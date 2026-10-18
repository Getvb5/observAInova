import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pci.auth.contracts import AuthPrincipal, Role
from pci.claims.enums import ContributionField
from pci.contributions.repository import curator_actor_keys
from pci.models.base import utc_now
from pci.models.claims import CandidateContribution, ExtractionRun
from pci.models.contributions import (
    ContributionCandidateSource,
    ContributionGrounding,
    ContributionVersion,
    ContributionVersionStatus,
    ScientificContribution,
)
from pci.models.documents import DocumentTextVersion
from pci.models.production import ProductionVersion
from pci.models.provenance import RawRecord, Source
from pci.models.publication import (
    OutboxStatus,
    PublicationAction,
    PublicationDecision,
    PublicationOutbox,
    PublishedContribution,
)
from pci.models.review import (
    ReviewCase,
    ReviewCaseKind,
    SampleSplit,
    SamplingRun,
)


class SeparationOfDutiesError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScientificProvenance:
    groundings: tuple[ContributionGrounding, ...]
    text_version: DocumentTextVersion
    production_version: ProductionVersion
    source: Source | None


def decide_publication(
    session: Session,
    version_id: uuid.UUID,
    action: PublicationAction,
    reason: str | None,
    supervisor: AuthPrincipal,
) -> PublicationDecision:
    if supervisor.roles.isdisjoint({Role.SUPERVISOR, Role.ADMIN}):
        raise SeparationOfDutiesError("supervisor role required")
    version = session.scalar(
        select(ContributionVersion).where(ContributionVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise ValueError("contribution version not found")
    pending = session.scalar(
        select(PublicationOutbox.id).where(
            PublicationOutbox.contribution_version_id == version.id,
            PublicationOutbox.status.in_((OutboxStatus.PENDING, OutboxStatus.PROCESSING)),
        )
    )
    if pending is not None:
        raise ValueError("pending publication decision already exists")
    if supervisor.actor_key in curator_actor_keys(session, version.id):
        raise SeparationOfDutiesError("validator cannot supervise the same version")
    normalized_reason = reason.strip() if reason else None
    if (
        action in {PublicationAction.RETURN, PublicationAction.SUPERSEDE, PublicationAction.REVOKE}
        and not normalized_reason
    ):
        raise ValueError("publication action requires a reason")
    active = session.scalar(
        select(PublishedContribution).where(
            PublishedContribution.scientific_contribution_id == version.scientific_contribution_id,
            PublishedContribution.active.is_(True),
        )
    )
    if action in {PublicationAction.PUBLISH, PublicationAction.RETURN}:
        if version.status is not ContributionVersionStatus.VALIDATED:
            raise ValueError("publication or return requires a validated version")
        if action is PublicationAction.PUBLISH and active is not None:
            raise ValueError("an active version must be superseded, not published again")
    elif action is PublicationAction.SUPERSEDE:
        if version.status is not ContributionVersionStatus.VALIDATED:
            raise ValueError("supersede requires a validated version")
        if active is None or active.version >= version.version:
            raise ValueError("supersede requires an older active version")
    elif action is PublicationAction.REVOKE:
        if (
            version.status is not ContributionVersionStatus.PUBLISHED
            or active is None
            or active.contribution_version_id != version.id
        ):
            raise ValueError("revocation requires the active published version")
    if action in {PublicationAction.PUBLISH, PublicationAction.SUPERSEDE}:
        _validated_scientific_provenance(session, version)
    decision = PublicationDecision(
        contribution_version_id=version.id,
        action=action,
        reason=normalized_reason,
        supervisor_actor_key=supervisor.actor_key,
    )
    session.add(decision)
    session.flush()
    session.add(
        PublicationOutbox(
            publication_decision_id=decision.id,
            contribution_version_id=version.id,
            scientific_contribution_id=version.scientific_contribution_id,
            action=action,
            status=OutboxStatus.PENDING,
        )
    )
    if action in {PublicationAction.PUBLISH, PublicationAction.SUPERSEDE}:
        version.status = ContributionVersionStatus.PUBLICATION_PENDING
    session.flush()
    return decision


def claim_next_publication_event(
    session: Session, *, lease_seconds: int = 300
) -> PublicationOutbox | None:
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    expired_before = utc_now() - timedelta(seconds=lease_seconds)
    event = session.scalar(
        select(PublicationOutbox)
        .where(
            or_(
                PublicationOutbox.status == OutboxStatus.PENDING,
                (
                    (PublicationOutbox.status == OutboxStatus.PROCESSING)
                    & (PublicationOutbox.attempt_started_at < expired_before)
                ),
            )
        )
        .order_by(PublicationOutbox.created_at, PublicationOutbox.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if event is None:
        return None
    event.status = OutboxStatus.PROCESSING
    event.attempt_token = str(uuid.uuid4())
    event.attempt_started_at = utc_now()
    event.error_code = None
    session.flush()
    return event


def process_publication_event(
    session: Session, event_id: uuid.UUID, attempt_token: str | None = None
) -> None:
    event = session.scalar(
        select(PublicationOutbox).where(PublicationOutbox.id == event_id).with_for_update()
    )
    if event is None:
        raise ValueError("publication event not found")
    if event.status is OutboxStatus.COMPLETED:
        return
    if attempt_token is not None and (
        event.status is not OutboxStatus.PROCESSING or event.attempt_token != attempt_token
    ):
        raise ValueError("publication event lease is no longer owned")
    if event.status is OutboxStatus.PENDING:
        event.status = OutboxStatus.PROCESSING
        event.attempt_token = attempt_token or str(uuid.uuid4())
        event.attempt_started_at = utc_now()
    elif event.status is not OutboxStatus.PROCESSING:
        raise ValueError("publication event is not processable")
    version = session.scalar(
        select(ContributionVersion)
        .where(ContributionVersion.id == event.contribution_version_id)
        .with_for_update()
    )
    if version is None:
        _fail_event(session, event, "version_not_found")
        return
    active = session.scalar(
        select(PublishedContribution)
        .where(
            PublishedContribution.scientific_contribution_id == event.scientific_contribution_id,
            PublishedContribution.active.is_(True),
        )
        .with_for_update()
    )
    if event.action in {PublicationAction.PUBLISH, PublicationAction.SUPERSEDE}:
        if version.status is not ContributionVersionStatus.PUBLICATION_PENDING:
            _fail_event(session, event, "invalid_version_state")
            return
        try:
            provenance = _validated_scientific_provenance(session, version)
        except ValueError:
            version.status = ContributionVersionStatus.VALIDATED
            _fail_event(session, event, "invalid_provenance")
            return
        if active is not None and active.version >= version.version:
            version.status = ContributionVersionStatus.SUPERSEDED
            _fail_event(session, event, "stale_version")
            return
        if event.action is PublicationAction.PUBLISH and active is not None:
            version.status = ContributionVersionStatus.VALIDATED
            _fail_event(session, event, "active_version_exists")
            return
        if event.action is PublicationAction.SUPERSEDE and active is None:
            version.status = ContributionVersionStatus.VALIDATED
            _fail_event(session, event, "active_version_missing")
            return
        if active is not None:
            active.active = False
            prior_version = session.get(ContributionVersion, active.contribution_version_id)
            if prior_version is not None:
                prior_version.status = ContributionVersionStatus.SUPERSEDED
        projection = session.scalar(
            select(PublishedContribution).where(
                PublishedContribution.contribution_version_id == version.id
            )
        )
        snapshot = _projection_snapshot(session, version, provenance)
        if projection is None:
            projection = PublishedContribution(**snapshot)
            session.add(projection)
        else:
            for key, value in snapshot.items():
                setattr(projection, key, value)
        version.status = ContributionVersionStatus.PUBLISHED
    elif event.action is PublicationAction.RETURN:
        if version.status is not ContributionVersionStatus.VALIDATED:
            _fail_event(session, event, "invalid_return_state")
            return
        version.status = ContributionVersionStatus.RETURNED
        decision = session.get(PublicationDecision, event.publication_decision_id)
        if decision is None or not decision.reason:
            _fail_event(session, event, "return_decision_missing")
            return
        from pci.contributions.service import open_return_correction

        open_return_correction(
            session,
            version,
            decision.reason,
            decision.supervisor_actor_key,
        )
    elif event.action is PublicationAction.REVOKE:
        if (
            version.status is not ContributionVersionStatus.PUBLISHED
            or active is None
            or active.contribution_version_id != version.id
        ):
            _fail_event(session, event, "invalid_revoke_state")
            return
        active.active = False
        version.status = ContributionVersionStatus.REVOKED
    event.status = OutboxStatus.COMPLETED
    event.completed_at = utc_now()
    session.flush()


def _fail_event(session: Session, event: PublicationOutbox, code: str) -> None:
    event.status = OutboxStatus.FAILED
    event.error_code = code
    event.completed_at = utc_now()
    session.flush()


def flag_contributions_for_source_review(
    session: Session, production_id: uuid.UUID, reason: str
) -> tuple[uuid.UUID, ...]:
    projections = session.scalars(
        select(PublishedContribution).where(
            PublishedContribution.production_id == production_id,
            PublishedContribution.active.is_(True),
        )
    ).all()
    pending_version_ids = set(
        session.scalars(
            select(ReviewCase.published_contribution_version_id).where(
                ReviewCase.kind == ReviewCaseKind.SOURCE_REVALIDATION,
                ReviewCase.published_contribution_version_id.in_(
                    [item.contribution_version_id for item in projections]
                ),
                ReviewCase.superseded_by_case_id.is_(None),
            )
        ).all()
    )
    revalidation = [
        item for item in projections if item.contribution_version_id not in pending_version_ids
    ]
    sampling_run = None
    if revalidation:
        sampling_run = SamplingRun(
            target_size=len(revalidation),
            selected_size=len(revalidation),
            test_fraction="0",
            double_code_fraction="0",
            seed=f"source-revalidation:{production_id}:{uuid.uuid4()}",
            rule_version="source-revalidation-v1",
        )
        session.add(sampling_run)
        session.flush()
    for projection in projections:
        projection.source_warning = reason[:1000]
    for selection_order, projection in enumerate(revalidation, start=1):
        assert sampling_run is not None
        review_case = ReviewCase(
            sampling_run_id=sampling_run.id,
            kind=ReviewCaseKind.SOURCE_REVALIDATION,
            published_contribution_version_id=projection.contribution_version_id,
            stratum={
                "institution": projection.institution,
                "publication_year": projection.publication_year,
                "production_type": projection.production_type,
                "text_scope": projection.source_scope,
                "contribution_type": projection.contribution_type,
            },
            split=SampleSplit.OPERATIONS,
            priority_reason=reason[:1000],
            selection_order=selection_order,
        )
        session.add(review_case)
        session.flush()
    session.flush()
    return tuple(item.scientific_contribution_id for item in projections)


def _validated_scientific_provenance(
    session: Session, version: ContributionVersion
) -> ScientificProvenance:
    contribution = session.get(ScientificContribution, version.scientific_contribution_id)
    if contribution is None:
        raise ValueError("scientific contribution not found")
    candidate_text_ids = set(
        session.scalars(
            select(ExtractionRun.document_text_version_id)
            .join(
                CandidateContribution,
                CandidateContribution.extraction_run_id == ExtractionRun.id,
            )
            .join(
                ContributionCandidateSource,
                ContributionCandidateSource.candidate_contribution_id == CandidateContribution.id,
            )
            .where(ContributionCandidateSource.contribution_version_id == version.id)
            .distinct()
        ).all()
    )
    if len(candidate_text_ids) != 1:
        raise ValueError("scientific provenance requires a single document text version")
    text_version_id = next(iter(candidate_text_ids))
    text_version = session.get(DocumentTextVersion, text_version_id)
    if text_version is None:
        raise ValueError("scientific provenance text version is missing")
    production_version = session.get(ProductionVersion, text_version.production_version_id)
    if production_version is None or production_version.production_id != contribution.production_id:
        raise ValueError("scientific provenance belongs to another production")
    groundings = tuple(
        session.scalars(
            select(ContributionGrounding).where(
                ContributionGrounding.contribution_version_id == version.id
            )
        ).all()
    )
    if {item.document_text_version_id for item in groundings} != {text_version.id}:
        raise ValueError("scientific provenance requires a single document text version")
    if any(item.source_scope != text_version.scope.value for item in groundings):
        raise ValueError("scientific provenance source scope does not match its text")
    scientific_fields = {
        field for field in ContributionField if getattr(version, field.value) is not None
    }
    if {item.field for item in groundings} != scientific_fields:
        raise ValueError("every published scientific field requires approved grounding")
    source = None
    if production_version.raw_record_id is not None:
        raw = session.get(RawRecord, production_version.raw_record_id)
        source = session.get(Source, raw.source_id) if raw is not None else None
    return ScientificProvenance(groundings, text_version, production_version, source)


def _projection_snapshot(
    session: Session,
    version: ContributionVersion,
    provenance: ScientificProvenance | None = None,
) -> dict[str, object]:
    contribution = session.get(ScientificContribution, version.scientific_contribution_id)
    if contribution is None:
        raise ValueError("scientific contribution not found")
    provenance = provenance or _validated_scientific_provenance(session, version)
    groundings = provenance.groundings
    production_version = provenance.production_version
    source = provenance.source
    values = {
        field.value: getattr(version, field.value)
        for field in ContributionField
        if getattr(version, field.value) is not None
    }
    values = {
        key: value.value if hasattr(value, "value") else value for key, value in values.items()
    }
    return {
        "scientific_contribution_id": contribution.id,
        "contribution_version_id": version.id,
        "production_id": contribution.production_id,
        "version": version.version,
        "contribution_type": version.contribution_type.value if version.contribution_type else None,
        "scientific_values": values,
        "approved_groundings": [
            {
                "field": item.field.value,
                "source_scope": item.source_scope,
                "page_number": item.page_number,
                "section": item.section,
                "quote": item.quote,
            }
            for item in groundings
        ],
        "institution": source.name if source else None,
        "publication_year": production_version.publication_year,
        "source_scope": provenance.text_version.scope.value,
        "production_type": production_version.type.value if production_version.type else None,
        "active": True,
        "source_warning": None,
        "validated_at": version.validated_at,
        "published_at": utc_now(),
    }
