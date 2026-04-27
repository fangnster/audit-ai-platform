from __future__ import annotations

import json
import logging
from typing import Any
import asyncio

import redis
from redis import asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)
_async_clients: dict[tuple[str, int], aioredis.Redis] = {}
_sync_clients: dict[str, redis.Redis] = {}


def _enabled() -> bool:
    return bool(settings.CACHE_ENABLED and settings.REDIS_URL)


def _json_default(value: Any) -> str:
    return str(value)


def _async_client() -> aioredis.Redis:
    loop_id = id(asyncio.get_running_loop())
    key = (settings.REDIS_URL, loop_id)
    client = _async_clients.get(key)
    if client is None:
        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        _async_clients[key] = client
    return client


def _sync_client() -> redis.Redis:
    client = _sync_clients.get(settings.REDIS_URL)
    if client is None:
        client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        _sync_clients[settings.REDIS_URL] = client
    return client


async def close_cache_clients() -> None:
    for client in list(_async_clients.values()):
        try:
            await client.aclose()
        except Exception:
            pass
    _async_clients.clear()
    for client in list(_sync_clients.values()):
        try:
            client.close()
        except Exception:
            pass
    _sync_clients.clear()


async def get_json(key: str) -> Any | None:
    if not _enabled():
        return None
    try:
        raw = await _async_client().get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("cache_get_failed key=%s error=%s", key, exc)
        return None


async def set_json(key: str, value: Any, ttl: int | None = None) -> None:
    if not _enabled():
        return
    try:
        await _async_client().setex(
            key,
            ttl or settings.CACHE_TTL_SECONDS,
            json.dumps(value, ensure_ascii=False, default=_json_default),
        )
    except Exception as exc:
        logger.warning("cache_set_failed key=%s error=%s", key, exc)


async def delete_pattern(pattern: str) -> int:
    if not _enabled():
        return 0
    try:
        deleted = 0
        batch: list[str] = []
        async for key in _async_client().scan_iter(match=pattern, count=500):
            batch.append(key)
            if len(batch) >= 500:
                deleted += await _async_client().delete(*batch)
                batch.clear()
        if batch:
            deleted += await _async_client().delete(*batch)
        return deleted
    except Exception as exc:
        logger.warning("cache_delete_failed pattern=%s error=%s", pattern, exc)
        return 0


def delete_pattern_sync(pattern: str) -> int:
    if not _enabled():
        return 0
    try:
        deleted = 0
        batch: list[str] = []
        client = _sync_client()
        for key in client.scan_iter(match=pattern, count=500):
            batch.append(key)
            if len(batch) >= 500:
                deleted += client.delete(*batch)
                batch.clear()
        if batch:
            deleted += client.delete(*batch)
        return deleted
    except Exception as exc:
        logger.warning("cache_delete_sync_failed pattern=%s error=%s", pattern, exc)
        return 0
