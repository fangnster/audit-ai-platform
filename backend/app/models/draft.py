from typing import Optional
import uuid
from datetime import date, datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Integer, Enum, ForeignKey, Text, Date, DateTime, Index, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class SectionStatus(str, PyEnum):
    draft = "draft"
    approved = "approved"
    locked = "locked"


class TaskType(str, PyEnum):
    fact_confirmation = "fact_confirmation"
    document_upload = "document_upload"
    detail_input = "detail_input"
    feedback = "feedback"


class TaskCreatorRole(str, PyEnum):
    lawyer = "lawyer"
    agent = "agent"


class TaskStatus(str, PyEnum):
    pending_approval = "pending_approval"   # agent-created, waiting lawyer confirm
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    overdue = "overdue"
    rejected = "rejected"


class DraftSection(Base):
    __tablename__ = "draft_sections"
    __table_args__ = (
        Index("idx_draft_sections_case", "case_id", "section_order"),
        Index("idx_draft_sections_case_deleted_version_order", "case_id", "is_deleted", "version", "section_order"),
        Index("idx_draft_sections_case_deleted_updated", "case_id", "is_deleted", text("updated_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    section_order: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=True)
    criterion: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # criterion_1|criterion_2|criterion_3
    status: Mapped[SectionStatus] = mapped_column(Enum(SectionStatus, native_enum=False), default=SectionStatus.draft, nullable=True)
    pending_slots: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)   # {slot_id: {label, filled_content}}
    version: Mapped[str] = mapped_column(String(10), default="main", nullable=True)
    is_deleted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="draft_sections")


class DraftRevision(Base):
    """Immutable snapshots captured before draft edits, rewrites, and restores."""
    __tablename__ = "draft_revisions"
    __table_args__ = (
        Index("idx_draft_revisions_section", "section_id", "revision_number"),
        Index("idx_draft_revisions_case", "case_id"),
        Index("idx_draft_revisions_case_created", "case_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("draft_sections.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_snapshot: Mapped[str] = mapped_column(Text, default="")
    editor_role: Mapped[str] = mapped_column(String(50), nullable=False)
    editor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    change_summary: Mapped[str] = mapped_column(String(500), default="")
    revision_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)


class LawyerTask(Base):
    """Tasks created by lawyer/agent for case management (e.g. supplement requests)."""
    __tablename__ = "client_tasks"  # Keep table name for DB compatibility
    __table_args__ = (
        Index("idx_client_tasks_case_deleted", "case_id", "is_deleted"),
        Index("idx_client_tasks_case_deleted_updated", "case_id", "is_deleted", text("updated_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_by_role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=True)
    legal_rationale: Mapped[str] = mapped_column(Text, default="", nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    attachments: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="lawyer_tasks")


class UserSession(Base):
    """Stores user progress for auto-save/resume."""
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("idx_user_sessions_user", "user_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    page_context: Mapped[str] = mapped_column(String(500), default="", nullable=True)  # current route
    draft_state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)      # editor content, pending inputs
    ui_state: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)         # scroll pos, active panel
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)


from app.models.case import Case  # noqa
