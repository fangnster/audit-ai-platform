import uuid
from typing import Optional
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Enum, ForeignKey, DateTime, Boolean, Index, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class CaseType(str, PyEnum):
    EB1A = "EB1A"
    EB1B = "EB1B"
    NIW = "NIW"
    O1A = "O1A"
    EB2 = "EB2"
    EB3 = "EB3"
    H1B = "H1B"


class CaseStatus(str, PyEnum):
    intake = "intake"
    fact_extraction = "fact_extraction"
    drafting = "drafting"
    review = "review"
    submitted = "submitted"


class CaseMemberRole(str, PyEnum):
    lead_lawyer = "lead_lawyer"
    associate = "associate"
    client = "client"


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        Index("idx_cases_org", "org_id"),
        Index("idx_cases_lawyer", "lead_lawyer_id", "status"),
        Index("idx_cases_deleted_created", "is_deleted", text("created_at DESC")),
        Index("idx_cases_deleted_updated", "is_deleted", text("updated_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    case_type: Mapped[CaseType] = mapped_column(Enum(CaseType), nullable=False)
    status: Mapped[CaseStatus] = mapped_column(Enum(CaseStatus), default=CaseStatus.intake, nullable=True)
    lead_lawyer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    members: Mapped[list["CaseMember"]] = relationship("CaseMember", back_populates="case")
    documents: Mapped[list["Document"]] = relationship("Document", back_populates="case")
    facts: Mapped[list["Fact"]] = relationship("Fact", back_populates="case")
    lawyer_tasks: Mapped[list["LawyerTask"]] = relationship("LawyerTask", back_populates="case")
    draft_sections: Mapped[list["DraftSection"]] = relationship("DraftSection", back_populates="case")
    agent_tasks: Mapped[list["AgentTask"]] = relationship("AgentTask", back_populates="case")


class CaseMember(Base):
    __tablename__ = "case_members"
    __table_args__ = (
        Index("idx_case_members_case", "case_id"),
        Index("idx_case_members_user_case", "user_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[CaseMemberRole] = mapped_column(Enum(CaseMemberRole), nullable=False)
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="members")


# Avoid circular imports - import here
from app.models.document import Document  # noqa
from app.models.fact import Fact  # noqa
from app.models.draft import DraftSection, LawyerTask  # noqa
from app.models.agent_task import AgentTask  # noqa
