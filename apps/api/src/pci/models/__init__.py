"""Canonical metadata models."""

from pci.models.actors import Authorship, Organization, Person, ProductionOrganization
from pci.models.base import Base
from pci.models.claims import (
    CandidateClaim,
    CandidateContribution,
    CandidateGrounding,
    ExtractionRun,
)
from pci.models.contributions import (
    ContributionCandidateSource,
    ContributionGrounding,
    ContributionVersion,
    ReviewFieldDecision,
    ScientificContribution,
)
from pci.models.documents import (
    DocumentPage,
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.models.production import DuplicateCandidate, Production, ProductionVersion
from pci.models.provenance import (
    AuditEvent,
    HarvestObservation,
    HarvestRun,
    RawRecord,
    RawRecordObject,
    Source,
)
from pci.models.publication import PublicationDecision, PublicationOutbox, PublishedContribution
from pci.models.review import ReviewAssignment, ReviewCase, SamplingRun
from pci.models.territory import ProductionTerritory, Territory

__all__ = [
    "AuditEvent",
    "Authorship",
    "Base",
    "CandidateClaim",
    "CandidateContribution",
    "CandidateGrounding",
    "ContributionCandidateSource",
    "ContributionGrounding",
    "ContributionVersion",
    "DocumentPage",
    "DocumentTextScope",
    "DocumentTextVersion",
    "DuplicateCandidate",
    "ExtractionRun",
    "HarvestObservation",
    "HarvestRun",
    "Organization",
    "Person",
    "Production",
    "ProductionOrganization",
    "ProductionTerritory",
    "ProductionVersion",
    "PublicationDecision",
    "PublicationOutbox",
    "PublishedContribution",
    "RawRecord",
    "RawRecordObject",
    "ReviewAssignment",
    "ReviewCase",
    "ReviewFieldDecision",
    "SamplingRun",
    "ScientificContribution",
    "Source",
    "SourceDocument",
    "SourceDocumentStatus",
    "Territory",
    "TextExtractionMethod",
]
