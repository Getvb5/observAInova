from typing import Literal, cast

from pci.documents.contracts import CorpusEligibilityResult
from pci.models.production import ProductionVersion
from pci.models.provenance import Source


def evaluate_corpus_eligibility(
    production_version: ProductionVersion, source: Source
) -> CorpusEligibilityResult:
    schedule = source.schedule
    configuration = _scope_configuration(schedule)
    if configuration is None:
        return CorpusEligibilityResult(False, None, ("scope_configuration_invalid",))
    sector, state, corpus_types, analysis_start, analysis_end, current_year = configuration
    reasons: list[str] = []
    if sector.casefold() != "public":
        reasons.append("institution_not_public")
    if state.upper() != "PE":
        reasons.append("institution_not_in_pe")
    production_type = production_version.type
    if production_type is None or production_type.value not in corpus_types:
        reasons.append("production_type_not_in_corpus")
    year = production_version.publication_year
    layer: Literal["analysis", "current"] | None = None
    if year is not None and analysis_start <= year <= analysis_end:
        layer = "analysis"
    elif year == current_year:
        layer = "current"
    else:
        reasons.append("publication_year_outside_corpus")
    return CorpusEligibilityResult(not reasons, layer if not reasons else None, tuple(reasons))


def _scope_configuration(
    schedule: dict[str, object] | None,
) -> tuple[str, str, frozenset[str], int, int, int] | None:
    if not isinstance(schedule, dict):
        return None
    sector = schedule.get("institution_sector")
    state = schedule.get("institution_state")
    raw_types = schedule.get("corpus_types")
    analysis_start = schedule.get("analysis_year_start")
    analysis_end = schedule.get("analysis_year_end")
    current_year = schedule.get("current_year")
    if not isinstance(sector, str) or not isinstance(state, str):
        return None
    if not isinstance(raw_types, list) or not all(isinstance(item, str) for item in raw_types):
        return None
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (
            analysis_start,
            analysis_end,
            current_year,
        )
    ):
        return None
    start = cast(int, analysis_start)
    end = cast(int, analysis_end)
    current = cast(int, current_year)
    if start > end or current <= end:
        return None
    corpus_types = frozenset(cast(list[str], raw_types))
    if not corpus_types:
        return None
    return sector, state, corpus_types, start, end, current
