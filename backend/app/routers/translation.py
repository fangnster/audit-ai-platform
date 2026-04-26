from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from app.deps import CurrentUser, DB
from app.llm.provider import LLMService
from app.models.organization import Organization, OrgMember

router = APIRouter()

class TranslateRequest(BaseModel):
    content: str
    source_lang: str = "zh"
    target_lang: str = "en"

@router.post("")
async def translate(body: TranslateRequest, current_user: CurrentUser, db: DB):
    """Translate text using the configured LLM."""
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")

    result = await db.execute(
        select(Organization)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == current_user.id)
    )
    org = result.scalars().first()
    try:
        translated = await LLMService().translate(
            body.content,
            source_lang=body.source_lang,
            target_lang=body.target_lang,
            glossary=None,
            org_settings=(org.settings or {}) if org else None,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Translation failed: {exc}") from exc

    return {"original": body.content, "translated": translated, "source_lang": body.source_lang, "target_lang": body.target_lang}
