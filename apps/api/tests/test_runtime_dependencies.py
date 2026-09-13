import tomllib
from pathlib import Path


def test_httpx_is_declared_as_a_runtime_dependency() -> None:
    """The OAI connector is imported by the worker, so httpx cannot be dev-only."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    configuration = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    runtime = configuration["project"]["dependencies"]
    development = configuration["dependency-groups"]["dev"]

    assert any(dependency.startswith("httpx") for dependency in runtime)
    assert not any(dependency.startswith("httpx") for dependency in development)
