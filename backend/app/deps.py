import uuid
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import decode_token
from app.models.case import CaseMember
from app.models.user import User
from app.models.organization import OrgMember, Organization, MemberRole

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


async def get_current_org_member(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    org_id: Optional[uuid.UUID] = None,
) -> OrgMember:
    """Get the current user's membership in the org (from token or query param)."""
    payload = decode_token  # org_id should be in JWT
    # In practice, org_id is embedded in JWT claims during login
    # This is a simplified version
    if not org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="org_id required")

    result = await db.execute(
        select(OrgMember).where(
            OrgMember.user_id == current_user.id,
            OrgMember.org_id == org_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")
    return member


async def ensure_case_member(db: AsyncSession, case_id: uuid.UUID, user_id: uuid.UUID) -> CaseMember:
    """Require the user to be a member of the case before reading or mutating case data."""
    result = await db.execute(
        select(CaseMember).where(
            CaseMember.case_id == case_id,
            CaseMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return member


def require_role(*roles: MemberRole):
    """Dependency factory: requires user to have one of the specified roles in their org."""
    async def _check(
        member: Annotated[OrgMember, Depends(get_current_org_member)],
    ) -> OrgMember:
        if member.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in roles]}",
            )
        return member
    return _check


# Convenience type aliases
CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]
