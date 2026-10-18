import csv
import io
import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pci.api_dependencies import SessionDependency
from pci.auth.contracts import AuthPrincipal, Role
from pci.auth.dependencies import require_roles
from pci.claims.enums import ContributionField
from pci.contributions.schemas import InternalContributionSummary
from pci.contributions.service import (
    IncompleteReviewError,
    MissingGroundingError,
    materialize_validated_contribution,
    merge_review_cases,
    record_field_decision,
    split_review_case,
)
from pci.evaluation.service import (
    compute_extraction_metrics,
    compute_governance_metrics,
    compute_inter_rater_agreement,
    safe_csv_cell,
)
from pci.models.claims import (
    CandidateClaim,
    CandidateContribution,
    CandidateGrounding,
    ExtractionRun,
)
from pci.models.contributions import (
    ContributionCandidateSource,
    ContributionGrounding,
    ContributionVersion,
    ContributionVersionStatus,
    ReviewFieldDecision,
)
from pci.models.documents import DocumentTextVersion, SourceDocument
from pci.models.production import ProductionVersion
from pci.models.provenance import Source
from pci.models.publication import PublishedContribution
from pci.models.review import (
    ReviewAssignment,
    ReviewCase,
    ReviewCaseKind,
    ReviewLane,
    ReviewStatus,
    SampleSplit,
    SamplingRun,
)
from pci.publication.schemas import PublicationDecisionRequest
from pci.publication.service import SeparationOfDutiesError, decide_publication
from pci.review.sampling import SamplingConfig, create_stratified_sample
from pci.review.schemas import (
    FieldDecisionRequest,
    MergeCasesRequest,
    SamplingRunRequest,
    SourceProcessingPolicyRequest,
    SplitCaseRequest,
)
from pci.review.service import claim_next_assignment, complete_assignment

router = APIRouter(prefix="/internal", tags=["internal-scientific-governance"])
Curator = Annotated[AuthPrincipal, Depends(require_roles(Role.CURATOR))]
Supervisor = Annotated[AuthPrincipal, Depends(require_roles(Role.SUPERVISOR))]
Admin = Annotated[AuthPrincipal, Depends(require_roles(Role.ADMIN))]
Staff = Annotated[
    AuthPrincipal,
    Depends(require_roles(Role.CURATOR, Role.SUPERVISOR, Role.ADMIN)),
]
Page = Annotated[int, Query(ge=1, le=1_000_000)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/dashboard")
def dashboard(session: SessionDependency, _: Staff) -> dict[str, object]:
    return {
        "documents": _enum_counts(session, SourceDocument.status),
        "extractions": _enum_counts(session, ExtractionRun.status),
        "review_pending": session.scalar(
            select(func.count())
            .select_from(ReviewAssignment)
            .join(ReviewCase, ReviewCase.id == ReviewAssignment.review_case_id)
            .where(
                ReviewAssignment.status == ReviewStatus.PENDING,
                ReviewCase.kind.in_((ReviewCaseKind.CANDIDATE, ReviewCaseKind.RETURN_CORRECTION)),
            )
        )
        or 0,
        "publication_pending": session.scalar(
            select(func.count())
            .select_from(ContributionVersion)
            .where(ContributionVersion.status == ContributionVersionStatus.PUBLICATION_PENDING)
        )
        or 0,
    }


@router.get("/review-queue")
def review_queue(
    session: SessionDependency, _: Curator, page: Page = 1, page_size: PageSize = 20
) -> dict[str, object]:
    query = (
        select(ReviewAssignment)
        .join(ReviewCase, ReviewCase.id == ReviewAssignment.review_case_id)
        .where(
            ReviewAssignment.status == ReviewStatus.PENDING,
            ReviewCase.kind.in_((ReviewCaseKind.CANDIDATE, ReviewCaseKind.RETURN_CORRECTION)),
        )
    )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = session.scalars(
        query.order_by(ReviewAssignment.created_at, ReviewAssignment.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_assignment_summary(item) for item in items],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/review-queue/claim")
def claim_assignment(session: SessionDependency, principal: Curator) -> dict[str, object]:
    assignment = claim_next_assignment(session, principal)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No assignment available")
    return _assignment_summary(assignment)


@router.get("/review-cases/{case_id}")
def review_case_detail(
    case_id: uuid.UUID, session: SessionDependency, _: Curator
) -> dict[str, object]:
    review_case = session.get(ReviewCase, case_id)
    if review_case is None:
        raise HTTPException(status_code=404, detail="Review case not found")
    return _review_case_detail(session, review_case)


@router.get("/review-assignments/{assignment_id}")
def review_assignment_detail(
    assignment_id: uuid.UUID, session: SessionDependency, principal: Curator
) -> dict[str, object]:
    assignment = session.get(ReviewAssignment, assignment_id)
    if assignment is None or assignment.actor_key != principal.actor_key:
        raise HTTPException(status_code=404, detail="Assignment not found")
    review_case = session.get(ReviewCase, assignment.review_case_id)
    if review_case is None:
        raise HTTPException(status_code=404, detail="Review case not found")
    payload: dict[str, object] = {
        "assignment": _assignment_summary(assignment),
        "review_case": _review_case_detail(session, review_case),
    }
    if assignment.lane is ReviewLane.ADJUDICATION:
        payload["adjudication_context"] = _adjudication_context(session, review_case.id)
    return payload


@router.post("/review-assignments/{assignment_id}/field-decisions")
def field_decision(
    assignment_id: uuid.UUID,
    request: FieldDecisionRequest,
    session: SessionDependency,
    principal: Curator,
) -> dict[str, object]:
    try:
        decision = record_field_decision(
            session,
            assignment_id,
            request.field,
            request.action,
            request.value,
            request.grounding_ids,
            request.reason,
            principal,
        )
    except MissingGroundingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Assignment not found") from exc
    return {"id": decision.id, "sequence": decision.sequence}


@router.post("/review-assignments/{assignment_id}/complete")
def finish_assignment(
    assignment_id: uuid.UUID, session: SessionDependency, principal: Curator
) -> dict[str, object]:
    try:
        assignment = complete_assignment(session, assignment_id, principal)
    except IncompleteReviewError as exc:
        raise HTTPException(
            status_code=422,
            detail={"missing_fields": [field.value for field in exc.missing_fields]},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Assignment is stale or inaccessible") from exc
    return _assignment_summary(assignment)


@router.post("/review-cases/{case_id}/split")
def split_case(
    case_id: uuid.UUID,
    request: SplitCaseRequest,
    session: SessionDependency,
    principal: Curator,
) -> dict[str, object]:
    cases = split_review_case(session, case_id, request.partitions, principal)
    return {"case_ids": [item.id for item in cases]}


@router.post("/review-cases/{case_id}/merge")
def merge_cases(
    case_id: uuid.UUID,
    request: MergeCasesRequest,
    session: SessionDependency,
    principal: Curator,
) -> dict[str, object]:
    merged = merge_review_cases(
        session, list(dict.fromkeys([case_id, *request.review_case_ids])), principal
    )
    return {"case_id": merged.id}


@router.post("/review-cases/{case_id}/materialize")
def materialize_case(
    case_id: uuid.UUID, session: SessionDependency, principal: Curator
) -> InternalContributionSummary:
    version = materialize_validated_contribution(session, case_id, principal)
    return InternalContributionSummary.model_validate(version, from_attributes=True)


@router.get("/publication-queue")
def publication_queue(
    session: SessionDependency, _: Supervisor, page: Page = 1, page_size: PageSize = 20
) -> dict[str, object]:
    query = (
        select(ContributionVersion)
        .outerjoin(
            PublishedContribution,
            PublishedContribution.contribution_version_id == ContributionVersion.id,
        )
        .where(
            or_(
                ContributionVersion.status.in_(
                    (
                        ContributionVersionStatus.VALIDATED,
                        ContributionVersionStatus.PUBLICATION_PENDING,
                    )
                ),
                (
                    (ContributionVersion.status == ContributionVersionStatus.PUBLISHED)
                    & PublishedContribution.active.is_(True)
                    & PublishedContribution.source_warning.is_not(None)
                ),
            )
        )
    )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = session.scalars(
        query.order_by(ContributionVersion.created_at, ContributionVersion.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            InternalContributionSummary.model_validate(item, from_attributes=True).model_dump()
            for item in items
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/contribution-versions/{version_id}")
def contribution_version_detail(
    version_id: uuid.UUID, session: SessionDependency, principal: Supervisor
) -> dict[str, object]:
    version = session.get(ContributionVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Contribution version not found")
    values = {
        field.value: getattr(version, field.value).value
        if hasattr(getattr(version, field.value), "value")
        else getattr(version, field.value)
        for field in ContributionField
        if getattr(version, field.value) is not None
    }
    groundings = session.scalars(
        select(ContributionGrounding).where(
            ContributionGrounding.contribution_version_id == version.id
        )
    ).all()
    actors = session.scalars(
        select(ContributionCandidateSource.curator_actor_key)
        .where(ContributionCandidateSource.contribution_version_id == version.id)
        .distinct()
    ).all()
    projection = session.scalar(
        select(PublishedContribution).where(
            PublishedContribution.contribution_version_id == version.id,
            PublishedContribution.active.is_(True),
        )
    )
    return {
        "id": version.id,
        "version": version.version,
        "validated_by": sorted(actors),
        "current_actor": principal.actor_key,
        "scientific_values": values,
        "approved_groundings": [
            {
                "field": item.field.value,
                "text": item.quote,
                "page": item.page_number,
                "source_scope": item.source_scope,
            }
            for item in groundings
        ],
        "status": version.status.value,
        "source_warning": projection.source_warning if projection is not None else None,
    }


@router.post("/contribution-versions/{version_id}/publication-decisions")
def publication_decision(
    version_id: uuid.UUID,
    request: PublicationDecisionRequest,
    session: SessionDependency,
    principal: Supervisor,
) -> dict[str, object]:
    try:
        decision = decide_publication(
            session, version_id, request.action, request.reason, principal
        )
    except SeparationOfDutiesError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": decision.id, "action": decision.action}


@router.put("/sources/{source_id}/processing-policy")
def update_source_policy(
    source_id: uuid.UUID,
    request: SourceProcessingPolicyRequest,
    session: SessionDependency,
    _: Admin,
) -> dict[str, object]:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.schedule = request.model_dump()
    session.flush()
    return {"source_id": source.id, "processing_policy": source.schedule}


@router.post("/sampling-runs")
def create_sample(
    request: SamplingRunRequest, session: SessionDependency, _: Admin
) -> dict[str, object]:
    try:
        config = SamplingConfig(
            request.target_size,
            Decimal(request.test_fraction),
            Decimal(request.double_code_fraction),
            request.seed,
            request.rule_version,
        )
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Invalid sampling configuration") from exc
    run = create_stratified_sample(session, request.candidate_ids, config)
    return {"id": run.id, "selected_size": run.selected_size}


def _evaluation_payload(session: Session, run_id: uuid.UUID) -> dict[str, object]:
    if session.get(SamplingRun, run_id) is None:
        raise HTTPException(status_code=404, detail="Sampling run not found")
    return {
        "sampling_run_id": str(run_id),
        "calibration": compute_extraction_metrics(
            session, run_id, SampleSplit.CALIBRATION
        ).as_dict(),
        "test": compute_extraction_metrics(session, run_id, SampleSplit.TEST).as_dict(),
        "agreement": compute_inter_rater_agreement(session, run_id).as_dict(),
        "governance": compute_governance_metrics(session, run_id).as_dict(),
    }


@router.get("/evaluation/sampling-runs/{run_id}.json")
def evaluation_json(run_id: uuid.UUID, session: SessionDependency, _: Admin) -> dict[str, object]:
    return _evaluation_payload(session, run_id)


@router.get("/evaluation/sampling-runs/{run_id}.csv")
def evaluation_csv(run_id: uuid.UUID, session: SessionDependency, _: Admin) -> Response:
    payload = _evaluation_payload(session, run_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["section", "field", "metric", "value"])
    for split in ("calibration", "test"):
        section = cast(dict[str, object], payload[split])
        fields = cast(dict[str, dict[str, object]], section["by_field"])
        for field, metrics in fields.items():
            for metric, value in metrics.items():
                writer.writerow(
                    [
                        safe_csv_cell(split),
                        safe_csv_cell(field),
                        safe_csv_cell(metric),
                        safe_csv_cell(value),
                    ]
                )
    governance = cast(dict[str, object], payload["governance"])
    for metric, value in governance.items():
        if metric != "sampling_run_id":
            writer.writerow(["governance", "", safe_csv_cell(metric), safe_csv_cell(value)])
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="evaluation-{run_id}.csv"'},
    )


def _assignment_summary(assignment: ReviewAssignment) -> dict[str, object]:
    return {
        "id": assignment.id,
        "review_case_id": assignment.review_case_id,
        "lane": assignment.lane,
        "status": assignment.status,
        "actor_key": assignment.actor_key,
    }


def _review_case_detail(session: Session, review_case: ReviewCase) -> dict[str, object]:
    candidate_ids = [uuid.UUID(item) for item in review_case.candidate_ids or []]
    if not candidate_ids and review_case.candidate_contribution_id is not None:
        candidate_ids = [review_case.candidate_contribution_id]
    claims = session.scalars(
        select(CandidateClaim)
        .where(CandidateClaim.candidate_contribution_id.in_(candidate_ids))
        .order_by(CandidateClaim.field, CandidateClaim.ordinal)
    ).all()
    claim_ids = [item.id for item in claims]
    groundings = (
        session.scalars(
            select(CandidateGrounding)
            .where(CandidateGrounding.candidate_claim_id.in_(claim_ids))
            .order_by(CandidateGrounding.page_number, CandidateGrounding.start_offset)
        ).all()
        if claim_ids
        else []
    )
    claim_by_field = {item.field: item for item in claims}
    grounding_ids_by_claim: dict[uuid.UUID, list[str]] = {}
    for grounding in groundings:
        grounding_ids_by_claim.setdefault(grounding.candidate_claim_id, []).append(
            str(grounding.id)
        )
    text_versions = session.scalars(
        select(DocumentTextVersion)
        .join(ExtractionRun, ExtractionRun.document_text_version_id == DocumentTextVersion.id)
        .join(CandidateContribution, CandidateContribution.extraction_run_id == ExtractionRun.id)
        .where(CandidateContribution.id.in_(candidate_ids))
        .order_by(DocumentTextVersion.created_at, DocumentTextVersion.id)
    ).all()
    text_version = text_versions[0] if text_versions else None
    production_version = (
        session.get(ProductionVersion, text_version.production_version_id)
        if text_version is not None
        else None
    )
    correction_version = (
        session.scalar(
            select(ContributionVersion).where(ContributionVersion.review_case_id == review_case.id)
        )
        if review_case.kind is ReviewCaseKind.RETURN_CORRECTION
        else None
    )

    def field_value(field: ContributionField) -> str:
        if correction_version is not None:
            value = getattr(correction_version, field.value)
            if value is not None:
                return value.value if hasattr(value, "value") else str(value)
        return claim_by_field[field].value if field in claim_by_field else ""

    return {
        "id": review_case.id,
        "kind": review_case.kind.value,
        "correction_reason": (
            review_case.priority_reason
            if review_case.kind is ReviewCaseKind.RETURN_CORRECTION
            else None
        ),
        "correction_base_version_id": review_case.correction_base_version_id,
        "draft_version": correction_version.version if correction_version is not None else None,
        "source_title": production_version.title if production_version else "Produção sem título",
        "source_kind": text_version.scope.value if text_version else "abstract_only",
        "source_text": "\n\n".join(item.normalized_text for item in text_versions),
        "fields": [
            {
                "name": field.value,
                "label": field.value.replace("_", " ").capitalize(),
                "value": field_value(field),
                "confidence": (
                    0
                    if review_case.kind is ReviewCaseKind.RETURN_CORRECTION
                    else claim_by_field[field].confidence
                    if field in claim_by_field
                    else 0
                ),
                "grounding_ids": grounding_ids_by_claim.get(claim_by_field[field].id, [])
                if field in claim_by_field
                else [],
            }
            for field in ContributionField
        ],
        "groundings": [
            {
                "id": grounding.id,
                "text": grounding.quote,
                "page": grounding.page_number,
                "claim_id": grounding.candidate_claim_id,
            }
            for grounding in groundings
        ],
    }


def _adjudication_context(session: Session, review_case_id: uuid.UUID) -> dict[str, object]:
    independent = session.scalars(
        select(ReviewAssignment)
        .where(
            ReviewAssignment.review_case_id == review_case_id,
            ReviewAssignment.lane.in_((ReviewLane.PRIMARY, ReviewLane.SECONDARY)),
            ReviewAssignment.status == ReviewStatus.COMPLETED,
        )
        .order_by(ReviewAssignment.lane)
    ).all()
    if len(independent) != 2:
        raise HTTPException(
            status_code=409,
            detail="Adjudication requires two completed independent reviews",
        )
    reviews: list[dict[str, object]] = []
    field_signatures: dict[ContributionField, list[tuple[object, ...]]] = {
        field: [] for field in ContributionField
    }
    for index, assignment in enumerate(independent, start=1):
        rows = session.scalars(
            select(ReviewFieldDecision)
            .where(ReviewFieldDecision.review_assignment_id == assignment.id)
            .order_by(ReviewFieldDecision.field, ReviewFieldDecision.sequence.desc())
        ).all()
        latest: dict[ContributionField, ReviewFieldDecision] = {}
        for row in rows:
            latest.setdefault(row.field, row)
        fields = []
        for field in ContributionField:
            decision = latest.get(field)
            if decision is None:
                continue
            grounding_ids = decision.grounding_ids or []
            signature = (
                decision.action.value,
                decision.value,
                decision.reason,
                tuple(sorted(grounding_ids)),
            )
            field_signatures[field].append(signature)
            fields.append(
                {
                    "name": field.value,
                    "action": decision.action.value,
                    "value": decision.value,
                    "reason": decision.reason,
                    "grounding_ids": grounding_ids,
                }
            )
        reviews.append({"review": index, "fields": fields})
    disagreements = [
        field.value
        for field, signatures in field_signatures.items()
        if len(signatures) == 2 and signatures[0] != signatures[1]
    ]
    return {"reviews": reviews, "disagreements": disagreements}


def _enum_counts(session: Session, column: Any) -> dict[str, int]:
    rows = session.execute(select(column, func.count()).group_by(column)).all()
    return {str(value.value): count for value, count in rows}
