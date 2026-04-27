import hashlib
import time
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.deps import CurrentUser, DB
from app.llm.provider import LLMService
from app.services.cache import get_json, set_json
from app.services.todo_org import get_or_create_todo_org

router = APIRouter()

TRANSLATION_CACHE_PREFIX = "translation:v1"
TRANSLATION_CACHE_TTL_SECONDS = 30 * 60
TRANSLATION_CACHE_MAX_ITEMS = 256
_translation_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()


class TranslateRequest(BaseModel):
    content: str
    source_lang: str = "zh"
    target_lang: str = "en"


def _translation_settings_fingerprint(org_settings: Optional[dict]) -> str:
    settings = org_settings or {}
    values = [
        str(settings.get("llm_provider") or ""),
        str(settings.get("llm_model") or ""),
        str(settings.get("llm_base_url") or ""),
    ]
    return "|".join(values)


def _translation_cache_key(
    *,
    user_id: str,
    content: str,
    source_lang: str,
    target_lang: str,
    org_settings: Optional[dict],
) -> str:
    payload = "\n".join([
        user_id,
        source_lang.strip().lower(),
        target_lang.strip().lower(),
        _translation_settings_fingerprint(org_settings),
        content,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_local_cached_translation(key: str) -> Optional[str]:
    cached = _translation_cache.get(key)
    if not cached:
        return None
    cached_at, translated = cached
    if time.monotonic() - cached_at > TRANSLATION_CACHE_TTL_SECONDS:
        _translation_cache.pop(key, None)
        return None
    _translation_cache.move_to_end(key)
    return translated


def _set_local_cached_translation(key: str, translated: str) -> None:
    _translation_cache[key] = (time.monotonic(), translated)
    _translation_cache.move_to_end(key)
    while len(_translation_cache) > TRANSLATION_CACHE_MAX_ITEMS:
        _translation_cache.popitem(last=False)


async def _get_cached_translation(key: str) -> Optional[str]:
    cached = await get_json(f"{TRANSLATION_CACHE_PREFIX}:{key}")
    if isinstance(cached, str):
        _set_local_cached_translation(key, cached)
        return cached
    return _get_local_cached_translation(key)


async def _set_cached_translation(key: str, translated: str) -> None:
    _set_local_cached_translation(key, translated)
    await set_json(f"{TRANSLATION_CACHE_PREFIX}:{key}", translated, ttl=TRANSLATION_CACHE_TTL_SECONDS)


@router.post("")
async def translate(body: TranslateRequest, current_user: CurrentUser, db: DB):
    """Translate text using the configured LLM."""
    content = body.content.strip()
    source_lang = body.source_lang.strip() or "zh"
    target_lang = body.target_lang.strip() or "en"
    if not content:
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if source_lang.lower() == target_lang.lower():
        return {"translated": content, "source_lang": source_lang, "target_lang": target_lang, "cached": True}

    # TODO(org): model settings live on a per-user compatibility shell for now.
    org = await get_or_create_todo_org(db, current_user)
    await db.commit()
    org_settings = (org.settings or {}) if org else None
    cache_key = _translation_cache_key(
        user_id=str(current_user.id),
        content=content,
        source_lang=source_lang,
        target_lang=target_lang,
        org_settings=org_settings,
    )
    cached = await _get_cached_translation(cache_key)
    if cached is not None:
        return {"translated": cached, "source_lang": source_lang, "target_lang": target_lang, "cached": True}

    try:
        translated = await LLMService().translate(
            content,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary=None,
            org_settings=org_settings,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Translation failed: {exc}") from exc

    await _set_cached_translation(cache_key, translated)
    return {"translated": translated, "source_lang": source_lang, "target_lang": target_lang, "cached": False}
