from typing import Optional
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Float, Enum, ForeignKey, Text, DateTime, Boolean, Index, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class FactStatus(str, PyEnum):
    extracted = "extracted"
    lawyer_approved = "lawyer_approved"
    client_confirmed = "client_confirmed"
    disputed = "disputed"


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (
        Index("idx_facts_case_status", "case_id", "status"),
        Index("idx_facts_case_deleted_created", "case_id", "is_deleted", text("created_at DESC")),
        Index("idx_facts_case_deleted_updated", "case_id", "is_deleted", text("updated_at DESC")),
        Index("idx_facts_source_document_deleted_created", "source_document_id", "is_deleted", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)   # education|employment|award|publication|patent|media
    content: Mapped[str] = mapped_column(Text, nullable=False)
    structured_data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)   # parsed key-value pairs
    status: Mapped[FactStatus] = mapped_column(Enum(FactStatus, native_enum=False), default=FactStatus.extracted, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    case: Mapped["Case"] = relationship("Case", back_populates="facts")
    collaborations: Mapped[list["FactCollaboration"]] = relationship("FactCollaboration", back_populates="fact")


class FactCollaboration(Base):
    __tablename__ = "fact_collaborations"
    __table_args__ = (
        Index("idx_fact_collaborations_fact", "fact_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("facts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)   # confirm|dispute|edit|approve
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    before_value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)
    after_value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    fact: Mapped["Fact"] = relationship("Fact", back_populates="collaborations")


from app.models.case import Case  # noqa
