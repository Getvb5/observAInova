import hashlib
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pci.auth.contracts import AuthPrincipal, Role
from pci.claims.enums import CandidateStatus, ContributionField, ExtractionRunStatus
from pci.models.base import utc_now
from pci.models.claims import CandidateContribution, ExtractionRun
from pci.models.contributions import (
    ContributionCandidateSource,
    ContributionGrounding,
    ContributionVersion,
    ContributionVersionStatus,
    ScientificContribution,
)
from pci.models.documents import (
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
    TextExtractionMethod,
)
from pci.models.enums import ProductionType, RightsPolicy
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import RawRecord, Source
from pci.models.publication import (
    OutboxStatus,
    PublicationAction,
    PublicationOutbox,
    PublishedContribution,
)
from pci.models.review import ReviewAssignment, ReviewCase, ReviewCaseKind, ReviewLane, ReviewStatus
from pci.publication.service import (
    SeparationOfDutiesError,
    claim_next_publication_event,
    decide_publication,
    process_publication_event,
)


def supervisor() -> AuthPrincipal:
    return AuthPrincipal("test", "supervisor", None, frozenset({Role.SUPERVISOR}))


def version_fixture(
    session: Session, version_number: int = 1, contribution: ScientificContribution | None = None
) -> ContributionVersion:
    if contribution is None:
        production = Production(canonical_key=f"local:{uuid.uuid4()}")
        session.add(production)
        session.flush()
        contribution = ScientificContribution(
            production_id=production.id, current_version_number=version_number
        )
        session.add(contribution)
        session.flush()
    production = session.get(Production, contribution.production_id)
    assert production is not None
    source = Source(
        code=f"publication-{uuid.uuid4()}",
        name="UFPE",
        connector_type="fixture",
        rights_policy=RightsPolicy.OPEN_COPY,
    )
    raw = RawRecord(
        source=source,
        source_identifier=str(uuid.uuid4()),
        payload={},
        checksum=uuid.uuid4().hex,
    )
    session.add_all([source, raw])
    session.flush()
    production_version = ProductionVersion(
        production_id=production.id,
        raw_record_id=raw.id,
        version=version_number,
        title=f"Tese {version_number}",
        publication_year=2024,
        type=ProductionType.THESIS,
    )
    session.add(production_version)
    session.flush()
    document = SourceDocument(
        production_version_id=production_version.id,
        status=SourceDocumentStatus.TEXT_EXTRACTED,
    )
    session.add(document)
    session.flush()
    text_value = f"Versão {version_number}"
    text = DocumentTextVersion(
        source_document_id=document.id,
        production_version_id=production_version.id,
        version=1,
        normalized_text=text_value,
        scope=DocumentTextScope.FULL_TEXT,
        extraction_method=TextExtractionMethod.MANUAL,
        checksum=hashlib.sha256(text_value.encode()).hexdigest(),
    )
    session.add(text)
    session.flush()
    extraction = ExtractionRun(
        document_text_version_id=text.id,
        document_checksum=text.checksum,
        provider="fixture",
        model="fixture",
        schema_version="v1",
        instruction_version="v1",
        status=ExtractionRunStatus.SUCCEEDED,
    )
    session.add(extraction)
    session.flush()
    candidate = CandidateContribution(
        extraction_run_id=extraction.id,
        ordinal=1,
        status=CandidateStatus.GENERATED,
    )
    session.add(candidate)
    session.flush()
    version = ContributionVersion(
        scientific_contribution_id=contribution.id,
        version=version_number,
        status=ContributionVersionStatus.VALIDATED,
        created_by="test|curator",
        description=f"Versão {version_number}",
        validated_at=utc_now(),
    )
    session.add(version)
    session.flush()
    contribution.current_version_number = version_number
    session.add_all(
        [
            ContributionCandidateSource(
                contribution_version_id=version.id,
                candidate_contribution_id=candidate.id,
                review_assignment_id=uuid.uuid4(),
                curator_actor_key="test|curator",
            ),
            ContributionGrounding(
                contribution_version_id=version.id,
                field=ContributionField.DESCRIPTION,
                source_scope=DocumentTextScope.FULL_TEXT.value,
                document_text_version_id=text.id,
                start_offset=0,
                end_offset=len(text_value),
                quote=text_value,
                quote_hash=hashlib.sha256(text_value.encode()).hexdigest(),
            ),
        ]
    )
    session.flush()
    return version


def decide_and_process(
    session: Session,
    version: ContributionVersion,
    action: PublicationAction,
    reason: str | None = None,
) -> PublicationOutbox:
    decision = decide_publication(session, version.id, action, reason, supervisor())
    event = session.scalar(
        select(PublicationOutbox).where(PublicationOutbox.publication_decision_id == decision.id)
    )
    assert event is not None
    process_publication_event(session, event.id)
    return event


def source_text_for_version(session: Session, version: ContributionVersion) -> DocumentTextVersion:
    text = session.scalar(
        select(DocumentTextVersion)
        .join(ExtractionRun, ExtractionRun.document_text_version_id == DocumentTextVersion.id)
        .join(
            CandidateContribution,
            CandidateContribution.extraction_run_id == ExtractionRun.id,
        )
        .join(
            ContributionCandidateSource,
            ContributionCandidateSource.candidate_contribution_id == CandidateContribution.id,
        )
        .where(ContributionCandidateSource.contribution_version_id == version.id)
    )
    assert text is not None
    return text


def test_publish_supersede_and_revoke_enforce_monotonic_single_active_projection(
    session: Session,
) -> None:
    first = version_fixture(session)
    decide_and_process(session, first, PublicationAction.PUBLISH)
    contribution = session.get(ScientificContribution, first.scientific_contribution_id)
    assert contribution is not None
    second = version_fixture(session, 2, contribution)

    decide_and_process(session, second, PublicationAction.SUPERSEDE, "evidência atualizada")

    active = session.scalars(
        select(PublishedContribution).where(
            PublishedContribution.scientific_contribution_id == contribution.id,
            PublishedContribution.active.is_(True),
        )
    ).all()
    assert [item.version for item in active] == [2]
    assert first.status is ContributionVersionStatus.SUPERSEDED
    decide_and_process(session, second, PublicationAction.REVOKE, "fonte invalidada")
    assert (
        session.scalar(
            select(PublishedContribution).where(
                PublishedContribution.scientific_contribution_id == contribution.id,
                PublishedContribution.active.is_(True),
            )
        )
        is None
    )
    assert second.status is ContributionVersionStatus.REVOKED


def test_illegal_or_duplicate_publication_decisions_are_rejected(session: Session) -> None:
    version = version_fixture(session)
    decide_publication(session, version.id, PublicationAction.PUBLISH, None, supervisor())
    with pytest.raises(ValueError, match="pending publication decision"):
        decide_publication(session, version.id, PublicationAction.PUBLISH, None, supervisor())
    unrelated = version_fixture(session)
    with pytest.raises(ValueError, match="published version"):
        decide_publication(session, unrelated.id, PublicationAction.REVOKE, "no", supervisor())


def test_return_opens_one_correction_revision_and_curator_assignment(session: Session) -> None:
    version = version_fixture(session)
    event = decide_and_process(
        session, version, PublicationAction.RETURN, "fundamento insuficiente"
    )
    assert version.status is ContributionVersionStatus.RETURNED
    contribution = session.get(ScientificContribution, version.scientific_contribution_id)
    assert contribution is not None
    assert contribution.current_version_number == 2
    revision = session.scalar(
        select(ContributionVersion).where(ContributionVersion.base_version_id == version.id)
    )
    assert revision is not None
    assert revision.status is ContributionVersionStatus.DRAFT
    assert revision.description == version.description
    correction_case = session.get(ReviewCase, revision.review_case_id)
    assert correction_case is not None
    assert correction_case.kind is ReviewCaseKind.RETURN_CORRECTION
    assert correction_case.correction_base_version_id == version.id
    assert correction_case.priority_reason == "fundamento insuficiente"
    assignment = session.scalar(
        select(ReviewAssignment).where(ReviewAssignment.review_case_id == correction_case.id)
    )
    assert assignment is not None
    assert assignment.lane is ReviewLane.SINGLE
    assert assignment.status is ReviewStatus.PENDING

    process_publication_event(session, event.id)
    assert session.scalars(
        select(ContributionVersion).where(ContributionVersion.base_version_id == version.id)
    ).all() == [revision]


def test_outbox_claim_recovers_only_expired_processing_lease(session: Session) -> None:
    version = version_fixture(session)
    decision = decide_publication(
        session, version.id, PublicationAction.PUBLISH, None, supervisor()
    )
    event = session.scalar(
        select(PublicationOutbox).where(PublicationOutbox.publication_decision_id == decision.id)
    )
    assert event is not None
    claimed = claim_next_publication_event(session, lease_seconds=60)
    assert (
        claimed is not None and claimed.id == event.id and claimed.status is OutboxStatus.PROCESSING
    )
    first_token = claimed.attempt_token
    assert claim_next_publication_event(session, lease_seconds=60) is None
    event.attempt_started_at = utc_now() - timedelta(seconds=61)
    session.flush()
    recovered = claim_next_publication_event(session, lease_seconds=60)
    assert (
        recovered is not None
        and recovered.id == event.id
        and recovered.attempt_token != first_token
    )


def test_failed_supersede_releases_version_from_publication_pending(session: Session) -> None:
    first = version_fixture(session)
    decide_and_process(session, first, PublicationAction.PUBLISH)
    contribution = session.get(ScientificContribution, first.scientific_contribution_id)
    assert contribution is not None
    second = version_fixture(session, 2, contribution)
    decision = decide_publication(
        session,
        second.id,
        PublicationAction.SUPERSEDE,
        "new validated evidence",
        supervisor(),
    )
    active = session.scalar(
        select(PublishedContribution).where(
            PublishedContribution.scientific_contribution_id == contribution.id,
            PublishedContribution.active.is_(True),
        )
    )
    assert active is not None
    active.active = False
    event = session.scalar(
        select(PublicationOutbox).where(PublicationOutbox.publication_decision_id == decision.id)
    )
    assert event is not None

    process_publication_event(session, event.id)

    assert event.status is OutboxStatus.FAILED
    assert event.error_code == "active_version_missing"
    assert second.status is ContributionVersionStatus.VALIDATED


def test_curator_cannot_return_or_revoke_their_own_version(session: Session) -> None:
    version = version_fixture(session)
    session.add(
        ContributionCandidateSource(
            contribution_version_id=version.id,
            candidate_contribution_id=uuid.uuid4(),
            review_assignment_id=uuid.uuid4(),
            curator_actor_key="test|dual-role",
        )
    )
    session.flush()
    dual_role = AuthPrincipal(
        "test",
        "dual-role",
        None,
        frozenset({Role.CURATOR, Role.SUPERVISOR}),
    )

    with pytest.raises(SeparationOfDutiesError):
        decide_publication(
            session,
            version.id,
            PublicationAction.RETURN,
            "Requires correction",
            dual_role,
        )

    decide_and_process(session, version, PublicationAction.PUBLISH)
    with pytest.raises(SeparationOfDutiesError):
        decide_publication(
            session,
            version.id,
            PublicationAction.REVOKE,
            "Source invalidated",
            dual_role,
        )


def test_publish_rejects_groundings_from_multiple_document_text_versions(
    session: Session,
) -> None:
    first = version_fixture(session)
    contribution = session.get(ScientificContribution, first.scientific_contribution_id)
    assert contribution is not None
    second = version_fixture(session, 2, contribution)
    second_text = source_text_for_version(session, second)
    session.add(
        ContributionGrounding(
            contribution_version_id=first.id,
            field=ContributionField.DESCRIPTION,
            source_scope=second_text.scope.value,
            document_text_version_id=second_text.id,
            start_offset=0,
            end_offset=len(second_text.normalized_text),
            quote=second_text.normalized_text,
            quote_hash=hashlib.sha256(second_text.normalized_text.encode()).hexdigest(),
        )
    )
    session.flush()

    with pytest.raises(ValueError, match="single document text version"):
        decide_publication(
            session,
            first.id,
            PublicationAction.PUBLISH,
            None,
            supervisor(),
        )


def test_publication_event_revalidates_source_provenance_before_projection(
    session: Session,
) -> None:
    first = version_fixture(session)
    decision = decide_publication(
        session,
        first.id,
        PublicationAction.PUBLISH,
        None,
        supervisor(),
    )
    event = session.scalar(
        select(PublicationOutbox).where(PublicationOutbox.publication_decision_id == decision.id)
    )
    assert event is not None
    contribution = session.get(ScientificContribution, first.scientific_contribution_id)
    assert contribution is not None
    second = version_fixture(session, 2, contribution)
    second_text = source_text_for_version(session, second)
    session.add(
        ContributionGrounding(
            contribution_version_id=first.id,
            field=ContributionField.DESCRIPTION,
            source_scope=second_text.scope.value,
            document_text_version_id=second_text.id,
            start_offset=0,
            end_offset=len(second_text.normalized_text),
            quote=second_text.normalized_text,
            quote_hash=hashlib.sha256(second_text.normalized_text.encode()).hexdigest(),
        )
    )
    session.flush()

    process_publication_event(session, event.id)

    assert event.status is OutboxStatus.FAILED
    assert event.error_code == "invalid_provenance"
    assert first.status is ContributionVersionStatus.VALIDATED
    assert session.scalar(select(PublishedContribution)) is None
