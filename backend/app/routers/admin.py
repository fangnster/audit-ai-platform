from __future__ import annotations

import uuid
import hashlib
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select

from app.config import settings
from app.deps import DB, SystemAdminUser
from app.middleware.auth import hash_password
from app.models.case import Case
from app.models.document import Document
from app.models.draft import LawyerTask
from app.models.knowledge import KnowledgeItem
from app.models.user import User
from app.services.admin_delete import delete_case_tree, delete_user_tree
from app.services.cache import delete_pattern, get_json, set_json
from app.utils.timezone import local_iso

router = APIRouter()
ADMIN_CACHE_PREFIX = "admin:v1"


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    firm_name: Optional[str] = None
    is_active: bool
    is_system_admin: bool
    case_count: int = 0
    created_at: Optional[str] = None


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int
    page: int
    page_size: int


class AdminUserUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    is_system_admin: Optional[bool] = None


class AdminUserPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8)
    new_password_confirm: str = Field(min_length=8)

    @model_validator(mode="after")
    def validate_new_password(self):
        if self.new_password != self.new_password_confirm:
            raise ValueError("两次输入的新密码不一致")
        return self


class AdminCaseResponse(BaseModel):
    id: uuid.UUID
    title: str
    case_type: str
    status: str
    is_deleted: bool
    lead_lawyer_name: str
    lead_lawyer_email: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminCaseListResponse(BaseModel):
    items: list[AdminCaseResponse]
    total: int
    page: int
    page_size: int


class AdminDeleteResponse(BaseModel):
    cases_deleted: int = 0
    users_deleted: int = 0
    documents_deleted: int = 0
    files_deleted: int = 0
    knowledge_items_deleted: int = 0
    storage_errors: list[str] = Field(default_factory=list)


class AdminOverviewResponse(BaseModel):
    total_users: int
    active_users: int
    system_admins: int
    total_cases: int
    active_cases: int
    deleted_cases: int
    total_documents: int
    total_tasks: int
    pending_tasks: int
    total_knowledge_items: int
    recent_users: list[AdminUserResponse]
    recent_cases: list[AdminCaseResponse]


async def _count(db: DB, stmt) -> int:
    return int((await db.execute(stmt)).scalar_one() or 0)


def _cache_token(value: str) -> str:
    if not value:
        return "-"
    return hashlib.sha1(value.strip().lower().encode("utf-8")).hexdigest()[:16]


async def _invalidate_admin_cache() -> None:
    await delete_pattern(f"{ADMIN_CACHE_PREFIX}:*")


def _sort_direction(column, sort_order: str):
    direction = column.asc() if sort_order == "asc" else column.desc()
    return direction.nullslast()


def _admin_user_order(sort_by: str, sort_order: str, case_count_col):
    columns = {
        "name": func.lower(User.name),
        "email": func.lower(User.email),
        "firm_name": func.lower(User.firm_name),
        "is_active": User.is_active,
        "is_system_admin": User.is_system_admin,
        "case_count": case_count_col,
        "created_at": User.created_at,
    }
    column = columns.get(sort_by, User.created_at)
    order = "asc" if sort_order == "asc" else "desc"
    return (_sort_direction(column, order), User.id.asc())


def _admin_case_order(sort_by: str, sort_order: str):
    updated_at_col = func.coalesce(Case.updated_at, Case.created_at)
    columns = {
        "title": func.lower(Case.title),
        "case_type": Case.case_type,
        "status": Case.status,
        "is_deleted": Case.is_deleted,
        "lead_lawyer": func.lower(User.name),
        "lead_lawyer_email": func.lower(User.email),
        "created_at": Case.created_at,
        "updated_at": updated_at_col,
    }
    column = columns.get(sort_by, updated_at_col)
    order = "asc" if sort_order == "asc" else "desc"
    return (_sort_direction(column, order), Case.id.asc())


async def _active_admin_count(db: DB, exclude_user_id: uuid.UUID | None = None) -> int:
    stmt = select(func.count()).select_from(User).where(
        User.is_system_admin == True,
        User.is_active == True,
    )
    if exclude_user_id:
        stmt = stmt.where(User.id != exclude_user_id)
    return await _count(db, stmt)


async def _ensure_active_admin_remains(
    db: DB,
    target: User,
    next_is_active: bool,
    next_is_system_admin: bool,
) -> None:
    if not target.is_system_admin or not target.is_active:
        return
    if next_is_active and next_is_system_admin:
        return
    if await _active_admin_count(db, exclude_user_id=target.id) == 0:
        raise HTTPException(status_code=400, detail="至少需要保留一个启用中的系统管理员")


def _user_response(user: User, case_count: int = 0) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        firm_name=user.firm_name,
        is_active=bool(user.is_active),
        is_system_admin=bool(user.is_system_admin),
        case_count=case_count,
        created_at=local_iso(user.created_at),
    )


def _case_response(case: Case, lead: User) -> AdminCaseResponse:
    return AdminCaseResponse(
        id=case.id,
        title=case.title,
        case_type=str(case.case_type.value if hasattr(case.case_type, "value") else case.case_type),
        status=str(case.status.value if hasattr(case.status, "value") else case.status),
        is_deleted=case.is_deleted,
        lead_lawyer_name=lead.name,
        lead_lawyer_email=lead.email,
        created_at=local_iso(case.created_at),
        updated_at=local_iso(case.updated_at or case.created_at),
    )


async def _recent_users(db: DB, limit: int = 5) -> list[AdminUserResponse]:
    case_counts = (
        select(Case.lead_lawyer_id.label("user_id"), func.count(Case.id).label("case_count"))
        .group_by(Case.lead_lawyer_id)
        .subquery()
    )
    result = await db.execute(
        select(User, func.coalesce(case_counts.c.case_count, 0))
        .outerjoin(case_counts, case_counts.c.user_id == User.id)
        .order_by(User.created_at.desc())
        .limit(limit)
    )
    return [_user_response(user, int(case_count or 0)) for user, case_count in result.all()]


async def _recent_cases(db: DB, limit: int = 8) -> list[AdminCaseResponse]:
    result = await db.execute(
        select(Case, User)
        .join(User, User.id == Case.lead_lawyer_id)
        .order_by(func.coalesce(Case.updated_at, Case.created_at).desc())
        .limit(limit)
    )
    return [_case_response(case, lead) for case, lead in result.all()]


@router.get("/overview", response_model=AdminOverviewResponse)
async def admin_overview(_admin: SystemAdminUser, db: DB):
    cache_key = f"{ADMIN_CACHE_PREFIX}:overview"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached

    payload = AdminOverviewResponse(
        total_users=await _count(db, select(func.count()).select_from(User)),
        active_users=await _count(db, select(func.count()).select_from(User).where(User.is_active == True)),
        system_admins=await _active_admin_count(db),
        total_cases=await _count(db, select(func.count()).select_from(Case)),
        active_cases=await _count(db, select(func.count()).select_from(Case).where(Case.is_deleted == False)),
        deleted_cases=await _count(db, select(func.count()).select_from(Case).where(Case.is_deleted == True)),
        total_documents=await _count(db, select(func.count()).select_from(Document)),
        total_tasks=await _count(db, select(func.count()).select_from(LawyerTask).where(LawyerTask.is_deleted == False)),
        pending_tasks=await _count(
            db,
            select(func.count()).select_from(LawyerTask).where(
                LawyerTask.is_deleted == False,
                LawyerTask.status.in_(["pending", "pending_approval", "in_progress"]),
            ),
        ),
        total_knowledge_items=await _count(
            db,
            select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.is_deleted == False),
        ),
        recent_users=await _recent_users(db),
        recent_cases=await _recent_cases(db),
    )
    serialized = payload.model_dump(mode="json")
    await set_json(cache_key, serialized, ttl=settings.ADMIN_CACHE_TTL_SECONDS)
    return serialized


@router.get("/users", response_model=AdminUserListResponse)
async def list_admin_users(
    _admin: SystemAdminUser,
    db: DB,
    q: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = "created_at",
    sort_order: str = "desc",
):
    cache_key = (
        f"{ADMIN_CACHE_PREFIX}:users:{_cache_token(q)}:{page}:{page_size}:"
        f"{sort_by}:{sort_order}"
    )
    cached = await get_json(cache_key)
    if cached is not None:
        return cached

    filters = []
    query_text = q.strip()
    if query_text:
        like = f"%{query_text}%"
        filters.append(or_(User.email.ilike(like), User.name.ilike(like), User.firm_name.ilike(like)))

    case_counts = (
        select(Case.lead_lawyer_id.label("user_id"), func.count(Case.id).label("case_count"))
        .group_by(Case.lead_lawyer_id)
        .subquery()
    )
    case_count_col = func.coalesce(case_counts.c.case_count, 0)
    count_stmt = select(func.count()).select_from(User)
    users_stmt = (
        select(User, case_count_col)
        .outerjoin(case_counts, case_counts.c.user_id == User.id)
        .order_by(*_admin_user_order(sort_by, sort_order, case_count_col))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        count_stmt = count_stmt.where(*filters)
        users_stmt = users_stmt.where(*filters)

    total = await _count(db, count_stmt)
    rows = (await db.execute(users_stmt)).all()

    payload = AdminUserListResponse(
        items=[_user_response(user, int(case_count or 0)) for user, case_count in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
    serialized = payload.model_dump(mode="json")
    await set_json(cache_key, serialized, ttl=settings.ADMIN_CACHE_TTL_SECONDS)
    return serialized


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_admin_user(
    user_id: uuid.UUID,
    body: AdminUserUpdateRequest,
    current_admin: SystemAdminUser,
    db: DB,
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    next_is_active = bool(target.is_active if body.is_active is None else body.is_active)
    next_is_system_admin = bool(target.is_system_admin if body.is_system_admin is None else body.is_system_admin)

    if target.id == current_admin.id and not next_is_active:
        raise HTTPException(status_code=400, detail="不能禁用当前登录的管理员")
    if target.id == current_admin.id and not next_is_system_admin:
        raise HTTPException(status_code=400, detail="不能移除当前登录管理员的系统管理员权限")

    await _ensure_active_admin_remains(db, target, next_is_active, next_is_system_admin)

    if body.is_active is not None:
        target.is_active = body.is_active
    if body.is_system_admin is not None:
        target.is_system_admin = body.is_system_admin
    await db.commit()
    await db.refresh(target)
    await _invalidate_admin_cache()

    case_count = await _count(
        db,
        select(func.count()).select_from(Case).where(Case.lead_lawyer_id == target.id),
    )
    return _user_response(target, case_count)


@router.patch("/users/{user_id}/password")
async def reset_admin_user_password(
    user_id: uuid.UUID,
    body: AdminUserPasswordResetRequest,
    _admin: SystemAdminUser,
    db: DB,
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.password_hash = hash_password(body.new_password)
    await db.commit()
    await _invalidate_admin_cache()
    return {"message": "密码已重置"}


@router.delete("/users/{user_id}", response_model=AdminDeleteResponse)
async def delete_admin_user(user_id: uuid.UUID, current_admin: SystemAdminUser, db: DB):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == current_admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员")
    await _ensure_active_admin_remains(db, target, next_is_active=False, next_is_system_admin=False)

    summary = await delete_user_tree(db, user_id)
    await db.commit()
    await _invalidate_admin_cache()
    return summary.as_dict()


@router.get("/cases", response_model=AdminCaseListResponse)
async def list_admin_cases(
    _admin: SystemAdminUser,
    db: DB,
    q: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = "updated_at",
    sort_order: str = "desc",
):
    cache_key = (
        f"{ADMIN_CACHE_PREFIX}:cases:{_cache_token(q)}:{page}:{page_size}:"
        f"{sort_by}:{sort_order}"
    )
    cached = await get_json(cache_key)
    if cached is not None:
        return cached

    filters = []
    query_text = q.strip()
    if query_text:
        like = f"%{query_text}%"
        filters.append(or_(Case.title.ilike(like), User.email.ilike(like), User.name.ilike(like)))

    count_stmt = select(func.count()).select_from(Case).join(User, User.id == Case.lead_lawyer_id)
    cases_stmt = (
        select(Case, User)
        .join(User, User.id == Case.lead_lawyer_id)
        .order_by(*_admin_case_order(sort_by, sort_order))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        count_stmt = count_stmt.where(*filters)
        cases_stmt = cases_stmt.where(*filters)

    total = await _count(db, count_stmt)
    rows = (await db.execute(cases_stmt)).all()
    payload = AdminCaseListResponse(
        items=[_case_response(case, lead) for case, lead in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
    serialized = payload.model_dump(mode="json")
    await set_json(cache_key, serialized, ttl=settings.ADMIN_CACHE_TTL_SECONDS)
    return serialized


@router.get("/cases/recent", response_model=list[AdminCaseResponse])
async def recent_admin_cases(
    _admin: SystemAdminUser,
    db: DB,
    limit: int = Query(default=20, ge=1, le=100),
):
    cache_key = f"{ADMIN_CACHE_PREFIX}:cases:recent:{limit}"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    payload = [item.model_dump(mode="json") for item in await _recent_cases(db, limit)]
    await set_json(cache_key, payload, ttl=settings.ADMIN_CACHE_TTL_SECONDS)
    return payload


@router.delete("/cases/{case_id}", response_model=AdminDeleteResponse)
async def delete_admin_case(case_id: uuid.UUID, _admin: SystemAdminUser, db: DB):
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    summary = await delete_case_tree(db, case_id)
    await db.commit()
    await _invalidate_admin_cache()
    return summary.as_dict()
