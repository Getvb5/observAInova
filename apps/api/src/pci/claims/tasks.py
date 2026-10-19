import uuid

import dramatiq

from pci.claims.providers import DeterministicExtractionProvider, HttpExtractionProvider
from pci.claims.service import run_extraction
from pci.db import session_scope
from pci.settings import Settings


@dramatiq.actor(queue_name="claims")
def extract_document_task(document_text_version_id: str, rerun: bool = False) -> None:
    settings = Settings()  # type: ignore[call-arg]
    if settings.claims_provider == "disabled":
        return
    provider = (
        HttpExtractionProvider(
            settings.claims_endpoint_url,
            settings.claims_api_key,
            settings.claims_model,
            settings.claims_timeout,
            schema_version=settings.claims_schema_version,
            instruction_version=settings.claims_instruction_version,
            allow_insecure=settings.app_env == "test",
        )
        if settings.claims_provider == "http"
        else DeterministicExtractionProvider({})
    )
    with session_scope() as session:
        run_extraction(session, uuid.UUID(document_text_version_id), provider, rerun=rerun)
