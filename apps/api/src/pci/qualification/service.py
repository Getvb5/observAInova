"""Publish only structurally trustworthy metadata, never semantic intelligence."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.models.enums import RecordVisibility
from pci.models.production import DuplicateCandidate, Production, ProductionVersion
from pci.models.provenance import AuditEvent, RawRecord


@dataclass(frozen=True, slots=True)
class QualificationResult:
    production_id: uuid.UUID
    eligible: bool
    published: bool
    reasons: tuple[str, ...]


def qualify_production(
    session: Session,
    production_id: uuid.UUID,
    *,
    actor: str = "qualification",
) -> QualificationResult:
    """Audit structural eligibility and make a current metadata record public.

    The gate intentionally checks provenance and duplicate-review state only.  It
    does not infer, approve, or expose semantic intelligence.
    """
    production = session.get(Production, production_id)
    if production is None:
        raise ValueError(f"production does not exist: {production_id}")
    version = session.scalar(
        select(ProductionVersion).where(
            ProductionVersion.production_id == production_id,
            ProductionVersion.version == production.current_version_number,
        )
    )
    reasons: list[str] = []
    raw: RawRecord | None = None
    if version is None:
        reasons.append("current normalized version is missing")
    elif version.title.strip() == "":
        reasons.append("current normalized version has no title")
    else:
        raw = session.get(RawRecord, version.raw_record_id) if version.raw_record_id else None
        if raw is None:
            reasons.append("current normalized version has no raw provenance")
        elif raw.is_tombstone:
            reasons.append("current normalized provenance is a tombstone")
    if session.scalar(
        select(DuplicateCandidate.id).where(
            DuplicateCandidate.production_id == production_id,
            DuplicateCandidate.status == "pending",
        )
    ) is not None:
        reasons.append("pending duplicate candidate")

    if reasons:
        session.add(
            _audit_event(
                actor=actor,
                action="metadata.qualification_rejected",
                entity_type="Production",
                entity_id=production.id,
                before={"visibility": production.visibility.value},
                after={"visibility": production.visibility.value, "reasons": reasons},
                reason="; ".join(reasons),
            )
        )
        return QualificationResult(production.id, False, False, tuple(reasons))

    assert version is not None
    session.add(
        _audit_event(
            actor=actor,
            action="metadata.qualified",
            entity_type="ProductionVersion",
            entity_id=version.id,
            after={
                "production_id": str(production.id),
                "raw_record_id": str(raw.id) if raw is not None else None,
                "structural_checks": ["current_version", "title", "raw_provenance", "no_pending_duplicate"],
            },
        )
    )
    if production.visibility is RecordVisibility.METADATA_PUBLIC:
        return QualificationResult(production.id, True, False, ())

    before = {"visibility": production.visibility.value}
    production.visibility = RecordVisibility.METADATA_PUBLIC
    session.add(
        _audit_event(
            actor=actor,
            action="production.visibility_changed",
            entity_type="Production",
            entity_id=production.id,
            before=before,
            after={"visibility": RecordVisibility.METADATA_PUBLIC.value},
            reason="structural metadata qualification",
        )
    )
    return QualificationResult(production.id, True, True, ())


def record_tombstone(
    session: Session,
    raw: RawRecord,
    *,
    actor: str = "qualification",
) -> tuple[uuid.UUID, ...]:
    """Record a deletion against prior source provenance without overwriting it."""
    if not raw.is_tombstone:
        raise ValueError("only tombstone raw records can invalidate source access")
    production_ids = tuple(
        sorted(
            set(
                session.scalars(
                    select(Production.id)
                    .join(ProductionVersion, ProductionVersion.production_id == Production.id)
                    .join(RawRecord, RawRecord.id == ProductionVersion.raw_record_id)
                    .where(
                        RawRecord.source_id == raw.source_id,
                        RawRecord.source_identifier == raw.source_identifier,
                        RawRecord.is_tombstone.is_(False),
                    )
                ).all()
            ),
            key=str,
        )
    )
    if not production_ids:
        session.add(
            _audit_event(
                actor=actor,
                action="raw_record.tombstone_orphaned",
                entity_type="RawRecord",
                entity_id=raw.id,
                before=None,
                after={
                    "source_id": str(raw.source_id),
                    "source_identifier": raw.source_identifier,
                    "is_tombstone": True,
                },
                reason="no prior normalized production shares this source record identity",
            )
        )
        return ()
    for production_id in production_ids:
        session.add(
            _audit_event(
                actor=actor,
                action="raw_record.tombstoned",
                entity_type="Production",
                entity_id=production_id,
                before={"source_access_status": "available"},
                after={
                    "source_access_status": "unavailable",
                    "full_text_available": False,
                    "tombstone_raw_record_id": str(raw.id),
                },
                reason="source reported a deleted OAI-PMH record",
            )
        )
    return production_ids


def _audit_event(
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        reason=reason,
    )
