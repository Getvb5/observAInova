import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

from pci.ingestion.contracts import HarvestedRecord


class FixtureConnector:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def harvest(self, cursor: str | None) -> AsyncIterator[HarvestedRecord]:
        del cursor
        document = cast(object, json.loads(self.path.read_text(encoding="utf-8")))
        if not isinstance(document, list):
            raise TypeError("fixture root must be a list of records")

        for item in document:
            if not isinstance(item, dict):
                raise TypeError("each fixture record must be an object")
            record = cast(dict[str, Any], item)
            payload = record["payload"]
            if not isinstance(payload, dict):
                raise TypeError("fixture record payload must be an object")
            yield HarvestedRecord(
                source_identifier=str(record["source_identifier"]),
                payload=cast(dict[str, Any], payload),
                source_url=_optional_string(record["source_url"]),
                rights=_optional_string(record["rights"]),
            )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("nullable record fields must be strings or null")
    return value
