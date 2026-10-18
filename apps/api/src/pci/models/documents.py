import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pci.models.base import Base, UUIDPrimaryKeyMixin, reject_append_only_change, utc_now
from pci.models.enums import enum_values

if TYPE_CHECKING:
    from pci.models.production import ProductionVersion


class SourceDocumentStatus(StrEnum):
    PENDING = "pending"
    RETRIEVED = "retrieved"
    TEXT_EXTRACTED = "text_extracted"
    OCR_REQUIRED = "ocr_required"
    RESTRICTED = "restricted"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class DocumentTextScope(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"


class TextExtractionMethod(StrEnum):
    PYPDF = "pypdf"
    METADATA_ABSTRACT = "metadata_abstract"
    MANUAL = "manual"
    OCR = "ocr"


class SourceDocument(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_source_documents_supersedes"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_source_documents_size"),
    )

    production_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[SourceDocumentStatus] = mapped_column(
        Enum(
            SourceDocumentStatus,
            name="source_document_status",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
        default=SourceDocumentStatus.PENDING,
        index=True,
    )
    official_url: Mapped[str | None] = mapped_column(String(2048))
    same_origin_host: Mapped[str | None] = mapped_column(String(255))
    object_key: Mapped[str | None] = mapped_column(String(1024), unique=True)
    object_checksum: Mapped[str | None] = mapped_column(String(64))
    media_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    rights_snapshot: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    production_version: Mapped["ProductionVersion"] = relationship()
    text_versions: Mapped[list["DocumentTextVersion"]] = relationship(
        back_populates="source_document", passive_deletes="all"
    )


class DocumentTextVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_text_versions"
    __table_args__ = (
        UniqueConstraint(
            "production_version_id",
            "version",
            name="uq_document_text_versions_production_version",
        ),
        CheckConstraint("version >= 1", name="ck_document_text_versions_version"),
    )

    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    production_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[DocumentTextScope] = mapped_column(
        Enum(
            DocumentTextScope,
            name="document_text_scope",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
    )
    extraction_method: Mapped[TextExtractionMethod] = mapped_column(
        Enum(
            TextExtractionMethod,
            name="text_extraction_method",
            values_callable=enum_values,
            validate_strings=True,
            create_constraint=True,
        ),
        nullable=False,
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    source_document: Mapped[SourceDocument] = relationship(back_populates="text_versions")
    production_version: Mapped["ProductionVersion"] = relationship()
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document_text_version",
        order_by="DocumentPage.page_number",
        passive_deletes="all",
    )


class DocumentPage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint(
            "document_text_version_id",
            "page_number",
            name="uq_document_pages_text_version_page",
        ),
        CheckConstraint("page_number >= 1", name="ck_document_pages_number"),
        CheckConstraint("start_offset >= 0", name="ck_document_pages_start_offset"),
        CheckConstraint("end_offset >= start_offset", name="ck_document_pages_offsets"),
    )

    document_text_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_text_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    document_text_version: Mapped[DocumentTextVersion] = relationship(back_populates="pages")


for model in (DocumentTextVersion, DocumentPage):
    event.listen(model, "before_update", reject_append_only_change)
    event.listen(model, "before_delete", reject_append_only_change)
