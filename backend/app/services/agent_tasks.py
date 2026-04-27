from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import select

from app.config import settings
from app.models.agent_task import AgentTask, AgentTaskStatus, AgentTaskType
from app.models.document import Document, ParseStatus
from app.services.cache import delete_pattern
from app.utils.timezone import local_iso, local_now


ACTIVE_AGENT_STATUSES = (AgentTaskStatus.queued, AgentTaskStatus.processing)
STALE_RELEASE_MESSAGE = "任务超过系统保护时间仍未完成，已自动释放排队资源，可重新发起。"


def _status_value(status) -> str:
    return str(status.value if hasattr(status, "value") else status)


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _timeout_for(status) -> timedelta:
    status_value = _status_value(status)
    minutes = (
        settings.AGENT_TASK_QUEUED_TIMEOUT_MINUTES
        if status_value == AgentTaskStatus.queued.value
        else settings.AGENT_TASK_PROCESSING_TIMEOUT_MINUTES
    )
    return timedelta(minutes=minutes)


async def release_stale_agent_tasks(
    db,
    *,
    case_id: uuid.UUID | None = None,
    task_types: Iterable[str] | None = None,
    input_key: str | None = None,
    input_value: str | None = None,
    commit: bool = True,
) -> list[AgentTask]:
    """Mark stale queued/processing Agent tasks as failed so UI locks can clear."""
    query = select(AgentTask).where(AgentTask.status.in_(ACTIVE_AGENT_STATUSES)).with_for_update()
    if case_id is not None:
        query = query.where(AgentTask.case_id == case_id)
    if task_types:
        query = query.where(AgentTask.task_type.in_([str(item.value if hasattr(item, "value") else item) for item in task_types]))
    if input_key and input_value is not None:
        query = query.where(AgentTask.input_params.op("->>")(input_key) == str(input_value))

    result = await db.execute(query)
    now = datetime.now(timezone.utc)
    released: list[AgentTask] = []
    touched_case_ids: set[uuid.UUID] = set()

    for task in result.scalars().all():
        previous_status = _status_value(task.status)
        timeout = _timeout_for(task.status)
        reference_time = _aware(task.updated_at or task.created_at)
        if now - reference_time < timeout:
            continue

        task.status = AgentTaskStatus.failed
        task.error_message = STALE_RELEASE_MESSAGE
        task.output_result = {
            **(task.output_result or {}),
            "error": "agent_task_timeout",
            "previous_status": previous_status,
            "released_at": local_iso(local_now()),
            "timeout_minutes": int(timeout.total_seconds() // 60),
        }
        released.append(task)
        touched_case_ids.add(task.case_id)

        if str(task.task_type) == AgentTaskType.fact_extract.value:
            document_id = (task.input_params or {}).get("document_id")
            try:
                doc_uuid = uuid.UUID(str(document_id))
            except Exception:
                doc_uuid = None
            if doc_uuid:
                doc = await db.get(Document, doc_uuid)
                if doc and doc.parse_status == ParseStatus.parsing:
                    doc.parse_status = ParseStatus.failed
                    doc.extracted_metadata = {
                        **(doc.extracted_metadata or {}),
                        "error": STALE_RELEASE_MESSAGE,
                        "released_at": local_iso(local_now()),
                    }

    if not released:
        return []

    if commit:
        await db.commit()
        for touched_case_id in touched_case_ids:
            await delete_pattern(f"documents:{touched_case_id}:*")
            await delete_pattern(f"facts:{touched_case_id}:*")
            await delete_pattern(f"drafts:{touched_case_id}:*")
            await delete_pattern(f"tasks:{touched_case_id}:*")
        await delete_pattern("admin:v1:*")
    return released
