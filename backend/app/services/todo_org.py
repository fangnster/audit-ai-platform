from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import MemberRole, OrgMember, Organization
from app.models.user import User


TODO_ORG_NAME = "个人工作区"


async def get_or_create_todo_org(
    db: AsyncSession,
    user: User,
    preferred_name: Optional[str] = None,
) -> Organization:
    """Compatibility shell for legacy org_id foreign keys.

    Organization/law-firm is intentionally not a business boundary right now.
    Keep one per-user placeholder so old schema constraints and model settings
    keep working until the org structure is revisited.
    """
    result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == user.id)
        .order_by(Organization.created_at.asc())
    )
    org = result.scalars().first()
    if org:
        return org

    name = (preferred_name or "").strip() or TODO_ORG_NAME
    org = Organization(
        name=name,
        slug=f"todo-{user.id.hex[:12]}-{uuid.uuid4().hex[:6]}",
        settings={},
    )
    db.add(org)
    await db.flush()
    db.add(OrgMember(org_id=org.id, user_id=user.id, role=MemberRole.firm_admin))
    await db.flush()
    return org
