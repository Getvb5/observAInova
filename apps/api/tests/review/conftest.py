import hashlib
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from pci.claims.enums import CandidateStatus, ContributionType, ExtractionRunStatus
from pci.models.claims import CandidateContribution, ExtractionRun
from pci.models.documents import (
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.models.enums import ProductionType, RightsPolicy
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import RawRecord, Source

CandidateFactory = Callable[..., CandidateContribution]


@pytest.fixture
def candidate_factory(session: Session) -> CandidateFactory:
    def create(
        *,
        institution: str = "UFPE",
        knowledge_area: str | None = "Ciência da Informação",
        year: int = 2024,
        production_type: ProductionType = ProductionType.THESIS,
        scope: DocumentTextScope = DocumentTextScope.FULL_TEXT,
        contribution_type: ContributionType = ContributionType.INTERVENTION,
    ) -> CandidateContribution:
        source = Source(
            code=f"source-{uuid.uuid4()}",
            name=institution,
            connector_type="fixture",
            rights_policy=RightsPolicy.OPEN_COPY,
        )
        raw = RawRecord(
            source=source,
            source_identifier=str(uuid.uuid4()),
            payload={},
            checksum=uuid.uuid4().hex,
        )
        production = Production(canonical_key=f"local:{uuid.uuid4()}")
        session.add_all([raw, production])
        session.flush()
        version = ProductionVersion(
            production_id=production.id,
            raw_record_id=raw.id,
            version=1,
            title="Tese",
            publication_year=year,
            type=production_type,
            knowledge_areas=[knowledge_area] if knowledge_area else None,
        )
        session.add(version)
        session.flush()
        source_document = SourceDocument(
            production_version_id=version.id,
            status=SourceDocumentStatus.TEXT_EXTRACTED,
        )
        session.add(source_document)
        session.flush()
        text_value = f"Texto {uuid.uuid4()}"
        text = DocumentTextVersion(
            source_document_id=source_document.id,
            production_version_id=version.id,
            version=1,
            normalized_text=text_value,
            scope=scope,
            extraction_method=TextExtractionMethod.MANUAL,
            checksum=hashlib.sha256(text_value.encode()).hexdigest(),
        )
        session.add(text)
        session.flush()
        run = ExtractionRun(
            document_text_version_id=text.id,
            document_checksum=text.checksum,
            provider="fixture",
            model="fixture",
            schema_version="v1",
            instruction_version="v1",
            status=ExtractionRunStatus.SUCCEEDED,
        )
        session.add(run)
        session.flush()
        candidate = CandidateContribution(
            extraction_run_id=run.id,
            ordinal=1,
            status=CandidateStatus.GENERATED,
            suggested_type=contribution_type,
        )
        session.add(candidate)
        session.flush()
        return candidate

    return create
