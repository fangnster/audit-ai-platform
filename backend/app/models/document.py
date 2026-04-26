from typing import Optional
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Integer, Boolean, Enum, ForeignKey, DateTime, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class DocType(str, PyEnum):
    petition_letter = "petition_letter"
    evidence = "evidence"
    reference_letter = "reference_letter"
    rfi_response = "rfi_response"
    award = "award"
    patent = "patent"
    publication = "publication"
    citation = "citation"
    employment = "employment"
    media = "media"
    membership = "membership"
    rfi = "rfi"
    other = "other"
    client_upload = "client_upload"


class UploaderRole(str, PyEnum):
    lawyer = "lawyer"
    client = "client"
    agent = "agent"


class ParseStatus(str, PyEnum):
    pending = "pending"
    parsing = "parsing"
    parsed = "parsed"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_case_deleted_created", "case_id", "is_deleted", text("created_at DESC")),
        Index("idx_documents_case_deleted_type_created", "case_id", "is_deleted", "doc_type", text("created_at DESC")),
        Index("idx_documents_case_deleted_uploader_created", "case_id", "is_deleted", "uploader_role", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document_categories.id", ondelete="SET NULL"), nullable=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[DocType] = mapped_column(Enum(DocType, native_enum=False), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)   # org/{org_id}/case/{case_id}/{role}/{category}/{uuid_file}
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream", nullable=True)
    uploader_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    uploader_role: Mapped[UploaderRole] = mapped_column(Enum(UploaderRole, native_enum=False), nullable=False)
    parse_status: Mapped[ParseStatus] = mapped_column(Enum(ParseStatus, native_enum=False), default=ParseStatus.pending, nullable=True)
    extracted_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    case: Mapped["Case"] = relationship("Case", back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship("DocumentVersion", back_populates="document")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        Index("idx_doc_versions_doc", "document_id", "version_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    editor_role: Mapped[str] = mapped_column(String(50), nullable=False)    # agent|lawyer
    editor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    change_summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    diff_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="versions")


from app.models.case import Case  # noqa
