from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from pci.models.documents import DocumentTextVersion, SourceDocument
    from pci.models.provenance import RawRecord


@dataclass(frozen=True, slots=True)
class DocumentLocation:
    url: str
    media_type: str
    rights: str | None


@dataclass(frozen=True, slots=True)
class DownloadedDocument:
    content: bytes
    media_type: str
    final_url: str


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class PreparedPage:
    page_number: int
    start_offset: int
    end_offset: int
    checksum: str


@dataclass(frozen=True, slots=True)
class PreparedText:
    normalized_text: str
    checksum: str
    pages: tuple[PreparedPage, ...]


@dataclass(frozen=True, slots=True)
class CorpusEligibilityResult:
    eligible: bool
    layer: Literal["analysis", "current"] | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentPreparationResult:
    eligibility: CorpusEligibilityResult
    source_document: "SourceDocument | None"
    text_version: "DocumentTextVersion | None"


class DocumentLocator(Protocol):
    def locate(self, raw: "RawRecord") -> DocumentLocation | None: ...


class PdfTextExtractor(Protocol):
    def extract(self, content: bytes) -> tuple[ExtractedPage, ...]: ...
