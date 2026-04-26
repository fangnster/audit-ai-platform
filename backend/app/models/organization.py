from typing import Optional
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Boolean, Integer, Enum, ForeignKey, DateTime, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class OrgPlan(str, PyEnum):
    free = "free"
    pro = "pro"
    enterprise = "enterprise"


class MemberRole(str, PyEnum):
    firm_admin = "firm_admin"
    lead_lawyer = "lead_lawyer"
    associate = "associate"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # settings: {default_llm, api_keys(encrypted), token_quota, fallback_model, llm_configs}
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)
    plan: Mapped[OrgPlan] = mapped_column(Enum(OrgPlan, native_enum=False), default=OrgPlan.free, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    members: Mapped[list["OrgMember"]] = relationship("OrgMember", back_populates="organization")
    teams: Mapped[list["Team"]] = relationship("Team", back_populates="organization")
    document_categories: Mapped[list["DocumentCategory"]] = relationship("DocumentCategory", back_populates="organization")


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        Index("idx_teams_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="teams")


class OrgMember(Base):
    __tablename__ = "org_members"
    __table_args__ = (
        Index("idx_org_members_org", "org_id"),
        Index("idx_org_members_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[MemberRole] = mapped_column(Enum(MemberRole, native_enum=False), nullable=False)
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="members")


class DocumentCategory(Base):
    """File categories - system presets + org custom categories."""
    __tablename__ = "document_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)  # NULL = system preset
    name: Mapped[str] = mapped_column(String(100), nullable=False)         # e.g. "award"
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g. "奖项证明"
    icon: Mapped[str] = mapped_column(String(100), default="file", nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)         # system presets cannot be deleted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)

    organization: Mapped[Optional["Organization"]] = relationship("Organization", back_populates="document_categories")
