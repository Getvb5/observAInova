import uuid
from dataclasses import asdict, dataclass

from pci.models.review import SampleSplit


@dataclass(frozen=True, slots=True)
class FieldExtractionMetrics:
    predicted_positive: int
    reference_positive: int
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float | None
    recall: float | None
    f1: float | None
    unsupported_claim_rate: float | None
    correction_rate: float | None
    accepted_without_correction_rate: float | None
    accepted_grounding_rate: float | None


@dataclass(frozen=True, slots=True)
class ExtractionMetrics:
    sampling_run_id: uuid.UUID
    split: SampleSplit
    record_ids: set[uuid.UUID]
    by_field: dict[str, FieldExtractionMetrics]
    by_stratum: dict[str, dict[str, FieldExtractionMetrics]]

    def as_dict(self) -> dict[str, object]:
        return {
            "sampling_run_id": str(self.sampling_run_id),
            "split": self.split.value,
            "record_ids": sorted(str(item) for item in self.record_ids),
            "by_field": {key: asdict(value) for key, value in self.by_field.items()},
            "by_stratum": {
                stratum: {key: asdict(value) for key, value in fields.items()}
                for stratum, fields in self.by_stratum.items()
            },
        }


@dataclass(frozen=True, slots=True)
class FieldAgreementMetrics:
    compared: int
    agreed: int
    agreement: float | None


@dataclass(frozen=True, slots=True)
class AgreementMetrics:
    sampling_run_id: uuid.UUID
    by_field: dict[str, FieldAgreementMetrics]

    def as_dict(self) -> dict[str, object]:
        return {
            "sampling_run_id": str(self.sampling_run_id),
            "by_field": {key: asdict(value) for key, value in self.by_field.items()},
        }


@dataclass(frozen=True, slots=True)
class GovernanceMetrics:
    sampling_run_id: uuid.UUID
    mean_review_seconds: float | None
    return_rate: float | None
    mean_publication_seconds: float | None
    provenance_completeness: float | None
    actor_separation_rate: float | None
    revocation_visibility_rate: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "sampling_run_id": str(self.sampling_run_id),
            **{key: value for key, value in asdict(self).items() if key != "sampling_run_id"},
        }
