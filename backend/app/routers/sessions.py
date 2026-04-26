import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from app.models.draft import UserSession
from app.deps import CurrentUser, DB, ensure_case_member

router = APIRouter()

class SessionData(BaseModel):
    page_context: str = ""
    draft_state: dict = {}
    ui_state: dict = {}

@router.put("/{case_id}")
async def save_session(case_id: uuid.UUID, body: SessionData, current_user: CurrentUser, db: DB):
    await ensure_case_member(db, case_id, current_user.id)
    result = await db.execute(select(UserSession).where(UserSession.user_id == current_user.id, UserSession.case_id == case_id))
    session = result.scalar_one_or_none()
    if session:
        session.page_context = body.page_context
        session.draft_state = body.draft_state
        session.ui_state = body.ui_state
    else:
        session = UserSession(user_id=current_user.id, case_id=case_id, **body.model_dump())
        db.add(session)
    await db.commit()
    return {"saved": True}

@router.get("/{case_id}")
async def get_session(case_id: uuid.UUID, current_user: CurrentUser, db: DB):
    await ensure_case_member(db, case_id, current_user.id)
    result = await db.execute(select(UserSession).where(UserSession.user_id == current_user.id, UserSession.case_id == case_id))
    session = result.scalar_one_or_none()
    if not session:
        return None
    return {"page_context": session.page_context, "draft_state": session.draft_state, "ui_state": session.ui_state, "last_active_at": session.last_active_at}

@router.delete("/{case_id}", status_code=204)
async def clear_session(case_id: uuid.UUID, current_user: CurrentUser, db: DB):
    await ensure_case_member(db, case_id, current_user.id)
    result = await db.execute(select(UserSession).where(UserSession.user_id == current_user.id, UserSession.case_id == case_id))
    session = result.scalar_one_or_none()
    if session:
        await db.delete(session)
        await db.commit()
