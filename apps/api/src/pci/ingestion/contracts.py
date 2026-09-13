import uuid
from dataclasses import dataclass
from typing import Any

from pci.models.enums import HarvestStatus


@dataclass(frozen=True, slots=True)
class HarvestedRecord:
    source_identifier: str
    payload: dict[str, Any]
    source_url: str | None
    rights: str | None
    full_text: bytes | None = None
    media_type: str | None = None
    is_tombstone: bool = False


@dataclass(frozen=True, slots=True)
class HarvestResult:
    run_id: uuid.UUID
    status: HarvestStatus
    received: int
    inserted: int
    unchanged: int
    failed: int
    observed: int = 0
