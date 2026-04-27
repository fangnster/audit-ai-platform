import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from app.models.draft import LawyerTask
from app.deps import CurrentUser, DB, ensure_case_member
from app.services.cache import delete_pattern, get_json, set_json
from app.utils.timezone import local_iso

router = APIRouter()
TASK_CACHE_PREFIX = "tasks:v2"


class CreateTaskRequest(BaseModel):
    task_type: str = "document_upload"
    title: str
    description: str = ""
    legal_rationale: str = ""


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


ALLOWED_TASK_STATUSES = {
    "pending_approval",
    "pending",
    "in_progress",
    "completed",
    "overdue",
    "rejected",
}


def _task_order(sort_by: str, sort_order: str):
    columns = {
        "updated_at": LawyerTask.updated_at,
        "created_at": LawyerTask.created_at,
        "due_date": LawyerTask.due_date,
        "status": LawyerTask.status,
        "title": LawyerTask.title,
    }
    column = columns.get(sort_by, LawyerTask.updated_at)
    direction = column.asc() if sort_order == "asc" else column.desc()
    return [direction, LawyerTask.created_at.desc()]


def _task_payload(t: LawyerTask) -> dict:
    return {
        "id": str(t.id), "title": t.title, "description": t.description or "",
        "status": t.status, "created_by_role": t.created_by_role,
        "task_type": t.task_type,
        "created_at": local_iso(t.created_at),
        "updated_at": local_iso(t.updated_at or t.created_at),
        "legal_rationale": t.legal_rationale or "",
        "due_date": t.due_date.isoformat() if t.due_date else None,
    }


async def _invalidate_task_cache(case_id: uuid.UUID) -> None:
    await delete_pattern(f"tasks:{case_id}:*")
    await delete_pattern(f"{TASK_CACHE_PREFIX}:{case_id}:*")
    await delete_pattern("admin:v1:*")


async def _get_task_for_user(task_id: uuid.UUID, current_user, db: DB) -> LawyerTask:
    result = await db.execute(select(LawyerTask).where(LawyerTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    await ensure_case_member(db, task.case_id, current_user.id)
    return task


@router.get("/cases/{case_id}")
async def list_tasks(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
):
    await ensure_case_member(db, case_id, current_user.id)
    cache_key = f"{TASK_CACHE_PREFIX}:{case_id}:{current_user.id}:{sort_by}:{sort_order}"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    result = await db.execute(
        select(LawyerTask).where(LawyerTask.case_id == case_id, LawyerTask.is_deleted == False)
        .order_by(*_task_order(sort_by, sort_order))
    )
    payload = [_task_payload(t) for t in result.scalars()]
    await set_json(cache_key, payload)
    return payload


@router.post("/cases/{case_id}", status_code=201)
async def create_task(case_id: uuid.UUID, body: CreateTaskRequest, current_user: CurrentUser, db: DB):
    await ensure_case_member(db, case_id, current_user.id)
    task = LawyerTask(
        case_id=case_id,
        task_type=body.task_type,
        created_by_role="lawyer",
        created_by_id=current_user.id,
        title=body.title,
        description=body.description,
        legal_rationale=body.legal_rationale,
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    await _invalidate_task_cache(case_id)
    return {"id": str(task.id), "status": task.status}


@router.post("/{task_id}/approve")
async def approve_task(task_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Lawyer approves an agent-generated task."""
    task = await _get_task_for_user(task_id, current_user, db)
    if task.created_by_role != "agent" or task.status != "pending_approval":
        raise HTTPException(400, "Only agent-created tasks pending lawyer approval can be approved")
    task.status = "pending"
    task.approved_by_id = current_user.id
    await db.commit()
    await _invalidate_task_cache(task.case_id)
    return {"id": str(task.id), "status": task.status}


@router.patch("/{task_id}")
async def update_task(task_id: uuid.UUID, body: UpdateTaskRequest, current_user: CurrentUser, db: DB):
    task = await _get_task_for_user(task_id, current_user, db)
    if body.title is not None: task.title = body.title
    if body.description is not None: task.description = body.description
    if body.status is not None:
        if body.status not in ALLOWED_TASK_STATUSES:
            raise HTTPException(400, "Invalid task status")
        task.status = body.status
    await db.commit()
    await _invalidate_task_cache(task.case_id)
    return {"id": str(task.id), "status": task.status}


@router.post("/{task_id}/complete")
async def complete_task(task_id: uuid.UUID, current_user: CurrentUser, db: DB):
    task = await _get_task_for_user(task_id, current_user, db)
    task.status = "completed"
    await db.commit()
    await _invalidate_task_cache(task.case_id)
    return {"id": str(task.id), "status": task.status}


@router.delete("/{task_id}")
async def soft_delete_task(task_id: uuid.UUID, current_user: CurrentUser, db: DB):
    task = await _get_task_for_user(task_id, current_user, db)
    task.is_deleted = True
    await db.commit()
    await _invalidate_task_cache(task.case_id)
    return {"id": str(task.id), "status": "deleted"}


@router.post("/{task_id}/restore")
async def restore_task(task_id: uuid.UUID, current_user: CurrentUser, db: DB):
    task = await _get_task_for_user(task_id, current_user, db)
    task.is_deleted = False
    await db.commit()
    await _invalidate_task_cache(task.case_id)
    return {"id": str(task.id), "status": "restored"}
