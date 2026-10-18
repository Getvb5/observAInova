import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pci.auth.oidc import LocalTokenVerifier
from pci.main import create_app
from pci.models.review import (
    ReviewAssignment,
    ReviewCase,
    ReviewCaseKind,
    ReviewLane,
    ReviewStatus,
    SampleSplit,
    SamplingRun,
)

SECRET = "local-secret-long-enough-for-tests"


def token(*roles: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": "observainova-local",
            "sub": "staff-person",
            "aud": "observainova-api",
            "exp": now + timedelta(minutes=5),
            "roles": list(roles),
        },
        SECRET,
        algorithm="HS256",
    )


def internal_client(session: Session) -> TestClient:
    app = create_app()
    app.state.session_factory = lambda: session
    app.state.token_verifier = LocalTokenVerifier(
        secret=SECRET, issuer="observainova-local", audience="observainova-api"
    )
    return TestClient(app)


def test_anonymous_user_cannot_read_review_queue(session: Session) -> None:
    response = internal_client(session).get("/api/v1/internal/review-queue")

    assert response.status_code == 401


def test_supervisor_cannot_claim_curator_assignment(session: Session) -> None:
    response = internal_client(session).post(
        "/api/v1/internal/review-queue/claim",
        headers={"Authorization": f"Bearer {token('supervisor')}"},
    )

    assert response.status_code == 403


def test_curator_can_read_a_bounded_empty_queue(session: Session) -> None:
    response = internal_client(session).get(
        "/api/v1/internal/review-queue?page=1&page_size=20",
        headers={"Authorization": f"Bearer {token('curator')}"},
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "page_size": 20, "total": 0}


def test_legacy_source_revalidation_assignment_never_enters_curator_queue(
    session: Session,
) -> None:
    run = SamplingRun(
        target_size=1,
        selected_size=1,
        test_fraction="0",
        double_code_fraction="0",
        seed="source-revalidation",
        rule_version="source-revalidation-v1",
    )
    session.add(run)
    session.flush()
    review_case = ReviewCase(
        sampling_run_id=run.id,
        kind=ReviewCaseKind.SOURCE_REVALIDATION,
        published_contribution_version_id=uuid.uuid4(),
        stratum={},
        split=SampleSplit.OPERATIONS,
        priority_reason="Fonte atualizada",
        selection_order=1,
    )
    session.add(review_case)
    session.flush()
    session.add(
        ReviewAssignment(
            review_case_id=review_case.id,
            lane=ReviewLane.SINGLE,
            status=ReviewStatus.PENDING,
        )
    )
    session.flush()

    response = internal_client(session).get(
        "/api/v1/internal/review-queue?page=1&page_size=20",
        headers={"Authorization": f"Bearer {token('curator')}"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
