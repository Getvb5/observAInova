from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from pci.auth.contracts import AuthPrincipal, Role
from pci.main import create_app
from pci.models.review import SamplingRun


class StaticVerifier:
    def __init__(self, roles: frozenset[Role]) -> None:
        self.roles = roles

    def verify(self, token: str) -> AuthPrincipal:
        return AuthPrincipal("test", token, None, self.roles)


def test_evaluation_export_is_admin_only_and_supports_json_csv(session: Session) -> None:
    run = SamplingRun(
        target_size=1,
        selected_size=0,
        test_fraction="1",
        double_code_fraction="0",
        seed="export",
        rule_version="v1",
    )
    session.add(run)
    session.flush()
    app = create_app()
    app.state.session_factory = lambda: session
    app.state.token_verifier = StaticVerifier(frozenset({Role.CURATOR}))
    with TestClient(app) as client:
        assert (
            client.get(
                f"/api/v1/internal/evaluation/sampling-runs/{run.id}.json",
                headers={"Authorization": "Bearer curator"},
            ).status_code
            == 403
        )
    app.state.token_verifier = StaticVerifier(frozenset({Role.ADMIN}))
    with TestClient(app) as client:
        json_response = client.get(
            f"/api/v1/internal/evaluation/sampling-runs/{run.id}.json",
            headers={"Authorization": "Bearer admin"},
        )
        csv_response = client.get(
            f"/api/v1/internal/evaluation/sampling-runs/{run.id}.csv",
            headers={"Authorization": "Bearer admin"},
        )
    assert json_response.status_code == 200
    assert json_response.json()["sampling_run_id"] == str(run.id)
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
