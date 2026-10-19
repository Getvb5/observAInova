import asyncio
import uuid
from pathlib import Path

import dramatiq
from sqlalchemy import select

from pci.db import session_scope
from pci.ingestion.connectors.base import SourceConnector
from pci.ingestion.connectors.fixture import FixtureConnector
from pci.ingestion.connectors.oai_pmh import OaiPmhConnector
from pci.ingestion.pipeline import harvest_normalize_qualify_source
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import Source

INGESTION_AUDIT_ACTOR = "dramatiq:ingestion"


@dramatiq.actor(queue_name="ingestion")
def harvest_source_task(source_id: str) -> None:
    parsed_source_id = uuid.UUID(source_id)
    production_version_ids: list[str] = []
    with session_scope() as session:
        source = session.get(Source, parsed_source_id)
        if source is None:
            raise ValueError(f"source does not exist: {parsed_source_id}")
        connector = resolve_connector(source)
        result = asyncio.run(
            harvest_normalize_qualify_source(
                session,
                connector,
                parsed_source_id,
                actor=INGESTION_AUDIT_ACTOR,
            )
        )
        for production_id in result.normalized_production_ids:
            production = session.get(Production, production_id)
            if production is None:
                continue
            version = session.scalar(
                select(ProductionVersion).where(
                    ProductionVersion.production_id == production.id,
                    ProductionVersion.version == production.current_version_number,
                )
            )
            if version is not None:
                production_version_ids.append(str(version.id))
    from pci.documents.tasks import prepare_document_text_task

    for production_version_id in production_version_ids:
        prepare_document_text_task.send(production_version_id)


def resolve_connector(source: Source) -> SourceConnector:
    if source.base_url is None:
        raise ValueError(f"source {source.id} has no connector location")
    if source.connector_type == "fixture":
        return FixtureConnector(Path(source.base_url))
    if source.connector_type in {"oai_pmh", "oai-pmh"}:
        schedule = source.schedule or {}
        metadata_prefix = str(schedule.get("metadata_prefix", "oai_dc"))
        raw_set_spec = schedule.get("set_spec")
        set_spec = str(raw_set_spec) if raw_set_spec else None
        timeout = float(schedule.get("timeout", 30.0))
        max_retries = int(schedule.get("max_retries", 2))
        request_interval_seconds = float(schedule.get("request_interval_seconds", 0.0))
        retry_base_delay_seconds = float(schedule.get("retry_base_delay_seconds", 0.0))
        return OaiPmhConnector(
            source.base_url,
            metadata_prefix=metadata_prefix,
            set_spec=set_spec,
            timeout=timeout,
            max_retries=max_retries,
            request_interval_seconds=request_interval_seconds,
            retry_base_delay_seconds=retry_base_delay_seconds,
        )
    raise ValueError(f"unsupported connector type: {source.connector_type}")
