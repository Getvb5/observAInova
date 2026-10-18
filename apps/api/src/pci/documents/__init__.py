from pci.documents.contracts import (
    CorpusEligibilityResult,
    DocumentLocation,
    DocumentPreparationResult,
    DownloadedDocument,
    ExtractedPage,
    PdfTextExtractor,
)
from pci.documents.eligibility import evaluate_corpus_eligibility
from pci.documents.locators import DspaceDocumentLocator
from pci.documents.service import prepare_document_text
from pci.documents.text import PyPdfTextExtractor

__all__ = [
    "CorpusEligibilityResult",
    "DocumentLocation",
    "DocumentPreparationResult",
    "DownloadedDocument",
    "DspaceDocumentLocator",
    "ExtractedPage",
    "PdfTextExtractor",
    "PyPdfTextExtractor",
    "evaluate_corpus_eligibility",
    "prepare_document_text",
]
