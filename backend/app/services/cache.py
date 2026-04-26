from __future__ import annotations

import json
import logging
from typing import Any

import redis
from redis import asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return bool(settings.CACHE_ENABLED and settings.REDIS_URL)


def _json_default(value: Any) -> str:
    return str(value)


async def get_json(key: str) -> Any | None:
    if not _enabled():
        return None
    try:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            raw = await client.get(key)
        finally:
            await client.aclose()
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("cache_get_failed key=%s error=%s", key, exc)
        return None


async def set_json(key: str, value: Any, ttl: int | None = None) -> None:
    if not _enabled():
        return
    try:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await client.setex(
                key,
                ttl or settings.CACHE_TTL_SECONDS,
                json.dumps(value, ensure_ascii=False, default=_json_default),
            )
        finally:
            await client.aclose()
    except Exception as exc:
        logger.warning("cache_set_failed key=%s error=%s", key, exc)


async def delete_pattern(pattern: str) -> int:
    if not _enabled():
        return 0
    try:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        deleted = 0
        try:
            async for key in client.scan_iter(match=pattern, count=200):
                deleted += await client.delete(key)
        finally:
            await client.aclose()
        return deleted
    except Exception as exc:
        logger.warning("cache_delete_failed pattern=%s error=%s", pattern, exc)
        return 0


def delete_pattern_sync(pattern: str) -> int:
    if not _enabled():
        return 0
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        deleted = 0
        for key in client.scan_iter(match=pattern, count=200):
            deleted += client.delete(key)
        client.close()
        return deleted
    except Exception as exc:
        logger.warning("cache_delete_sync_failed pattern=%s error=%s", pattern, exc)
        return 0
