import argparse
import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.db import session_scope
from pci.models.enums import RightsPolicy
from pci.models.provenance import Source

UFPE_SOURCE_CODE = "ufpe-theses-dissertations"


@dataclass(frozen=True, slots=True)
class UfpeSourceConfig:
    base_url: str = "https://repositorio.ufpe.br/oai/request"
    set_spec: str | None = None
    analysis_year_start: int = 2016
    analysis_year_end: int = 2025
    current_year: int = 2026


def ensure_ufpe_source(session: Session, config: UfpeSourceConfig) -> Source:
    source = session.scalar(select(Source).where(Source.code == UFPE_SOURCE_CODE))
    if source is None:
        source = Source(
            code=UFPE_SOURCE_CODE,
            name="UFPE — Teses e Dissertações",
            connector_type="oai_pmh",
            rights_policy=RightsPolicy.METADATA_ONLY,
        )
        session.add(source)
    source.base_url = config.base_url
    source.active = True
    source.schedule = {
        "metadata_prefix": "oai_dc",
        "set_spec": config.set_spec,
        "institution_sector": "public",
        "institution_state": "PE",
        "corpus_types": ["thesis", "dissertation"],
        "analysis_year_start": config.analysis_year_start,
        "analysis_year_end": config.analysis_year_end,
        "current_year": config.current_year,
        "timeout": 30.0,
        "max_retries": 5,
        "request_interval_seconds": 2.0,
        "retry_base_delay_seconds": 15.0,
    }
    session.flush()
    return source


def config_from_environment() -> UfpeSourceConfig:
    return UfpeSourceConfig(
        base_url=os.getenv(
            "UFPE_OAI_BASE_URL", "https://repositorio.ufpe.br/oai/request"
        ),
        set_spec=os.getenv("UFPE_OAI_SET_SPEC") or None,
        analysis_year_start=int(os.getenv("CORPUS_ANALYSIS_YEAR_START", "2016")),
        analysis_year_end=int(os.getenv("CORPUS_ANALYSIS_YEAR_END", "2025")),
        current_year=int(os.getenv("CORPUS_CURRENT_YEAR", "2026")),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure the UFPE pilot source.")
    parser.add_argument("--enqueue-harvest", action="store_true")
    arguments = parser.parse_args()
    with session_scope() as session:
        source = ensure_ufpe_source(session, config_from_environment())
        source_id = str(source.id)
    if arguments.enqueue_harvest:
        from pci.worker import harvest_source_task

        harvest_source_task.send(source_id)


if __name__ == "__main__":
    main()
