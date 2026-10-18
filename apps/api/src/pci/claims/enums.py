from enum import StrEnum


class ContributionField(StrEnum):
    PROBLEM_OR_PHENOMENON = "problem_or_phenomenon"
    CONTRIBUTION_TYPE = "contribution_type"
    DESCRIPTION = "description"
    MECHANISM = "mechanism"
    POPULATION = "population"
    SERVICE = "service"
    TERRITORY = "territory"
    METHODOLOGY = "methodology"
    EVIDENCE_RESULTS = "evidence_results"
    BARRIERS_LIMITATIONS = "barriers_limitations"
    APPLICABILITY = "applicability"
    REQUIRED_RESOURCES = "required_resources"
    MATURITY = "maturity"
    RISKS_CONTRAINDICATIONS = "risks_contraindications"


class ContributionType(StrEnum):
    DIAGNOSIS = "diagnosis"
    CAUSAL_EXPLANATION = "causal_explanation"
    METHOD = "method"
    INTERVENTION = "intervention"
    TECHNOLOGY = "technology"
    MODEL = "model"
    PROTOCOL = "protocol"
    RECOMMENDATION = "recommendation"
    EVALUATION = "evaluation"
    INSTRUMENT = "instrument"


class ExtractionRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class CandidateStatus(StrEnum):
    GENERATED = "generated"
    IN_REVIEW = "in_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
