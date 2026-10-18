import uuid

import dramatiq

from pci.db import session_scope
from pci.documents.locators import DspaceDocumentLocator
from pci.documents.service import prepare_document_text
from pci.documents.text import PyPdfTextExtractor
from pci.settings import Settings
from pci.storage.objects import S3ObjectStore


@dramatiq.actor(queue_name="documents")
def prepare_document_text_task(production_version_id: str) -> None:
    parsed_id = uuid.UUID(production_version_id)
    settings = Settings()  # type: ignore[call-arg]
    object_store = S3ObjectStore(
        endpoint_url=settings.object_storage_endpoint,
        bucket=settings.object_storage_bucket,
        access_key=settings.object_storage_access_key,
        secret_key=settings.object_storage_secret_key,
    )
    text_version_id: str | None = None
    with session_scope() as session:
        result = prepare_document_text(
            session,
            parsed_id,
            locator=DspaceDocumentLocator(timeout=settings.document_timeout_seconds),
            object_store=object_store,
            extractor=PyPdfTextExtractor(),
            max_document_bytes=settings.document_max_bytes,
            download_timeout=settings.document_timeout_seconds,
        )
        if result.text_version is not None:
            text_version_id = str(result.text_version.id)
    if text_version_id is not None:
        from pci.claims.tasks import extract_document_task

        extract_document_task.send(text_version_id)
