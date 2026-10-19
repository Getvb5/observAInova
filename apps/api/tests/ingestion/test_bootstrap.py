from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.bootstrap import UfpeSourceConfig, ensure_ufpe_source
from pci.models.enums import RightsPolicy
from pci.models.provenance import Source


def test_ufpe_source_bootstrap_is_idempotent_and_preserves_the_approved_corpus(
    session: Session,
) -> None:
    config = UfpeSourceConfig(
        base_url="https://repositorio.ufpe.br/oai/request",
        set_spec="com_123456789_50",
    )

    first = ensure_ufpe_source(session, config)
    second = ensure_ufpe_source(session, config)
    session.flush()

    assert first.id == second.id
    assert len(session.scalars(select(Source)).all()) == 1
    assert first.rights_policy is RightsPolicy.METADATA_ONLY
    assert first.schedule == {
        "metadata_prefix": "oai_dc",
        "set_spec": "com_123456789_50",
        "institution_sector": "public",
        "institution_state": "PE",
        "corpus_types": ["thesis", "dissertation"],
        "analysis_year_start": 2016,
        "analysis_year_end": 2025,
        "current_year": 2026,
        "timeout": 30.0,
        "max_retries": 2,
    }
