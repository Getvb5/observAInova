import hashlib
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pci.main import create_app
from pci.models.claims import CandidateClaim, CandidateContribution, ExtractionRun
from pci.models.documents import (
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.models.enums import ProductionType, RecordVisibility, RightsPolicy
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import RawRecord, Source


def test_public_endpoints_never_serialize_candidate_marker(session: Session) -> None:
    marker = "PRIVATE-CANDIDATE-8e071f"
    source = Source(
        code=f"privacy-{uuid.uuid4()}",
        name="UFPE",
        connector_type="fixture",
        rights_policy=RightsPolicy.OPEN_COPY,
    )
    raw = RawRecord(
        source=source,
        source_identifier=str(uuid.uuid4()),
        payload={},
        source_url="https://repositorio.example/items/1",
        checksum=uuid.uuid4().hex,
    )
    production = Production(
        canonical_key=f"local:{uuid.uuid4()}",
        current_version_number=1,
        visibility=RecordVisibility.METADATA_PUBLIC,
    )
    session.add_all([raw, production])
    session.flush()
    version = ProductionVersion(
        production_id=production.id,
        raw_record_id=raw.id,
        version=1,
        title="Tese pública",
        publication_year=2024,
        type=ProductionType.THESIS,
    )
    session.add(version)
    session.flush()
    document = SourceDocument(
        production_version_id=version.id,
        status=SourceDocumentStatus.TEXT_EXTRACTED,
    )
    session.add(document)
    session.flush()
    text = DocumentTextVersion(
        source_document_id=document.id,
        production_version_id=version.id,
        version=1,
        normalized_text="texto público de origem",
        scope=DocumentTextScope.FULL_TEXT,
        extraction_method=TextExtractionMethod.MANUAL,
        checksum=hashlib.sha256(b"texto publico").hexdigest(),
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
        status="succeeded",
    )
    session.add(run)
    session.flush()
    candidate = CandidateContribution(extraction_run_id=run.id, ordinal=1)
    session.add(candidate)
    session.flush()
    session.add(
        CandidateClaim(
            candidate_contribution_id=candidate.id,
            ordinal=1,
            field="description",
            value=marker,
            confidence=0.5,
        )
    )
    session.flush()
    app = create_app()
    app.state.session_factory = lambda: session

    with TestClient(app) as client:
        for path in ("/api/v1/productions", f"/api/v1/productions/{production.id}"):
            response = client.get(path)
            assert response.status_code == 200
            assert marker not in response.text
