from collections.abc import AsyncIterator
from typing import Protocol

from pci.ingestion.contracts import HarvestedRecord


class SourceConnector(Protocol):
    def harvest(self, cursor: str | None) -> AsyncIterator[HarvestedRecord]: ...
