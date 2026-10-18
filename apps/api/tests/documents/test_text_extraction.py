import hashlib
import io

from pypdf import PdfWriter

from pci.documents.contracts import ExtractedPage
from pci.documents.text import PyPdfTextExtractor, normalize_extracted_pages


def test_page_boundaries_preserve_unicode_repeated_text_and_exact_offsets() -> None:
    prepared = normalize_extracted_pages(
        (
            ExtractedPage(page_number=1, text="ação\r\nrepetida"),
            ExtractedPage(page_number=2, text="ação\nrepetida"),
        )
    )

    assert prepared.normalized_text == "ação\nrepetida\nação\nrepetida"
    assert [
        prepared.normalized_text[page.start_offset : page.end_offset] for page in prepared.pages
    ] == ["ação\nrepetida", "ação\nrepetida"]
    assert prepared.pages[0].start_offset == 0
    assert prepared.pages[1].start_offset == len("ação\nrepetida\n")
    assert prepared.checksum == hashlib.sha256(prepared.normalized_text.encode()).hexdigest()


def test_pypdf_extractor_returns_a_page_for_an_image_only_pdf() -> None:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)

    pages = PyPdfTextExtractor().extract(output.getvalue())

    assert pages == (ExtractedPage(page_number=1, text=""),)
