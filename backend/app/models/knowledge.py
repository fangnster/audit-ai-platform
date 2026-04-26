import uuid
from typing import Optional
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Text, ForeignKey, DateTime, Boolean, Index, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class KnowledgeType(str, PyEnum):
    prompt_template = "prompt_template"         # 提示词模板
    document_template = "document_template"     # 文案模板
    sample_document = "sample_document"         # 范文
    agent_strategy = "agent_strategy"           # 律师驾驭 Agent 的策略


class KnowledgeItem(Base):
    __tablename__ = "knowledge_items"
    __table_args__ = (
        Index("idx_knowledge_org", "org_id"),
        Index("idx_knowledge_user", "user_id"),
        Index("idx_knowledge_deleted", "is_deleted"),
        Index("idx_knowledge_items_org_deleted_type_updated", "org_id", "is_deleted", "item_type", text("updated_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=True)  # e.g. ["EB1A", "推荐信"]
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
