import uuid
from datetime import timedelta
from typing import Optional, Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import verify_password, hash_password, create_access_token, create_refresh_token
from app.models.user import User
from app.models.organization import Organization, OrgMember, MemberRole
from app.deps import CurrentUser

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str = Field(min_length=8)
    password_confirm: str = Field(min_length=8)
    org_name: str

    @model_validator(mode="after")
    def validate_registration(self):
        if not self.org_name.strip():
            raise ValueError("请填写律所/公司名称")
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
    profile: dict

    model_config = {"from_attributes": True}


class UpdateMeRequest(BaseModel):
    name: Optional[str] = None
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


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        profile={},
    )
    db.add(user)
    await db.flush()

    # Auto-create organization for the user
    org_name = body.org_name.strip()
    slug = org_name.lower().replace(" ", "-").replace("　", "-")[:50] + f"-{uuid.uuid4().hex[:6]}"
    org = Organization(name=org_name, slug=slug)
    db.add(org)
    await db.flush()

    # Add user as firm admin
    org_member = OrgMember(org_id=org.id, user_id=user.id, role=MemberRole.firm_admin)
    db.add(org_member)

    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

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

    if body.phone is not None:
        profile = dict(current_user.profile or {})
        profile["phone"] = body.phone.strip()
        current_user.profile = profile

    await db.commit()
    await db.refresh(current_user)
    return current_user
