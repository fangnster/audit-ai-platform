import uuid
from datetime import timedelta
from typing import Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.middleware.auth import verify_password, hash_password, create_access_token, create_refresh_token
from app.models.user import User
from app.deps import CurrentUser
from app.services.cache import delete_pattern
from app.services.todo_org import get_or_create_todo_org

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str = Field(min_length=8)
    password_confirm: str = Field(min_length=8)
    firm_name: Optional[str] = None
    org_name: Optional[str] = None

    @model_validator(mode="after")
    def validate_registration(self):
        if self.password != self.password_confirm:
            raise ValueError("两次输入的密码不一致")
        return self


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    firm_name: Optional[str] = None
    is_system_admin: bool = False
    profile: dict

    model_config = {"from_attributes": True}


class UpdateMeRequest(BaseModel):
    name: Optional[str] = None
    firm_name: Optional[str] = None
    phone: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)
    new_password_confirm: str = Field(min_length=8)

    @model_validator(mode="after")
    def validate_new_password(self):
        if self.new_password != self.new_password_confirm:
            raise ValueError("两次输入的新密码不一致")
        return self


def _configured_admin_emails() -> set[str]:
    return {
        email.strip().lower()
        for email in (settings.SYSTEM_ADMIN_EMAILS or "").replace(";", ",").split(",")
        if email.strip()
    }


def _should_be_system_admin(email: str) -> bool:
    return email.strip().lower() in _configured_admin_emails()


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        firm_name=(body.firm_name or body.org_name or "").strip(),
        password_hash=hash_password(body.password),
        is_system_admin=_should_be_system_admin(body.email),
        profile={},
    )
    db.add(user)
    await db.flush()

    # TODO(org): keep a per-user compatibility shell for legacy org_id FKs.
    await get_or_create_todo_org(db, user)

    await db.commit()
    await db.refresh(user)
    await delete_pattern("admin:v1:*")
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not user.is_active or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if _should_be_system_admin(user.email) and not user.is_system_admin:
        user.is_system_admin = True
        await db.commit()
        await db.refresh(user)
        await delete_pattern("admin:v1:*")

    access_token = create_access_token({"sub": str(user.id), "email": user.email})
    refresh_token = create_refresh_token(user.id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser):
    return current_user


@router.patch("/me/password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")

    current_user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"message": "密码已更新"}


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: UpdateMeRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="姓名不能为空")
        current_user.name = name

    if body.firm_name is not None:
        firm_name = body.firm_name.strip()
        if not firm_name:
            raise HTTPException(status_code=422, detail="公司/律所名称不能为空")
        current_user.firm_name = firm_name

    if body.phone is not None:
        profile = dict(current_user.profile or {})
        profile["phone"] = body.phone.strip()
        current_user.profile = profile

    await db.commit()
    await db.refresh(current_user)
    await delete_pattern("admin:v1:*")
    return current_user
