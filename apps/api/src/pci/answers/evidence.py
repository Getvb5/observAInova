"""Read only current public material; never expose the claims/review tables."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from pci.answers.schemas import EvidenceSource, Excerpt
from pci.documents.service import _rights_restrict_copy
from pci.models.documents import (
    DocumentTextScope,
    DocumentTextVersion,
    SourceDocument,
    SourceDocumentStatus,
)
from pci.models.production import Production, ProductionVersion
from pci.models.provenance import RawRecord, Source
from pci.productions.search import SearchResult, normalize, query_terms
from pci.storage.objects import COPY_POLICIES

MAX_SOURCES = 5
MAX_EXCERPTS = 3
EXCERPT_CHARACTERS = 1800


def _passages(text: str, page: int | None) -> list[tuple[str, int | None]]:
    result = []
    for paragraph in re.split(r"\n\s*\n", text):
        while paragraph.strip():
            end = min(len(paragraph), EXCERPT_CHARACTERS)
            if end < len(paragraph):
                boundary = paragraph.rfind(" ", end // 2, end)
                if boundary > 0:
                    end = boundary
            chunk, paragraph = paragraph[:end].strip(), paragraph[end:]
            if len(chunk) >= 40:
                result.append((chunk, page))
    return result


def collect_evidence(
    session: Session, items: list[SearchResult], query: str
) -> list[EvidenceSource]:
    terms = query_terms(query)
    sources: list[EvidenceSource] = []
    for item in items:
        if item.source.access_status != "available":
            continue
        context = session.execute(
            select(ProductionVersion, RawRecord, Source)
            .join(Production, Production.id == ProductionVersion.production_id)
            .join(RawRecord, RawRecord.id == ProductionVersion.raw_record_id)
            .join(Source, Source.id == RawRecord.source_id)
            .where(
                Production.id == item.id,
                ProductionVersion.version == Production.current_version_number,
                Source.active.is_(True),
            )
        ).first()
        if context is None:
            continue
        version, raw, source = context
        text_version = None
        passages: list[tuple[str, int | None]] = []
        if source.rights_policy in COPY_POLICIES and not _rights_restrict_copy(raw.rights_snapshot):
            # New restrictions can create a document without any text version.
            # Its state must govern whether older text may leave the system.
            document = session.scalar(
                select(SourceDocument)
                .where(SourceDocument.production_version_id == version.id)
                .order_by(SourceDocument.created_at.desc(), SourceDocument.id.desc())
                .limit(1)
            )
            latest = None
            if (
                document is not None
                and document.status == SourceDocumentStatus.TEXT_EXTRACTED
                and not _rights_restrict_copy(document.rights_snapshot)
            ):
                latest = session.scalar(
                    select(DocumentTextVersion)
                    .options(selectinload(DocumentTextVersion.pages))
                    .where(
                        DocumentTextVersion.production_version_id == version.id,
                        DocumentTextVersion.source_document_id == document.id,
                    )
                    .order_by(DocumentTextVersion.version.desc())
                    .limit(1)
                )
            if latest is not None and latest.scope == DocumentTextScope.FULL_TEXT:
                text_version = latest
                if latest.pages:
                    for page in latest.pages:
                        passages.extend(
                            _passages(
                                latest.normalized_text[page.start_offset : page.end_offset],
                                page.page_number,
                            )
                        )
                else:
                    passages = _passages(latest.normalized_text, None)
        if not passages:
            text_version = None
            passages = _passages(version.abstract or "", None)
        if not passages:
            continue
        selected = sorted(
            enumerate(passages),
            key=lambda pair: -sum(term in normalize(pair[1][0]) for term in terms),
        )[:MAX_EXCERPTS]
        selected.sort(key=lambda pair: pair[0])
        source_id = f"S{len(sources) + 1}"
        sources.append(
            EvidenceSource(
                id=source_id,
                production_id=item.id,
                production_version_id=version.id,
                text_version_id=text_version.id if text_version else None,
                title=item.title,
                authors=item.authors,
                year=item.publication_year,
                url=item.source.source_url,
                reading_scope="full_text_excerpts" if text_version else "abstract_only",
                excerpts=[
                    Excerpt(id=f"{source_id}-E{i + 1}", text=text, page=page)
                    for i, (_, (text, page)) in enumerate(selected)
                ],
            )
        )
        if len(sources) == MAX_SOURCES:
            break
    return sources
