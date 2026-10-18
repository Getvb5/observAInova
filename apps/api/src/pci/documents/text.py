import hashlib
import io

from pypdf import PdfReader

from pci.documents.contracts import ExtractedPage, PreparedPage, PreparedText


class PyPdfTextExtractor:
    def extract(self, content: bytes) -> tuple[ExtractedPage, ...]:
        reader = PdfReader(io.BytesIO(content))
        return tuple(
            ExtractedPage(page_number=index, text=page.extract_text() or "")
            for index, page in enumerate(reader.pages, start=1)
        )


def normalize_extracted_pages(pages: tuple[ExtractedPage, ...]) -> PreparedText:
    expected_numbers = tuple(range(1, len(pages) + 1))
    if tuple(page.page_number for page in pages) != expected_numbers:
        raise ValueError("extracted pages must be ordered and one-based")
    normalized_pages = tuple(_normalize_line_endings(page.text) for page in pages)
    normalized_text = "\n".join(normalized_pages)
    prepared_pages: list[PreparedPage] = []
    offset = 0
    for index, (page, text) in enumerate(zip(pages, normalized_pages, strict=True)):
        start = offset
        end = start + len(text)
        prepared_pages.append(
            PreparedPage(
                page_number=page.page_number,
                start_offset=start,
                end_offset=end,
                checksum=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )
        offset = end + (1 if index < len(pages) - 1 else 0)
    return PreparedText(
        normalized_text=normalized_text,
        checksum=hashlib.sha256(normalized_text.encode("utf-8")).hexdigest(),
        pages=tuple(prepared_pages),
    )


def normalize_plain_text(value: str) -> str:
    return _normalize_line_endings(value)


def _normalize_line_endings(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")
