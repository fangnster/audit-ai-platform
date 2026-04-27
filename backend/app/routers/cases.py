from __future__ import annotations

import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import select

from app.models.case import Case, CaseMember, CaseStatus, CaseType, CaseMemberRole
from app.deps import CurrentUser, DB, ensure_case_member
from app.services.cache import delete_pattern, get_json, set_json
from app.services.todo_org import get_or_create_todo_org
from app.utils.timezone import local_iso

router = APIRouter()
CASE_CACHE_PREFIX = "cases:v2"


class CreateCaseRequest(BaseModel):
    title: str
    case_type: CaseType
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None

    @model_validator(mode="after")
    def require_client_contact(self):
        if not (self.client_email or "").strip() and not (self.client_phone or "").strip():
            raise ValueError("请至少填写客户邮箱或电话")
        return self


class UpdateCaseRequest(BaseModel):
    title: Optional[str] = None
    case_type: Optional[CaseType] = None
    status: Optional[CaseStatus] = None
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None


class UpdateCaseStatusRequest(BaseModel):
    status: CaseStatus


class CaseResponse(BaseModel):
    id: uuid.UUID
    title: str
    case_type: str
    status: str
    lead_lawyer_id: uuid.UUID
    org_id: uuid.UUID
    client_name: Optional[str] = None
    client_email: Optional[str] = None
    client_phone: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    is_deleted: bool = False
    model_config = {"from_attributes": True}

    @classmethod
    def from_case(cls, case):
        meta = case.metadata_ or {}
        return cls(
            id=case.id, title=case.title, case_type=case.case_type,
            status=case.status, lead_lawyer_id=case.lead_lawyer_id,
            org_id=case.org_id,
            client_name=meta.get("client_name"),
            client_email=meta.get("client_email"),
            client_phone=meta.get("client_phone"),
            created_at=local_iso(case.created_at),
            updated_at=local_iso(case.updated_at or case.created_at),
            is_deleted=case.is_deleted,
        )


class AddMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: CaseMemberRole


async def _invalidate_case_cache(user_id: uuid.UUID | None = None) -> None:
    if user_id:
        await delete_pattern(f"cases:{user_id}:*")
        await delete_pattern(f"{CASE_CACHE_PREFIX}:{user_id}:*")
    else:
        await delete_pattern("cases:*")
        await delete_pattern(f"{CASE_CACHE_PREFIX}:*")
    await delete_pattern("admin:v1:*")


async def _get_case_for_user(case_id: uuid.UUID, current_user, db: DB) -> Case:
    await ensure_case_member(db, case_id, current_user.id)
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


# ── Create ────────────────────────────────

@router.post("", response_model=CaseResponse, status_code=201)
async def create_case(body: CreateCaseRequest, current_user: CurrentUser, db: DB):
    # TODO(org): org is only a legacy FK shell, not a business boundary.
    org = await get_or_create_todo_org(db, current_user)

    case = Case(
        org_id=org.id,
        title=body.title,
        case_type=body.case_type,
        lead_lawyer_id=current_user.id,
        metadata_={
            "client_name": body.client_name or "",
            "client_email": body.client_email or "",
            "client_phone": body.client_phone or "",
        },
    )
    db.add(case)
    await db.flush()

    # Add lead lawyer as case member
    db.add(CaseMember(case_id=case.id, user_id=current_user.id, role=CaseMemberRole.lead_lawyer))
    await db.commit()
    await db.refresh(case)
    await _invalidate_case_cache()
    return CaseResponse.from_case(case)


# ── List (active cases only, exclude deleted) ─

@router.get("", response_model=list[CaseResponse])
async def list_cases(current_user: CurrentUser, db: DB):
    """Returns active (non-deleted) cases where user is a member."""
    cache_key = f"{CASE_CACHE_PREFIX}:{current_user.id}:active"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    result = await db.execute(
        select(Case)
        .join(CaseMember, CaseMember.case_id == Case.id)
        .where(
            CaseMember.user_id == current_user.id,
            Case.is_deleted == False,
        )
        .order_by(Case.updated_at.desc())
    )
    cases = result.scalars().all()
    payload = [CaseResponse.from_case(c).model_dump(mode="json") for c in cases]
    await set_json(cache_key, payload)
    return payload


# ── Trash (list deleted cases) ─────────────

@router.get("/trash", response_model=list[CaseResponse])
async def list_trash(current_user: CurrentUser, db: DB):
    """Returns deleted cases in the recycle bin."""
    cache_key = f"{CASE_CACHE_PREFIX}:{current_user.id}:trash"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    result = await db.execute(
        select(Case)
        .join(CaseMember, CaseMember.case_id == Case.id)
        .where(
            CaseMember.user_id == current_user.id,
            Case.is_deleted == True,
        )
        .order_by(Case.updated_at.desc())
    )
    cases = result.scalars().all()
    payload = [CaseResponse.from_case(c).model_dump(mode="json") for c in cases]
    await set_json(cache_key, payload)
    return payload


# ── Get Detail ─────────────────────────────

@router.get("/{case_id}", response_model=CaseResponse)
async def get_case(case_id: uuid.UUID, current_user: CurrentUser, db: DB):
    cache_key = f"{CASE_CACHE_PREFIX}:{current_user.id}:detail:{case_id}"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    result = await db.execute(
        select(Case)
        .join(CaseMember, CaseMember.case_id == Case.id)
        .where(Case.id == case_id, CaseMember.user_id == current_user.id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    payload = CaseResponse.from_case(case).model_dump(mode="json")
    await set_json(cache_key, payload)
    return payload


# ── Update (edit title / type / status) ────

@router.patch("/{case_id}", response_model=CaseResponse)
async def update_case(case_id: uuid.UUID, body: UpdateCaseRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Case)
        .join(CaseMember, CaseMember.case_id == Case.id)
        .where(Case.id == case_id, CaseMember.user_id == current_user.id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    updates = body.model_dump(exclude_unset=True)
    if body.title is not None:
        case.title = body.title
    if body.case_type is not None:
        case.case_type = body.case_type
    if body.status is not None:
        case.status = body.status
    if any(key in updates for key in ("client_name", "client_email", "client_phone")):
        meta = dict(case.metadata_ or {})
        if "client_name" in updates:
            meta["client_name"] = body.client_name or ""
        if "client_email" in updates:
            meta["client_email"] = body.client_email or ""
        if "client_phone" in updates:
            meta["client_phone"] = body.client_phone or ""
        if not (meta.get("client_email") or "").strip() and not (meta.get("client_phone") or "").strip():
            raise HTTPException(status_code=422, detail="请至少填写客户邮箱或电话")
        case.metadata_ = meta

    await db.commit()
    await db.refresh(case)
    await _invalidate_case_cache()
    return CaseResponse.from_case(case)


# ── Soft Delete (move to trash) ────────────

@router.delete("/{case_id}", status_code=200)
async def soft_delete_case(case_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Move case to recycle bin (soft delete)."""
    case = await _get_case_for_user(case_id, current_user, db)

    case.is_deleted = True
    await db.commit()
    await _invalidate_case_cache()
    return {"id": str(case_id), "status": "moved_to_trash"}


# ── Restore from Trash ────────────────────

@router.post("/{case_id}/restore", status_code=200)
async def restore_case(case_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Restore a case from the recycle bin."""
    case = await _get_case_for_user(case_id, current_user, db)
    if not case.is_deleted:
        raise HTTPException(status_code=404, detail="Case not found in trash")

    case.is_deleted = False
    await db.commit()
    await _invalidate_case_cache()
    return {"id": str(case_id), "status": "restored"}


# ── Permanent Delete (from trash only) ─────

@router.delete("/{case_id}/permanent", status_code=200)
async def permanent_delete_case(case_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Permanently delete a case (only works for cases in trash)."""
    case = await _get_case_for_user(case_id, current_user, db)
    if not case.is_deleted:
        raise HTTPException(status_code=404, detail="Case not found in trash")

    # Delete related records explicitly (async session may not cascade automatically)
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(CaseMember).where(CaseMember.case_id == case_id))
    await db.delete(case)
    await db.commit()
    await _invalidate_case_cache()
    return {"id": str(case_id), "status": "permanently_deleted"}


# ── Legacy: Update status ──────────────────

@router.patch("/{case_id}/status")
async def update_case_status(case_id: uuid.UUID, body: UpdateCaseStatusRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Case)
        .join(CaseMember, CaseMember.case_id == Case.id)
        .where(Case.id == case_id, CaseMember.user_id == current_user.id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    case.status = body.status
    await db.commit()
    await _invalidate_case_cache()
    return {"id": str(case.id), "status": case.status}


# ── Members ────────────────────────────────

@router.post("/{case_id}/members", status_code=201)
async def add_case_member(case_id: uuid.UUID, body: AddMemberRequest, current_user: CurrentUser, db: DB):
    await ensure_case_member(db, case_id, current_user.id)
    member = CaseMember(case_id=case_id, user_id=body.user_id, role=body.role)
    db.add(member)
    await db.commit()
    await _invalidate_case_cache()
    return {"case_id": str(case_id), "user_id": str(body.user_id), "role": body.role}


@router.delete("/{case_id}/members/{user_id}", status_code=204)
async def remove_case_member(case_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DB):
    await ensure_case_member(db, case_id, current_user.id)
    result = await db.execute(
        select(CaseMember).where(CaseMember.case_id == case_id, CaseMember.user_id == user_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.delete(member)
    await db.commit()
    await _invalidate_case_cache()
