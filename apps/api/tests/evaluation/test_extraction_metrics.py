from sqlalchemy.orm import Session

from pci.evaluation.service import compute_extraction_metrics, safe_csv_cell
from pci.models.review import SampleSplit, SamplingRun


def test_empty_test_split_has_null_rates_and_no_calibration_records(session: Session) -> None:
    run = SamplingRun(
        target_size=2,
        selected_size=0,
        test_fraction="0.5",
        double_code_fraction="0",
        seed="evaluation",
        rule_version="v1",
    )
    session.add(run)
    session.flush()

    metrics = compute_extraction_metrics(session, run.id, SampleSplit.TEST)

    assert metrics.split is SampleSplit.TEST
    assert metrics.record_ids == set()
    assert all(item.precision is None and item.recall is None for item in metrics.by_field.values())


def test_csv_formula_injection_is_neutralized() -> None:
    assert safe_csv_cell("=IMPORTDATA('x')") == "'=IMPORTDATA('x')"
    assert safe_csv_cell("+1") == "'+1"
    assert safe_csv_cell("UFPE") == "UFPE"
