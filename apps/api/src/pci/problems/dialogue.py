from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pci.problems.models import (
    KnowledgeStatus,
    ProblemAnswerEvent,
    ProblemField,
)

FIELD_ORDER = (
    ProblemField.TERRITORY,
    ProblemField.AFFECTED_POPULATION_OR_SERVICE,
    ProblemField.OBSERVED_CONSEQUENCES,
    ProblemField.PERCEIVED_CAUSES,
    ProblemField.ATTEMPTED_ACTIONS,
    ProblemField.AVAILABLE_RESOURCES,
    ProblemField.CONSTRAINTS,
    ProblemField.DESIRED_OUTCOME,
)

PROMPTS = {
    ProblemField.TERRITORY: "Em qual território ou unidade administrativa isso acontece?",
    ProblemField.AFFECTED_POPULATION_OR_SERVICE: (
        "Qual população, serviço ou organização é mais afetado?"
    ),
    ProblemField.OBSERVED_CONSEQUENCES: "Quais consequências você observa?",
    ProblemField.PERCEIVED_CAUSES: (
        "Quais causas são percebidas? Elas serão registradas como percepções, "
        "não como fatos comprovados."
    ),
    ProblemField.ATTEMPTED_ACTIONS: "O que já foi tentado e qual foi o resultado?",
    ProblemField.AVAILABLE_RESOURCES: "Quais recursos ou capacidades já estão disponíveis?",
    ProblemField.CONSTRAINTS: "Quais restrições precisam ser respeitadas?",
    ProblemField.DESIRED_OUTCOME: "Que resultado concreto você deseja alcançar?",
}

SUMMARY_LABELS = {
    ProblemField.TERRITORY: "Território",
    ProblemField.AFFECTED_POPULATION_OR_SERVICE: "População ou serviço afetado",
    ProblemField.OBSERVED_CONSEQUENCES: "Consequências observadas",
    ProblemField.PERCEIVED_CAUSES: "Causas percebidas",
    ProblemField.ATTEMPTED_ACTIONS: "Ações já tentadas",
    ProblemField.AVAILABLE_RESOURCES: "Recursos disponíveis",
    ProblemField.CONSTRAINTS: "Restrições",
    ProblemField.DESIRED_OUTCOME: "Resultado desejado",
}


@dataclass(frozen=True)
class FieldAnswer:
    value: str | None
    knowledge_status: KnowledgeStatus


@dataclass(frozen=True)
class ProblemDraft:
    description: str
    answers: Mapping[ProblemField, FieldAnswer]


@dataclass(frozen=True)
class NextQuestion:
    field: ProblemField
    prompt: str
    accepts_unknown: bool = True


class IncompleteProblemError(ValueError):
    def __init__(self, fields: tuple[ProblemField, ...]) -> None:
        self.missing_fields = fields
        super().__init__(
            "Problem is incomplete: " + ", ".join(field.value for field in fields)
        )


def build_draft(
    description: str, events: Iterable[ProblemAnswerEvent]
) -> ProblemDraft:
    answers: dict[ProblemField, FieldAnswer] = {}
    for event in events:
        answers[event.field] = FieldAnswer(
            value=event.value,
            knowledge_status=event.knowledge_status,
        )
    return ProblemDraft(description=description, answers=answers)


def missing_fields(draft: ProblemDraft) -> tuple[ProblemField, ...]:
    return tuple(field for field in FIELD_ORDER if field not in draft.answers)


def get_next_question(draft: ProblemDraft) -> NextQuestion | None:
    missing = missing_fields(draft)
    if not missing:
        return None
    field = missing[0]
    return NextQuestion(field=field, prompt=PROMPTS[field])


def validate_answer(
    field: ProblemField,
    value: str | None,
    knowledge_status: KnowledgeStatus,
) -> FieldAnswer:
    if field is ProblemField.PERCEIVED_CAUSES and knowledge_status not in {
        KnowledgeStatus.PERCEPTION,
        KnowledgeStatus.UNKNOWN,
    }:
        raise ValueError("perceived causes must be perception or unknown")

    if knowledge_status is KnowledgeStatus.UNKNOWN:
        if value is not None:
            raise ValueError("unknown answer must not include a value")
        return FieldAnswer(value=None, knowledge_status=knowledge_status)

    if value is None:
        raise ValueError("reported answer must contain between 1 and 5000 characters")
    normalized = value.strip()
    if not 1 <= len(normalized) <= 5000:
        raise ValueError("reported answer must contain between 1 and 5000 characters")
    return FieldAnswer(value=normalized, knowledge_status=knowledge_status)


def build_context(draft: ProblemDraft) -> dict[str, object]:
    missing = missing_fields(draft)
    if missing:
        raise IncompleteProblemError(missing)

    context: dict[str, object] = {"description": draft.description}
    for field in FIELD_ORDER:
        answer = draft.answers[field]
        context[field.value] = {
            "value": answer.value,
            "knowledge_status": answer.knowledge_status.value,
        }
    return context


def build_summary(draft: ProblemDraft) -> str:
    missing = missing_fields(draft)
    if missing:
        raise IncompleteProblemError(missing)

    lines = [f"Problema descrito: {draft.description}"]
    for field in FIELD_ORDER:
        answer = draft.answers[field]
        displayed_value = answer.value if answer.value is not None else "não informado"
        lines.append(f"{SUMMARY_LABELS[field]}: {displayed_value}")
    return "\n".join(lines)
