from __future__ import annotations

import uuid
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.organization import MemberRole
from app.deps import CurrentUser, DB
from app.llm.provider import LLMProviderError, LLMService
from app.services.todo_org import get_or_create_todo_org

router = APIRouter()

class CreateOrgRequest(BaseModel):
    name: str
    slug: str


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    settings: dict
    model_config = {"from_attributes": True}


class UpdateOrgRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class InviteRequest(BaseModel):
    email: str
    role: MemberRole


class UpdateRoleRequest(BaseModel):
    role: MemberRole


class UpdateOrgSettingsRequest(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    api_key: str | None = None


def _public_settings(org_settings: dict | None) -> dict:
    saved = org_settings or {}
    service = LLMService()
    provider = (saved.get("llm_provider") or service.provider or "openai").strip()
    model = (saved.get("llm_model") or service.model or "").strip()
    base_url = (saved.get("llm_base_url") or service.base_url or "https://api.openai.com/v1").strip().rstrip("/")
    saved_api_key = (saved.get("api_key") or "").strip()
    effective_api_key = (saved_api_key or service.api_key or "").strip()

    return {
        "llm_provider": provider,
        "llm_model": model,
        "llm_base_url": base_url,
        "api_key_configured": bool(saved_api_key),
        "effective_api_key_configured": bool(effective_api_key),
        "uses_org_provider": bool((saved.get("llm_provider") or "").strip()),
        "uses_org_model": bool((saved.get("llm_model") or "").strip()),
        "uses_org_base_url": bool((saved.get("llm_base_url") or "").strip()),
        "uses_org_api_key": bool(saved_api_key),
    }


def _merge_llm_settings(saved: dict | None, updates: UpdateOrgSettingsRequest) -> dict:
    merged = dict(saved or {})
    for key, value in updates.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
        if key == "api_key" and not value:
            continue
        merged[key] = value
    return merged


def _validate_test_config(base_url: str) -> None:
    if base_url and not base_url.startswith(("http://", "https://")):
        raise HTTPException(
            status_code=422,
            detail="Base URL must start with http:// or https://",
        )


@router.post("", response_model=OrgResponse, status_code=201)
async def create_org(body: CreateOrgRequest, current_user: CurrentUser, db: DB):
    # TODO(org): organization creation is parked. Keep one compatibility shell per user.
    org = await get_or_create_todo_org(db, current_user, body.name)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/me", response_model=OrgResponse)
async def get_my_org(current_user: CurrentUser, db: DB):
    # TODO(org): return the compatibility shell only.
    org = await get_or_create_todo_org(db, current_user)
    await db.commit()
    await db.refresh(org)
    return org


@router.patch("/me", response_model=OrgResponse)
async def update_my_org(body: UpdateOrgRequest, current_user: CurrentUser, db: DB):
    # TODO(org): only the display name is editable while org/law-firm business logic is parked.
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="公司/事务所名称不能为空")
    org = await get_or_create_todo_org(db, current_user)
    org.name = name
    await db.commit()
    await db.refresh(org)
    return org


@router.patch("/me/settings")
async def update_my_org_settings(body: UpdateOrgSettingsRequest, current_user: CurrentUser, db: DB):
    # TODO(org): model settings are stored on the compatibility shell for now.
    org = await get_or_create_todo_org(db, current_user)

    org.settings = _merge_llm_settings(org.settings, body)
    await db.commit()
    return {"settings": _public_settings(org.settings)}


@router.get("/me/settings")
async def get_my_org_settings(current_user: CurrentUser, db: DB):
    # TODO(org): model settings are stored on the compatibility shell for now.
    org = await get_or_create_todo_org(db, current_user)
    await db.commit()
    return _public_settings(org.settings)


@router.post("/me/settings/test-generation")
async def test_my_org_llm_generation(_body: UpdateOrgSettingsRequest, current_user: CurrentUser, db: DB):
    # TODO(org): model settings are stored on the compatibility shell for now.
    org = await get_or_create_todo_org(db, current_user)
    await db.commit()

    candidate_settings = dict(org.settings or {})
    service = LLMService()
    probe_text = f"model-test-{uuid.uuid4().hex[:8]}"
    try:
        config = service._resolve_config(candidate_settings)
        _validate_test_config(config.base_url)
        started_at = time.perf_counter()
        sample = await service.generate(
            f"Reply with exactly this text and nothing else: {probe_text}",
            system="You are a model availability test. Follow the user's instruction exactly.",
            temperature=0,
            max_tokens=1024,
            org_settings=candidate_settings,
        )
        latency_ms = int((time.perf_counter() - started_at) * 1000)
    except HTTPException:
        raise
    except LLMProviderError as exc:
        raise HTTPException(status_code=502, detail=f"LLM generation test failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM generation test failed: {exc}") from exc

    return {
        "ok": True,
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "latency_ms": latency_ms,
        "sample": sample[:300],
        "message": "Model generation succeeded",
    }


@router.get("/me/members")
async def list_members(current_user: CurrentUser, db: DB):
    # TODO(org): org/team membership is parked; expose only the current user shell.
    org = await get_or_create_todo_org(db, current_user)
    await db.commit()
    return [{"id": str(org.id), "user_id": str(current_user.id), "role": "todo"}]


@router.post("/me/invite")
async def invite_member(body: InviteRequest, current_user: CurrentUser, db: DB):
    raise HTTPException(status_code=501, detail="Organization invitations are TODO")


@router.post("/join/{token}")
async def join_org(token: str, current_user: CurrentUser, db: DB):
    raise HTTPException(status_code=501, detail="Organization join is TODO")


@router.delete("/me/members/{member_id}", status_code=204)
async def remove_member(member_id: uuid.UUID, current_user: CurrentUser, db: DB):
    raise HTTPException(status_code=501, detail="Organization members are TODO")


@router.patch("/me/members/{member_id}/role")
async def update_member_role(member_id: uuid.UUID, body: UpdateRoleRequest, current_user: CurrentUser, db: DB):
    raise HTTPException(status_code=501, detail="Organization roles are TODO")


@router.post("/me/teams", status_code=201)
async def create_team(name: str, current_user: CurrentUser, db: DB):
    raise HTTPException(status_code=501, detail="Teams are TODO")


@router.get("/me/teams")
async def list_teams(current_user: CurrentUser, db: DB):
    return []
