import hashlib
import uuid
from collections import defaultdict
from typing import cast

from sqlalchemy import ColumnElement, and_, exists, extract, or_, select
from sqlalchemy.orm import Session

from pci.models.actors import Authorship, Person
from pci.models.production import Production, ProductionVersion
from pci.normalization.contracts import MatchDecision, NormalizedRecord
from pci.normalization.text import exact_text_key, trigram_similarity

REVIEW_THRESHOLD = 0.90
FUZZY_CANDIDATE_LIMIT = 100
EXACT_CANDIDATE_LIMIT = 8
EXACT_IDENTIFIER_KEYS = ("doi", "patent", "handle", "source")
IDENTIFIER_DIGEST_COLUMNS = {
    "doi": ProductionVersion.doi_digest,
    "patent": ProductionVersion.patent_digest,
    "handle": ProductionVersion.handle_digest,
    "source": ProductionVersion.source_digest,
}


def matching_digest(value: str) -> str:
    """Return an indexed candidate key; equality still checks the original value."""
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def match_production(session: Session, record: NormalizedRecord) -> MatchDecision:
    for identifier_key in EXACT_IDENTIFIER_KEYS:
        incoming = record.identifiers.get(identifier_key)
        if incoming is None:
            continue
        production_id = _production_for_exact_identifier(session, identifier_key, incoming)
        if production_id is not None:
            return MatchDecision("exact", production_id, (f"exact identifier: {identifier_key}",))

    incoming_authors = {exact_text_key(author.name) for author in record.authors}
    exact_title_match = _production_for_exact_title_year_author(session, record, incoming_authors)
    if exact_title_match is not None:
        return MatchDecision(
            "exact",
            exact_title_match,
            ("exact title, publication year, and author",),
        )

    if record.title is None:
        return MatchDecision("new", None, ("no conservative duplicate match",))

    candidates = _bounded_fuzzy_candidates(session, record, incoming_authors)
    if not candidates:
        return MatchDecision("new", None, ("no conservative duplicate match",))
    author_keys = _author_keys(session, tuple(candidates))
    review_matches: list[tuple[float, str, ProductionVersion, tuple[str, ...]]] = []
    for production_id, version in candidates.items():
        score = trigram_similarity(record.title, version.title)
        if score < REVIEW_THRESHOLD:
            continue
        compatibility = _compatibility_reasons(
            record,
            version,
            incoming_authors,
            author_keys[production_id],
        )
        if compatibility is None:
            continue
        reasons = (
            f"title trigram similarity {score:.3f} at or above {REVIEW_THRESHOLD:.3f}",
            *compatibility,
        )
        review_matches.append((score, str(production_id), version, reasons))

    if not review_matches:
        return MatchDecision("new", None, ("no conservative duplicate match",))
    score, _, version, reasons = max(review_matches, key=lambda item: (item[0], item[1]))
    return MatchDecision("review", version.production_id, reasons, score)


def _production_for_exact_identifier(
    session: Session, identifier_key: str, incoming: str
) -> uuid.UUID | None:
    digest_column = IDENTIFIER_DIGEST_COLUMNS[identifier_key]
    identifiers = ProductionVersion.identifiers
    production_id = session.scalar(
        select(Production.id)
        .join(
            ProductionVersion,
            ProductionVersion.production_id == Production.id,
        )
        .where(
            digest_column == matching_digest(incoming),
            identifiers[identifier_key].as_string() == incoming,
        )
        .order_by(
            Production.created_at,
            ProductionVersion.version.desc(),
            Production.id,
        )
        .limit(1)
    )
    return production_id


def _production_for_exact_title_year_author(
    session: Session,
    record: NormalizedRecord,
    incoming_authors: set[str],
) -> uuid.UUID | None:
    if record.title is None or record.publication_year is None or not incoming_authors:
        return None
    author_digests = [matching_digest(name) for name in sorted(incoming_authors)]
    rows = session.execute(
        select(Production.id, ProductionVersion)
        .join(
            ProductionVersion,
            ProductionVersion.production_id == Production.id,
        )
        .where(
            ProductionVersion.version == Production.current_version_number,
            ProductionVersion.title_digest == matching_digest(exact_text_key(record.title)),
            _version_year_matches(record.publication_year),
            _has_author_digest(author_digests),
        )
        .order_by(Production.id)
        .limit(EXACT_CANDIDATE_LIMIT)
    ).all()
    if not rows:
        return None
    production_ids = tuple(production_id for production_id, _ in rows)
    author_keys = _author_keys(session, production_ids)
    title_key = exact_text_key(record.title)
    for production_id, version in rows:
        if (
            exact_text_key(version.title) == title_key
            and incoming_authors & author_keys[production_id]
        ):
            return cast(uuid.UUID, production_id)
    return None


def _bounded_fuzzy_candidates(
    session: Session,
    record: NormalizedRecord,
    incoming_authors: set[str],
) -> dict[uuid.UUID, ProductionVersion]:
    compatibility_filters: list[ColumnElement[bool]] = []
    if record.publication_year is not None:
        compatibility_filters.append(_version_year_matches(record.publication_year))
    if incoming_authors:
        compatibility_filters.append(
            _has_author_digest([matching_digest(name) for name in sorted(incoming_authors)])
        )
    if not compatibility_filters:
        return {}
    rows = session.execute(
        select(Production.id, ProductionVersion)
        .join(
            ProductionVersion,
            ProductionVersion.production_id == Production.id,
        )
        .where(
            ProductionVersion.version == Production.current_version_number,
            or_(*compatibility_filters),
        )
        .order_by(Production.id)
        .limit(FUZZY_CANDIDATE_LIMIT)
    ).all()
    return {production_id: version for production_id, version in rows}


def _has_author_digest(author_digests: list[str]) -> ColumnElement[bool]:
    return exists(
        select(1)
        .select_from(Authorship)
        .join(Person, Person.id == Authorship.person_id)
        .where(
            Authorship.production_id == Production.id,
            Person.name_digest.in_(author_digests),
        )
    )


def _version_year_matches(publication_year: int) -> ColumnElement[bool]:
    return or_(
        ProductionVersion.publication_year == publication_year,
        and_(
            ProductionVersion.publication_year.is_(None),
            extract("year", ProductionVersion.publication_date) == publication_year,
        ),
    )


def _author_keys(
    session: Session, production_ids: tuple[uuid.UUID, ...]
) -> dict[uuid.UUID, set[str]]:
    result: dict[uuid.UUID, set[str]] = defaultdict(set)
    if not production_ids:
        return result
    for production_id, name in session.execute(
        select(Authorship.production_id, Person.name)
        .join(Person, Person.id == Authorship.person_id)
        .where(Authorship.production_id.in_(production_ids))
    ):
        result[production_id].add(exact_text_key(name))
    return result


def _compatibility_reasons(
    record: NormalizedRecord,
    version: ProductionVersion,
    incoming_authors: set[str],
    existing_authors: set[str],
) -> tuple[str, ...] | None:
    existing_year = _publication_year(version)
    year_matches = (
        record.publication_year is not None
        and existing_year is not None
        and record.publication_year == existing_year
    )
    year_conflicts = (
        record.publication_year is not None
        and existing_year is not None
        and record.publication_year != existing_year
    )
    author_matches = bool(
        incoming_authors and existing_authors and incoming_authors & existing_authors
    )
    author_conflicts = bool(incoming_authors and existing_authors and not author_matches)
    if year_matches or author_matches:
        reasons: list[str] = []
        if year_matches:
            reasons.append("compatible publication year")
        if author_matches:
            reasons.append("compatible author")
        return tuple(reasons)
    if year_conflicts or author_conflicts:
        return None
    return None


def _publication_year(version: ProductionVersion) -> int | None:
    if version.publication_year is not None:
        return version.publication_year
    if version.publication_date is not None:
        return version.publication_date.year
    return None
