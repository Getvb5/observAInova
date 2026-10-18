import uuid

import pytest
from pydantic import ValidationError

from pci.claims.contracts import (
    CandidateClaimPayload,
    CandidateContributionPayload,
    DocumentPagePayload,
    ExtractionDocument,
    GroundingPayload,
    ProviderExtraction,
)
from pci.claims.enums import ContributionField, ContributionType
from pci.claims.service import InvalidGroundingError, validate_provider_extraction


def document() -> ExtractionDocument:
    text = "A solução reduz filas no serviço público."
    return ExtractionDocument(
        document_text_version_id=uuid.uuid4(),
        checksum="a" * 64,
        scope="full_text",
        normalized_text=text,
        pages=[
            DocumentPagePayload(
                page_number=1,
                start_offset=0,
                end_offset=len(text),
            )
        ],
    )


def provider_payload(source: ExtractionDocument) -> ProviderExtraction:
    quote = "reduz filas"
    start = source.normalized_text.index(quote)
    return ProviderExtraction(
        provider="deterministic",
        model="fixture-v1",
        schema_version="v1",
        instruction_version="v1",
        contributions=[
            CandidateContributionPayload(
                claims=[
                    CandidateClaimPayload(
                        field=ContributionField.DESCRIPTION,
                        value="Redução de filas",
                        confidence=0.91,
                        groundings=[
                            GroundingPayload(
                                document_text_version_id=source.document_text_version_id,
                                page_number=1,
                                section="resultados",
                                start_offset=start,
                                end_offset=start + len(quote),
                                quote=quote,
                            )
                        ],
                    ),
                    CandidateClaimPayload(
                        field=ContributionField.CONTRIBUTION_TYPE,
                        value=ContributionType.INTERVENTION.value,
                        confidence=0.85,
                        groundings=[
                            GroundingPayload(
                                document_text_version_id=source.document_text_version_id,
                                page_number=1,
                                section="resultados",
                                start_offset=start,
                                end_offset=start + len(quote),
                                quote=quote,
                            )
                        ],
                    ),
                ]
            )
        ],
        raw_response={"fixture": True},
    )


def test_every_claim_must_match_its_exact_grounding() -> None:
    source = document()
    payload = provider_payload(source)
    payload.contributions[0].claims[0].groundings[0].quote = "texto inventado"

    with pytest.raises(InvalidGroundingError):
        validate_provider_extraction(source, payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"confidence": 1.1},
        {"value": "  "},
        {"field": "campo_inventado"},
        {"field": ContributionField.CONTRIBUTION_TYPE, "value": "coisa"},
    ],
)
def test_claim_contract_rejects_invalid_values(changes: dict[str, object]) -> None:
    source = document()
    grounding = GroundingPayload(
        document_text_version_id=source.document_text_version_id,
        page_number=1,
        start_offset=0,
        end_offset=1,
        quote="A",
    )
    values: dict[str, object] = {
        "field": ContributionField.DESCRIPTION,
        "value": "Valor",
        "confidence": 0.5,
        "groundings": [grounding],
    }
    values.update(changes)

    with pytest.raises(ValidationError):
        CandidateClaimPayload.model_validate(values)


def test_provider_contract_forbids_unknown_fields() -> None:
    source = document()
    payload = provider_payload(source).model_dump()
    payload["debug"] = "private surprise"

    with pytest.raises(ValidationError):
        ProviderExtraction.model_validate(payload)
