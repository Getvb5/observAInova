from pathlib import Path

import pytest

from pci.ingestion.connectors.fixture import FixtureConnector

FIXTURE_PATH = Path(__file__).parents[4] / "fixtures/repositories/sample-oai.json"


@pytest.mark.asyncio
async def test_fixture_connector_emits_common_contract() -> None:
    """Dropping or renaming a common record field must break fixture ingestion."""
    records = [record async for record in FixtureConnector(FIXTURE_PATH).harvest(cursor=None)]

    assert len(records) == 2
    assert records[0].source_identifier == "oai:sample:1"
    assert records[0].payload["title"] == "Tecnologia social para saneamento rural"
    assert records[0].source_url == "https://repositorio.example/items/oai:sample:1"
    assert records[0].rights == "CC BY 4.0"


@pytest.mark.asyncio
async def test_fixture_connector_preserves_missing_optional_payload_fields() -> None:
    """Filling absent source metadata with an invented value must break this test."""
    records = [record async for record in FixtureConnector(FIXTURE_PATH).harvest(cursor=None)]

    assert "abstract" not in records[1].payload
