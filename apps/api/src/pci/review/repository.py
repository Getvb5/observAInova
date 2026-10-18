import uuid
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.claims.enums import ContributionType
from pci.models.claims import CandidateContribution, ExtractionRun
from pci.models.documents import DocumentTextScope, DocumentTextVersion
from pci.models.enums import ProductionType
from pci.models.production import ProductionVersion
from pci.models.provenance import RawRecord, Source


@dataclass(frozen=True, slots=True)
class CandidateSamplingData:
    candidate_id: uuid.UUID
    institution: str
    knowledge_area: str
    publication_year: int | None
    production_type: ProductionType | None
    text_scope: DocumentTextScope
    contribution_type: ContributionType | None


def candidate_sampling_data(
    session: Session, candidate_ids: list[uuid.UUID]
) -> list[CandidateSamplingData]:
    rows = session.execute(
        select(
            CandidateContribution.id,
            Source.name,
            ProductionVersion.knowledge_areas,
            ProductionVersion.publication_year,
            ProductionVersion.type,
            DocumentTextVersion.scope,
            CandidateContribution.suggested_type,
        )
        .join(ExtractionRun, ExtractionRun.id == CandidateContribution.extraction_run_id)
        .join(
            DocumentTextVersion,
            DocumentTextVersion.id == ExtractionRun.document_text_version_id,
        )
        .join(
            ProductionVersion,
            ProductionVersion.id == DocumentTextVersion.production_version_id,
        )
        .join(RawRecord, RawRecord.id == ProductionVersion.raw_record_id)
        .join(Source, Source.id == RawRecord.source_id)
        .where(CandidateContribution.id.in_(candidate_ids))
    ).all()
    result: list[CandidateSamplingData] = []
    for candidate_id, institution, areas, year, production_type, scope, suggested_type in rows:
        area_values = cast(list[object] | None, areas)
        first_area = (
            next((item for item in area_values if isinstance(item, str) and item), None)
            if area_values
            else None
        )
        result.append(
            CandidateSamplingData(
                candidate_id=candidate_id,
                institution=institution,
                knowledge_area=first_area or "not_informed",
                publication_year=year,
                production_type=production_type,
                text_scope=scope,
                contribution_type=suggested_type,
            )
        )
    return result
