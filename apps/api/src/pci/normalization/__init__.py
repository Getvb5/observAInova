"""Deterministic normalization and conservative duplicate detection."""

from pci.normalization.contracts import MatchDecision, NormalizedAuthor, NormalizedRecord
from pci.normalization.deduplication import match_production
from pci.normalization.records import normalize_record
from pci.normalization.service import persist_normalized_record

__all__ = [
    "MatchDecision",
    "NormalizedAuthor",
    "NormalizedRecord",
    "match_production",
    "normalize_record",
    "persist_normalized_record",
]
