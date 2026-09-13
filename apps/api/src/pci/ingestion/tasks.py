import asyncio
import uuid
from pathlib import Path

import dramatiq

from pci.db import session_scope
from pci.ingestion.connectors.base import SourceConnector
from pci.ingestion.connectors.fixture import FixtureConnector
from pci.ingestion.connectors.oai_pmh import OaiPmhConnector
from pci.ingestion.pipeline import harvest_normalize_qualify_source
from pci.models.provenance import Source

INGESTION_AUDIT_ACTOR = "dramatiq:ingestion"


@dramatiq.actor(queue_name="ingestion")
def harvest_source_task(source_id: str) -> None:
    parsed_source_id = uuid.UUID(source_id)
    with session_scope() as session:
        source = session.get(Source, parsed_source_id)
        if source is None:
            raise ValueError(f"source does not exist: {parsed_source_id}")
        connector = resolve_connector(source)
        asyncio.run(
            harvest_normalize_qualify_source(
                session,
                connector,
                parsed_source_id,
                actor=INGESTION_AUDIT_ACTOR,
            )
        )


def resolve_connector(source: Source) -> SourceConnector:
    if source.base_url is None:
        raise ValueError(f"source {source.id} has no connector location")
    if source.connector_type == "fixture":
        return FixtureConnector(Path(source.base_url))
    if source.connector_type in {"oai_pmh", "oai-pmh"}:
        schedule = source.schedule or {}
        metadata_prefix = str(schedule.get("metadata_prefix", "oai_dc"))
        timeout = float(schedule.get("timeout", 30.0))
        max_retries = int(schedule.get("max_retries", 2))
        return OaiPmhConnector(
            source.base_url,
            metadata_prefix=metadata_prefix,
            timeout=timeout,
            max_retries=max_retries,
        )
    raise ValueError(f"unsupported connector type: {source.connector_type}")
