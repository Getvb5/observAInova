import pytest

from pci.problems.dialogue import (
    FIELD_ORDER,
    FieldAnswer,
    IncompleteProblemError,
    ProblemDraft,
    build_context,
    build_summary,
    get_next_question,
    missing_fields,
    validate_answer,
)
from pci.problems.models import KnowledgeStatus, ProblemField


def complete_draft(**overrides: str) -> ProblemDraft:
    values = {
        ProblemField.TERRITORY: overrides.get("territory", "Caruaru"),
        ProblemField.AFFECTED_POPULATION_OR_SERVICE: overrides.get(
            "population", "adultos aguardando cardiologia"
        ),
        ProblemField.OBSERVED_CONSEQUENCES: overrides.get(
            "consequence", "espera superior a 90 dias"
        ),
        ProblemField.PERCEIVED_CAUSES: overrides.get(
            "cause", "oferta insuficiente, segundo a equipe"
        ),
        ProblemField.ATTEMPTED_ACTIONS: "remanejamento manual de vagas",
        ProblemField.AVAILABLE_RESOURCES: "equipe de regulação e dados de agenda",
        ProblemField.CONSTRAINTS: "sem aumento de equipe",
        ProblemField.DESIRED_OUTCOME: overrides.get(
            "desired", "reduzir a espera preservando equidade"
        ),
    }
    answers = {
        field: FieldAnswer(
            value=value,
            knowledge_status=(
                KnowledgeStatus.PERCEPTION
                if field is ProblemField.PERCEIVED_CAUSES
                else KnowledgeStatus.REPORTED_FACT
            ),
        )
        for field, value in values.items()
    }
    return ProblemDraft(description="Demora no atendimento", answers=answers)


def test_dialogue_asks_fields_in_fixed_order() -> None:
    draft = ProblemDraft(description="Demora no atendimento", answers={})

    question = get_next_question(draft)

    assert question is not None
    assert question.field is ProblemField.TERRITORY
    assert missing_fields(draft) == FIELD_ORDER


def test_unknown_is_complete_without_invented_value() -> None:
    answer = validate_answer(
        ProblemField.ATTEMPTED_ACTIONS,
        None,
        KnowledgeStatus.UNKNOWN,
    )
    draft = ProblemDraft(
        description="Demora no atendimento",
        answers={ProblemField.ATTEMPTED_ACTIONS: answer},
    )

    assert draft.answers[ProblemField.ATTEMPTED_ACTIONS].value is None
    assert ProblemField.ATTEMPTED_ACTIONS not in missing_fields(draft)


def test_perceived_cause_cannot_be_classified_as_fact() -> None:
    with pytest.raises(ValueError, match="perception or unknown"):
        validate_answer(
            ProblemField.PERCEIVED_CAUSES,
            "Falta de profissionais",
            KnowledgeStatus.REPORTED_FACT,
        )


@pytest.mark.parametrize("value", ["", "   ", "x" * 5001])
def test_reported_answer_rejects_blank_or_oversized_text(value: str) -> None:
    with pytest.raises(ValueError, match="between 1 and 5000"):
        validate_answer(
            ProblemField.TERRITORY,
            value,
            KnowledgeStatus.REPORTED_FACT,
        )


def test_unknown_rejects_invented_value() -> None:
    with pytest.raises(ValueError, match="must not include a value"):
        validate_answer(
            ProblemField.TERRITORY,
            "território provável",
            KnowledgeStatus.UNKNOWN,
        )


def test_summary_uses_exact_supplied_phrases() -> None:
    draft = complete_draft(
        territory="Caruaru",
        population="adultos aguardando cardiologia",
        consequence="espera superior a 90 dias",
        cause="oferta insuficiente, segundo a equipe",
        desired="reduzir a espera preservando equidade",
    )

    summary = build_summary(draft)

    for phrase in [
        "Caruaru",
        "adultos aguardando cardiologia",
        "espera superior a 90 dias",
        "oferta insuficiente, segundo a equipe",
        "reduzir a espera preservando equidade",
    ]:
        assert phrase in summary
    assert "Causas percebidas" in summary


def test_context_keeps_unknown_as_null() -> None:
    draft = complete_draft()
    answers = dict(draft.answers)
    answers[ProblemField.ATTEMPTED_ACTIONS] = FieldAnswer(
        value=None,
        knowledge_status=KnowledgeStatus.UNKNOWN,
    )

    context = build_context(ProblemDraft(description=draft.description, answers=answers))

    assert context["attempted_actions"] == {
        "value": None,
        "knowledge_status": "unknown",
    }


def test_incomplete_summary_reports_ordered_missing_fields() -> None:
    draft = ProblemDraft(description="Demora no atendimento", answers={})

    with pytest.raises(IncompleteProblemError) as error:
        build_summary(draft)

    assert error.value.missing_fields == FIELD_ORDER
