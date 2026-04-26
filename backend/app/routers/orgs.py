from __future__ import annotations

import uuid
import time
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.organization import Organization, OrgMember, Team, MemberRole
from app.deps import CurrentUser, DB
from app.llm.provider import LLMProviderError, LLMService

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
    org_settings = org_settings or {}
    return {
        "llm_provider": org_settings.get("llm_provider"),
        "llm_model": org_settings.get("llm_model"),
        "llm_base_url": org_settings.get("llm_base_url"),
        "api_key_configured": bool((org_settings.get("api_key") or "").strip()),
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


def _saved_llm_settings_for_test(org_settings: dict | None, *, require_model: bool = False) -> dict:
    saved = dict(org_settings or {})
    provider = (saved.get("llm_provider") or "").strip()
    base_url = (saved.get("llm_base_url") or "").strip()
    model = (saved.get("llm_model") or "").strip()
    api_key = (saved.get("api_key") or "").strip()

    if not provider:
        raise HTTPException(status_code=422, detail="LLM provider must be saved before testing")
    if not base_url:
        raise HTTPException(status_code=422, detail="LLM base URL must be saved before testing")
    if require_model and not model:
        raise HTTPException(status_code=422, detail="LLM model must be saved before generation testing")
    if not api_key and provider.lower() not in {"ollama", "local"}:
        raise HTTPException(status_code=422, detail="LLM API key must be saved before testing")

    return saved


@router.post("", response_model=OrgResponse, status_code=201)
async def create_org(body: CreateOrgRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(select(Organization).where(Organization.slug == body.slug))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Slug already taken")

    org = Organization(name=body.name, slug=body.slug)
    db.add(org)
    await db.flush()

    # Creator becomes firm_admin
    member = OrgMember(org_id=org.id, user_id=current_user.id, role=MemberRole.firm_admin)
    db.add(member)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/me", response_model=OrgResponse)
async def get_my_org(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == current_user.id)
    )
    org = result.scalars().first()
    if not org:
        raise HTTPException(status_code=404, detail="No organization found")
    return org


@router.patch("/me/settings")
async def update_my_org_settings(body: UpdateOrgSettingsRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == current_user.id)
    )
    org = result.scalars().first()
    if not org:
        raise HTTPException(status_code=404, detail="No organization found")

    org.settings = _merge_llm_settings(org.settings, body)
    await db.commit()
    return {"settings": _public_settings(org.settings)}


@router.get("/me/settings")
async def get_my_org_settings(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == current_user.id)
    )
    org = result.scalars().first()
    if not org:
        raise HTTPException(status_code=404, detail="No organization found")
    return _public_settings(org.settings)


@router.post("/me/settings/test-generation")
async def test_my_org_llm_generation(_body: UpdateOrgSettingsRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == current_user.id)
    )
    org = result.scalars().first()
    if not org:
        raise HTTPException(status_code=404, detail="No organization found")

    candidate_settings = _saved_llm_settings_for_test(org.settings, require_model=True)
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
    result = await db.execute(
        select(OrgMember)
        .join(Organization, OrgMember.org_id == Organization.id)
        .where(OrgMember.org_id.in_(
            select(OrgMember.org_id).where(OrgMember.user_id == current_user.id)
        ))
    )
    return [{"id": str(m.id), "user_id": str(m.user_id), "role": m.role} for m in result.scalars()]


@router.post("/me/invite")
async def invite_member(body: InviteRequest, current_user: CurrentUser, db: DB):
    """Generate invitation token (simplified - in production send email with token)."""
    import secrets
    token = secrets.token_urlsafe(32)
    # TODO: store invite in Redis with TTL=72h, send email
    return {"invite_token": token, "email": body.email, "role": body.role}


@router.post("/join/{token}")
async def join_org(token: str, current_user: CurrentUser, db: DB):
    """Accept invite and join organization."""
    # TODO: retrieve invite from Redis by token, create OrgMember
    return {"message": "Joined successfully"}


@router.delete("/me/members/{member_id}", status_code=204)
async def remove_member(member_id: uuid.UUID, current_user: CurrentUser, db: DB):
    result = await db.execute(select(OrgMember).where(OrgMember.id == member_id))
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.delete(member)
    await db.commit()


@router.patch("/me/members/{member_id}/role")
async def update_member_role(member_id: uuid.UUID, body: UpdateRoleRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(select(OrgMember).where(OrgMember.id == member_id))
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    member.role = body.role
    await db.commit()
    return {"id": str(member.id), "role": member.role}


@router.post("/me/teams", status_code=201)
async def create_team(name: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(OrgMember).where(OrgMember.user_id == current_user.id)
    )
    member = result.scalars().first()
    if not member:
        raise HTTPException(status_code=403, detail="Not in any org")
    team = Team(org_id=member.org_id, name=name)
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return {"id": str(team.id), "name": team.name}


@router.get("/me/teams")
async def list_teams(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(OrgMember).where(OrgMember.user_id == current_user.id)
    )
    member = result.scalars().first()
    if not member:
        return []
    teams = await db.execute(select(Team).where(Team.org_id == member.org_id))
    return [{"id": str(t.id), "name": t.name} for t in teams.scalars()]
