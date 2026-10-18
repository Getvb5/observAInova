from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.auth.contracts import AuthPrincipal, Role
from pci.claims.enums import ContributionField
from pci.claims.service import run_extraction
from pci.contributions.service import (
    materialize_validated_contribution,
    record_field_decision,
)
from pci.main import create_app
from pci.models.claims import CandidateContribution, CandidateGrounding
from pci.models.contributions import FieldDecisionAction
from pci.models.publication import PublicationAction, PublicationOutbox
from pci.publication.service import decide_publication, process_publication_event
from pci.review.sampling import SamplingConfig, create_stratified_sample
from pci.review.service import claim_next_assignment, complete_assignment
from tests.claims.test_extraction import deterministic_provider, ready_text


def test_extraction_human_validation_publication_and_revocation_are_one_vertical_slice(
    session: Session,
) -> None:
    text = ready_text(session)
    extraction = run_extraction(session, text.id, deterministic_provider(text))
    candidate = session.scalar(
        select(CandidateContribution).where(
            CandidateContribution.extraction_run_id == extraction.id
        )
    )
    grounding = session.scalar(select(CandidateGrounding))
    assert candidate is not None and grounding is not None
    sampling_run = create_stratified_sample(
        session,
        [candidate.id],
        SamplingConfig(
            target_size=1,
            test_fraction=Decimal(1),
            double_code_fraction=Decimal(0),
            seed="vertical-slice-v1",
            rule_version="vertical-slice-v1",
        ),
    )
    curator = AuthPrincipal("test", "curator", None, frozenset({Role.CURATOR}))
    assignment = claim_next_assignment(session, curator)
    assert assignment is not None
    for field in ContributionField:
        if field is ContributionField.EVIDENCE_RESULTS:
            record_field_decision(
                session,
                assignment.id,
                field,
                FieldDecisionAction.ACCEPT,
                None,
                [grounding.id],
                None,
                curator,
            )
        else:
            record_field_decision(
                session,
                assignment.id,
                field,
                FieldDecisionAction.INSUFFICIENT,
                None,
                [],
                "Não há evidência textual suficiente para este campo.",
                curator,
            )
    complete_assignment(session, assignment.id, curator)
    review_case = sampling_run.cases[0]
    version = materialize_validated_contribution(session, review_case.id, curator)
    contribution_id = version.scientific_contribution_id

    app = create_app()
    app.state.session_factory = lambda: session
    with TestClient(app) as client:
        assert client.get(f"/api/v1/contributions/{contribution_id}").status_code == 404

        supervisor = AuthPrincipal("test", "supervisor", None, frozenset({Role.SUPERVISOR}))
        publication = decide_publication(
            session,
            version.id,
            PublicationAction.PUBLISH,
            None,
            supervisor,
        )
        publication_event = session.scalar(
            select(PublicationOutbox).where(
                PublicationOutbox.publication_decision_id == publication.id
            )
        )
        assert publication_event is not None
        process_publication_event(session, publication_event.id)

        public_response = client.get(f"/api/v1/contributions/{contribution_id}")
        assert public_response.status_code == 200
        body = public_response.json()
        assert body["scientific_values"]["evidence_results"] == "Redução do tempo de espera"
        assert body["approved_groundings"][0]["quote"] == "reduziu o tempo de espera"
        assert "raw_response" not in body

        revocation = decide_publication(
            session,
            version.id,
            PublicationAction.REVOKE,
            "A fonte requer reavaliação científica.",
            supervisor,
        )
        revocation_event = session.scalar(
            select(PublicationOutbox).where(
                PublicationOutbox.publication_decision_id == revocation.id
            )
        )
        assert revocation_event is not None
        process_publication_event(session, revocation_event.id)

        assert client.get(f"/api/v1/contributions/{contribution_id}").status_code == 404
