from typing import Optional
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Integer, Enum, ForeignKey, DateTime, Index, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class AgentTaskType(str, PyEnum):
    fact_extract = "fact_extract"
    draft_generate = "draft_generate"
    rfi_generate = "rfi_generate"
    merge = "merge"
    rewrite_section = "rewrite_section"
    translate = "translate"


class AgentTaskStatus(str, PyEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (
        Index("idx_agent_tasks_case_created", "case_id", text("created_at DESC")),
        Index("idx_agent_tasks_case_updated", "case_id", text("updated_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    input_params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)
    output_result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=True)
    status: Mapped[AgentTaskStatus] = mapped_column(Enum(AgentTaskStatus), default=AgentTaskStatus.queued, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=True)     # 0=highest (P0 fact fix)
    llm_model: Mapped[str] = mapped_column(String(100), default="claude", nullable=True)
    token_usage: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="agent_tasks")


from app.models.case import Case  # noqa
