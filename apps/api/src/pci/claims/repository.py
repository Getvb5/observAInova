import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from pci.claims.contracts import ExtractionProvider
from pci.claims.enums import ExtractionRunStatus
from pci.models.claims import ExtractionRun


def run_identity_statement(
    *,
    document_checksum: str,
    provider: ExtractionProvider,
) -> Select[tuple[ExtractionRun]]:
    return select(ExtractionRun).where(
        ExtractionRun.document_checksum == document_checksum,
        ExtractionRun.provider == provider.provider_name,
        ExtractionRun.model == provider.model_name,
        ExtractionRun.schema_version == provider.schema_version,
        ExtractionRun.instruction_version == provider.instruction_version,
    )


def current_completed_run(
    session: Session,
    *,
    document_checksum: str,
    provider: ExtractionProvider,
) -> ExtractionRun | None:
    return session.scalar(
        run_identity_statement(document_checksum=document_checksum, provider=provider)
        .where(ExtractionRun.status == ExtractionRunStatus.SUCCEEDED)
        .order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc())
        .limit(1)
    )


def latest_run(
    session: Session,
    *,
    document_checksum: str,
    provider: ExtractionProvider,
) -> ExtractionRun | None:
    return session.scalar(
        run_identity_statement(document_checksum=document_checksum, provider=provider)
        .order_by(ExtractionRun.created_at.desc(), ExtractionRun.id.desc())
        .limit(1)
    )


def lock_document_text_version(document_text_version_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    from pci.models.documents import DocumentTextVersion

    return (
        select(DocumentTextVersion.id)
        .where(DocumentTextVersion.id == document_text_version_id)
        .with_for_update()
    )
