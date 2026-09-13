import hashlib
import uuid
from dataclasses import replace
from typing import Any, cast

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pci.ingestion.contracts import HarvestedRecord
from pci.models.actors import Authorship, Organization, Person, ProductionOrganization
from pci.models.enums import RecordVisibility
from pci.models.production import DuplicateCandidate, Production, ProductionVersion
from pci.models.provenance import AuditEvent, RawRecord
from pci.normalization.contracts import MatchDecision, NormalizedAuthor, NormalizedRecord
from pci.normalization.deduplication import match_production, matching_digest
from pci.normalization.records import normalize_record
from pci.normalization.text import exact_text_key

ResolvedAuthor = tuple[NormalizedAuthor, Person, Organization | None, int]


def persist_normalized_record(session: Session, raw_record_id: uuid.UUID) -> uuid.UUID:
    existing_version = _version_for_raw_record(session, raw_record_id)
    if existing_version is not None:
        return existing_version.production_id

    raw = session.get(RawRecord, raw_record_id)
    if raw is None:
        raise ValueError(f"raw record does not exist: {raw_record_id}")
    harvested = HarvestedRecord(
        source_identifier=raw.source_identifier,
        payload=raw.payload,
        source_url=raw.source_url,
        rights=raw.rights_snapshot,
    )
    record = normalize_record(harvested)
    scoped_source = _source_scoped_identifier(raw.source_id, record.source_identifier)
    report = {
        "transformations": [
            *record.normalization_report["transformations"],
            {
                "field": "source_stable_identifier",
                "original": record.source_identifier,
                "normalized": scoped_source,
                "source_id": str(raw.source_id),
            },
        ],
        "missing_fields": list(record.missing_fields),
    }
    identifiers = {**record.identifiers, "source": scoped_source}
    record = replace(
        record,
        identifiers=identifiers,
        normalization_report=report,
        full_text_available=raw.stored_object is not None and raw.stored_object.status == "stored",
    )
    if record.title is None:
        raise ValueError("normalized title is required before persistence")

    provenance_production = _production_for_source_provenance(session, raw)
    recovered_production_id: uuid.UUID | None = None
    for version_attempt in range(2):
        decision = (
            MatchDecision(
                "exact",
                recovered_production_id,
                ("concurrent canonical key",),
            )
            if recovered_production_id is not None
            else MatchDecision(
                "exact",
                provenance_production.id,
                ("immutable source provenance",),
            )
            if provenance_production is not None
            else match_production(session, record)
        )
        try:
            with session.begin_nested():
                if decision.kind == "exact":
                    if decision.production_id is None:
                        raise RuntimeError("exact match did not identify a production")
                    production = session.get(Production, decision.production_id)
                    if production is None:
                        raise RuntimeError("matched production disappeared")
                else:
                    production = _create_production(session, record, decision)

                record, resolved_authors = _reconcile_authors(session, production, record)
                _create_version(session, production, raw_record_id, record, decision)
                _sync_production_organizations(session, production, record)
                _sync_authorship(session, production, resolved_authors)
                if decision.kind == "review":
                    _create_duplicate_candidate(session, production, decision)
            return production.id
        except IntegrityError as error:
            concurrent_version = _version_for_raw_record(session, raw_record_id)
            if _is_raw_record_conflict(error) and concurrent_version is not None:
                return concurrent_version.production_id
            if _is_canonical_key_conflict(error) and decision.kind == "new":
                winner = _production_for_canonical_key(session, _canonical_key(record))
                if winner is not None:
                    recovered_production_id = winner.id
                    continue
            if (
                _is_version_allocation_conflict(error)
                and decision.kind == "exact"
                and version_attempt == 0
            ):
                continue
            raise

    raise RuntimeError("production version allocation retry was exhausted")


def _version_for_raw_record(session: Session, raw_record_id: uuid.UUID) -> ProductionVersion | None:
    return session.scalar(
        select(ProductionVersion).where(ProductionVersion.raw_record_id == raw_record_id)
    )


def _production_for_source_provenance(session: Session, raw: RawRecord) -> Production | None:
    production_ids = tuple(
        session.scalars(
            select(Production.id)
            .distinct()
            .join(
                ProductionVersion,
                ProductionVersion.production_id == Production.id,
            )
            .join(RawRecord, RawRecord.id == ProductionVersion.raw_record_id)
            .where(
                RawRecord.source_id == raw.source_id,
                RawRecord.source_identifier == raw.source_identifier,
                RawRecord.id != raw.id,
            )
            .order_by(Production.id)
            .limit(2)
        ).all()
    )
    if len(production_ids) > 1:
        raise ValueError("ambiguous source provenance: multiple productions share the identity")
    return session.get(Production, production_ids[0]) if production_ids else None


def _is_raw_record_conflict(error: IntegrityError) -> bool:
    return _is_unique_conflict(
        error,
        "uq_production_versions_raw_record",
        ("production_versions.raw_record_id",),
    )


def _is_version_allocation_conflict(error: IntegrityError) -> bool:
    return _is_unique_conflict(
        error,
        "uq_production_versions_production_version",
        ("production_versions.production_id", "production_versions.version"),
    )


def _is_canonical_key_conflict(error: IntegrityError) -> bool:
    return _is_unique_conflict(
        error,
        "uq_productions_canonical_key",
        ("productions.canonical_key",),
    )


def _is_unique_conflict(
    error: IntegrityError, constraint: str, sqlite_columns: tuple[str, ...]
) -> bool:
    diagnostics = getattr(error.orig, "diag", None)
    if getattr(diagnostics, "constraint_name", None) == constraint:
        return True
    message = str(error.orig).casefold()
    return all(column.casefold() in message for column in sqlite_columns)


def _production_lock_statement(production_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    return select(Production.id).where(Production.id == production_id).with_for_update()


def _production_for_canonical_key(session: Session, canonical_key: str) -> Production | None:
    return session.scalar(select(Production).where(Production.canonical_key == canonical_key))


def _create_production(
    session: Session, record: NormalizedRecord, decision: MatchDecision
) -> Production:
    production = Production(canonical_key=_canonical_key(record), visibility="private")
    session.add(production)
    session.flush()
    session.add(
        _audit_event(
            action="production.created",
            entity_type="Production",
            entity_id=production.id,
            after={
                "canonical_key": production.canonical_key,
                "visibility": "private",
            },
            reason="; ".join(decision.reasons),
        )
    )
    return production


def _canonical_key(record: NormalizedRecord) -> str:
    for key in ("doi", "patent", "handle", "source"):
        if value := record.identifiers.get(key):
            canonical_key = f"{key}:{value}"
            if len(canonical_key) <= 1024:
                return canonical_key
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            return f"{key}:sha256:{digest}"
    return f"local:{uuid.uuid4()}"


def _source_scoped_identifier(source_id: uuid.UUID, source_identifier: str) -> str:
    """Build a stable source identity without relying on mutable display codes."""
    return f"{source_id}:{source_identifier}"


def _create_version(
    session: Session,
    production: Production,
    raw_record_id: uuid.UUID,
    record: NormalizedRecord,
    decision: MatchDecision,
) -> None:
    assert record.title is not None
    session.execute(_production_lock_statement(production.id))
    previous = session.scalar(
        select(func.max(ProductionVersion.version)).where(
            ProductionVersion.production_id == production.id
        )
    )
    version_number = (previous or 0) + 1
    before_number = production.current_version_number
    production.current_version_number = version_number
    visibility_event: AuditEvent | None = None
    if production.visibility is RecordVisibility.METADATA_PUBLIC:
        visibility_event = _audit_event(
            action="production.visibility_changed",
            entity_type="Production",
            entity_id=production.id,
            before={"visibility": RecordVisibility.METADATA_PUBLIC.value},
            after={"visibility": RecordVisibility.PRIVATE.value},
            reason="current version awaits structural metadata qualification",
        )
        production.visibility = RecordVisibility.PRIVATE
    version = ProductionVersion(
        production_id=production.id,
        raw_record_id=raw_record_id,
        version=version_number,
        title=record.title,
        title_digest=matching_digest(exact_text_key(record.title)),
        abstract=record.abstract,
        publication_date=record.publication_date,
        publication_year=record.publication_year,
        language=record.language,
        type=record.type,
        identifiers=dict(record.identifiers),
        doi_digest=_identifier_digest(record, "doi"),
        patent_digest=_identifier_digest(record, "patent"),
        handle_digest=_identifier_digest(record, "handle"),
        source_digest=_identifier_digest(record, "source"),
        keywords=list(record.keywords),
        publishers=list(record.publishers),
        source_url=record.source_url,
        full_text_available=record.full_text_available,
        rights=record.rights,
        normalization_report=record.normalization_report,
    )
    session.add(version)
    session.flush()
    audit_events = [
        _audit_event(
            action="production.version_advanced",
            entity_type="Production",
            entity_id=production.id,
            before={"current_version_number": before_number},
            after={"current_version_number": version_number},
            reason="; ".join(decision.reasons),
        ),
        _audit_event(
            action="production_version.created",
            entity_type="ProductionVersion",
            entity_id=version.id,
            after={
                "production_id": str(production.id),
                "raw_record_id": str(raw_record_id),
                "version": version_number,
            },
            reason="; ".join(decision.reasons),
        ),
    ]
    if visibility_event is not None:
        audit_events.append(visibility_event)
    session.add_all(audit_events)


def _reconcile_authors(
    session: Session, production: Production, record: NormalizedRecord
) -> tuple[NormalizedRecord, list[ResolvedAuthor]]:
    """Resolve aliases before versioning so duplicate identities are auditable discards."""
    organizations: dict[str, Organization] = {}
    resolved: list[ResolvedAuthor] = []
    retained_authors: list[NormalizedAuthor] = []
    seen: dict[tuple[uuid.UUID, uuid.UUID | None], int] = {}
    transformations = [
        dict(item)
        for item in cast(list[dict[str, Any]], record.normalization_report["transformations"])
    ]
    for original_position, author in enumerate(record.authors):
        person = _find_or_create_person(session, author)
        organization = None
        if author.organization is not None:
            organization = organizations.get(exact_text_key(author.organization))
            if organization is None:
                organization = _find_or_create_organization(session, author.organization)
                organizations[exact_text_key(author.organization)] = organization
        identity = (person.id, organization.id if organization is not None else None)
        retained_position = seen.get(identity)
        if retained_position is not None:
            discard = {
                "field": f"authors[{original_position}]",
                "original": {
                    "name": author.name,
                    "orcid": author.orcid,
                    "organization": author.organization,
                },
                "retained": f"authors[{retained_position}]",
                "resolved_identity": {
                    "person_id": str(person.id),
                    "organization_id": str(organization.id) if organization is not None else None,
                },
                "reason": "resolved_identity_duplicate_discarded",
            }
            transformations.append(discard)
            session.add(
                _audit_event(
                    action="authorship.alias_discarded",
                    entity_type="Production",
                    entity_id=production.id,
                    after=discard,
                    reason="resolved author alias duplicates an existing authorship identity",
                )
            )
            continue
        seen[identity] = original_position
        retained_authors.append(author)
        resolved.append((author, person, organization, len(retained_authors)))
    report = {**record.normalization_report, "transformations": transformations}
    return replace(record, authors=tuple(retained_authors), normalization_report=report), resolved


def _sync_authorship(
    session: Session, production: Production, resolved_authors: list[ResolvedAuthor]
) -> None:
    desired = [
        (person, organization, position) for _, person, organization, position in resolved_authors
    ]

    existing = list(
        session.scalars(select(Authorship).where(Authorship.production_id == production.id))
    )
    unmatched = sorted(existing, key=lambda authorship: (authorship.position, str(authorship.id)))
    matched: dict[int, Authorship] = {}

    for desired_index, (person, organization, _) in enumerate(desired):
        organization_id = organization.id if organization is not None else None
        authorship = next(
            (
                candidate
                for candidate in unmatched
                if candidate.person_id == person.id and candidate.organization_id == organization_id
            ),
            None,
        )
        if authorship is not None:
            unmatched.remove(authorship)
            matched[desired_index] = authorship

    for desired_index, (person, organization, position) in enumerate(desired):
        organization_id = organization.id if organization is not None else None
        authorship = matched.get(desired_index)
        if authorship is None:
            authorship = next(
                (candidate for candidate in unmatched if candidate.person_id == person.id),
                None,
            )
            if authorship is None:
                authorship = Authorship(
                    production_id=production.id,
                    person_id=person.id,
                    organization_id=organization_id,
                    position=position,
                )
                session.add(authorship)
                session.flush()
                session.add(
                    _audit_event(
                        action="authorship.created",
                        entity_type="Authorship",
                        entity_id=authorship.id,
                        after=_authorship_snapshot(authorship),
                    )
                )
                continue
            unmatched.remove(authorship)
            matched[desired_index] = authorship

    for authorship in unmatched:
        session.delete(authorship)
        session.add(
            _audit_event(
                action="authorship.removed",
                entity_type="Authorship",
                entity_id=authorship.id,
                before=_authorship_snapshot(authorship),
            )
        )
    session.flush()

    for desired_index, (_, organization, position) in enumerate(desired):
        authorship = matched.get(desired_index)
        if authorship is None:
            continue
        organization_id = organization.id if organization is not None else None
        if authorship.organization_id == organization_id and authorship.position == position:
            continue
        before = _authorship_snapshot(authorship)
        authorship.organization_id = organization_id
        authorship.position = position
        session.add(
            _audit_event(
                action="authorship.updated",
                entity_type="Authorship",
                entity_id=authorship.id,
                before=before,
                after=_authorship_snapshot(authorship),
            )
        )


def _authorship_snapshot(authorship: Authorship) -> dict[str, str | int | None]:
    return {
        "production_id": str(authorship.production_id),
        "person_id": str(authorship.person_id),
        "organization_id": (
            str(authorship.organization_id) if authorship.organization_id is not None else None
        ),
        "position": authorship.position,
    }


def _sync_production_organizations(
    session: Session, production: Production, record: NormalizedRecord
) -> None:
    desired = {
        organization.id: organization
        for organization in (
            _find_or_create_organization(session, name) for name in record.organizations
        )
    }
    existing = {
        link.organization_id: link
        for link in session.scalars(
            select(ProductionOrganization).where(
                ProductionOrganization.production_id == production.id
            )
        )
    }
    for organization_id, link in existing.items():
        if organization_id in desired:
            continue
        session.delete(link)
        session.add(
            _audit_event(
                action="production_organization.removed",
                entity_type="ProductionOrganization",
                entity_id=production.id,
                before={
                    "production_id": str(production.id),
                    "organization_id": str(organization_id),
                },
            )
        )
    for organization_id, organization in desired.items():
        if organization_id in existing:
            continue
        session.add(
            ProductionOrganization(
                production_id=production.id,
                organization_id=organization_id,
            )
        )
        session.add(
            _audit_event(
                action="production_organization.created",
                entity_type="ProductionOrganization",
                entity_id=production.id,
                after={
                    "production_id": str(production.id),
                    "organization_id": str(organization_id),
                    "organization_name": organization.name,
                },
            )
        )


def _find_or_create_person(session: Session, author: NormalizedAuthor) -> Person:
    name_key = exact_text_key(author.name)
    statement = select(Person)
    if author.orcid is not None:
        statement = statement.where(Person.orcid == author.orcid)
    else:
        statement = statement.where(
            Person.orcid.is_(None),
            Person.name_digest == matching_digest(name_key),
        )
    candidates = list(session.scalars(statement.order_by(Person.id).limit(8)))
    if author.orcid is None:
        candidates = [person for person in candidates if exact_text_key(person.name) == name_key]
    if candidates:
        return min(candidates, key=lambda person: str(person.id))
    new_identifiers: dict[str, Any] | None = {"orcid": author.orcid} if author.orcid else None
    person = Person(
        name=author.name,
        name_digest=matching_digest(name_key),
        orcid=author.orcid,
        identifiers=new_identifiers,
    )
    session.add(person)
    session.flush()
    session.add(
        _audit_event(
            action="person.created",
            entity_type="Person",
            entity_id=person.id,
            after={"name": person.name, "identifiers": new_identifiers},
        )
    )
    return person


def _find_or_create_organization(session: Session, name: str) -> Organization:
    name_key = exact_text_key(name)
    candidates = session.scalars(
        select(Organization)
        .where(Organization.name_digest == matching_digest(name_key))
        .order_by(Organization.id)
        .limit(8)
    ).all()
    exact_matches = [
        organization for organization in candidates if exact_text_key(organization.name) == name_key
    ]
    if exact_matches:
        return min(exact_matches, key=lambda organization: str(organization.id))
    organization = Organization(name=name, name_digest=matching_digest(name_key))
    session.add(organization)
    session.flush()
    session.add(
        _audit_event(
            action="organization.created",
            entity_type="Organization",
            entity_id=organization.id,
            after={"name": organization.name},
        )
    )
    return organization


def _identifier_digest(record: NormalizedRecord, key: str) -> str | None:
    value = record.identifiers.get(key)
    return matching_digest(value) if value is not None else None


def _create_duplicate_candidate(
    session: Session, production: Production, decision: MatchDecision
) -> None:
    if decision.production_id is None or decision.score is None:
        raise RuntimeError("review match is missing its candidate or score")
    candidate = DuplicateCandidate(
        production_id=production.id,
        candidate_production_id=decision.production_id,
        score=decision.score,
        reasons=list(decision.reasons),
        status="pending",
    )
    session.add(candidate)
    session.flush()
    session.add(
        _audit_event(
            action="duplicate_candidate.created",
            entity_type="DuplicateCandidate",
            entity_id=candidate.id,
            after={
                "production_id": str(production.id),
                "candidate_production_id": str(decision.production_id),
                "score": decision.score,
                "reasons": list(decision.reasons),
                "status": "pending",
            },
            reason="; ".join(decision.reasons),
        )
    )


def _audit_event(
    *,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        actor="normalization",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        reason=reason,
    )
