import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_

from app.models.knowledge import KnowledgeItem, KnowledgeType
from app.deps import CurrentUser, DB
from app.services.cache import delete_pattern, get_json, set_json
from app.services.todo_org import get_or_create_todo_org
from app.utils.timezone import local_iso

router = APIRouter()
ALLOWED_KNOWLEDGE_TYPES = {item.value for item in KnowledgeType}
KNOWLEDGE_CACHE_PREFIX = "knowledge:v1"


class CreateKnowledgeRequest(BaseModel):
    title: str
    content: str
    item_type: str
    tags: list[str] = []


class UpdateKnowledgeRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None


class KnowledgeResponse(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    item_type: str
    tags: list
    user_id: uuid.UUID
    is_deleted: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    model_config = {"from_attributes": True}

    @classmethod
    def from_item(cls, item: KnowledgeItem):
        return cls(
            id=item.id,
            title=item.title,
            content=item.content,
            item_type=item.item_type,
            tags=item.tags or [],
            user_id=item.user_id,
            is_deleted=bool(item.is_deleted),
            created_at=local_iso(item.created_at),
            updated_at=local_iso(item.updated_at or item.created_at),
        )


def _knowledge_payload(item: KnowledgeItem) -> dict:
    return KnowledgeResponse.from_item(item).model_dump(mode="json")


async def _invalidate_knowledge_cache(user_id: uuid.UUID) -> None:
    await delete_pattern(f"{KNOWLEDGE_CACHE_PREFIX}:{user_id}:*")
    await delete_pattern("admin:v1:*")


# ── List ──────────────────────────────────
@router.get("", response_model=list[KnowledgeResponse])
async def list_knowledge(current_user: CurrentUser, db: DB, item_type: Optional[str] = None):
    """List all active knowledge items owned by the current lawyer."""
    if item_type and item_type not in ALLOWED_KNOWLEDGE_TYPES:
        raise HTTPException(400, "Invalid knowledge item type")
    cache_key = f"{KNOWLEDGE_CACHE_PREFIX}:{current_user.id}:active:{item_type or 'all'}"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    q = select(KnowledgeItem).where(
        and_(KnowledgeItem.user_id == current_user.id, KnowledgeItem.is_deleted == False)
    )
    if item_type:
        q = q.where(KnowledgeItem.item_type == item_type)
    q = q.order_by(KnowledgeItem.updated_at.desc())
    result = await db.execute(q)
    payload = [_knowledge_payload(item) for item in result.scalars().all()]
    await set_json(cache_key, payload)
    return payload


# ── Trash ─────────────────────────────────
@router.get("/trash", response_model=list[KnowledgeResponse])
async def list_trash(current_user: CurrentUser, db: DB):
    cache_key = f"{KNOWLEDGE_CACHE_PREFIX}:{current_user.id}:trash"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    q = select(KnowledgeItem).where(
        and_(KnowledgeItem.user_id == current_user.id, KnowledgeItem.is_deleted == True)
    ).order_by(KnowledgeItem.updated_at.desc())
    result = await db.execute(q)
    payload = [_knowledge_payload(item) for item in result.scalars().all()]
    await set_json(cache_key, payload)
    return payload


# ── Create ────────────────────────────────
@router.post("", response_model=KnowledgeResponse, status_code=201)
async def create_knowledge(body: CreateKnowledgeRequest, current_user: CurrentUser, db: DB):
    if body.item_type not in ALLOWED_KNOWLEDGE_TYPES:
        raise HTTPException(400, "Invalid knowledge item type")
    # TODO(org): org_id is retained only for legacy FK compatibility.
    org = await get_or_create_todo_org(db, current_user)

    item = KnowledgeItem(
        org_id=org.id,
        user_id=current_user.id,
        title=body.title,
        content=body.content,
        item_type=body.item_type,
        tags=body.tags,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await _invalidate_knowledge_cache(current_user.id)
    return KnowledgeResponse.from_item(item)


# ── Update ────────────────────────────────
@router.patch("/{item_id}", response_model=KnowledgeResponse)
async def update_knowledge(item_id: uuid.UUID, body: UpdateKnowledgeRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(select(KnowledgeItem).where(
        KnowledgeItem.id == item_id,
        KnowledgeItem.user_id == current_user.id,
    ))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Not found")

    if body.title is not None:
        item.title = body.title
    if body.content is not None:
        item.content = body.content
    if body.tags is not None:
        item.tags = body.tags

    await db.commit()
    await db.refresh(item)
    await _invalidate_knowledge_cache(current_user.id)
    return KnowledgeResponse.from_item(item)


# ── Soft Delete ───────────────────────────
@router.delete("/{item_id}")
async def soft_delete(item_id: uuid.UUID, current_user: CurrentUser, db: DB):
    result = await db.execute(select(KnowledgeItem).where(
        KnowledgeItem.id == item_id,
        KnowledgeItem.user_id == current_user.id,
    ))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Not found")
    item.is_deleted = True
    await db.commit()
    await _invalidate_knowledge_cache(current_user.id)
    return {"detail": "moved to trash"}


# ── Restore ───────────────────────────────
@router.post("/{item_id}/restore")
async def restore(item_id: uuid.UUID, current_user: CurrentUser, db: DB):
    result = await db.execute(select(KnowledgeItem).where(
        KnowledgeItem.id == item_id,
        KnowledgeItem.user_id == current_user.id,
    ))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Not found")
    item.is_deleted = False
    await db.commit()
    await _invalidate_knowledge_cache(current_user.id)
    return {"detail": "restored"}


# ── Permanent Delete ──────────────────────
@router.delete("/{item_id}/permanent")
async def permanent_delete(item_id: uuid.UUID, current_user: CurrentUser, db: DB):
    result = await db.execute(select(KnowledgeItem).where(
        KnowledgeItem.id == item_id,
        KnowledgeItem.user_id == current_user.id,
    ))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Not found")
    await db.delete(item)
    await db.commit()
    await _invalidate_knowledge_cache(current_user.id)
    return {"detail": "permanently deleted"}
