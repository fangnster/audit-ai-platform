import pytest

from app.routers import translation


@pytest.mark.asyncio
async def test_translation_cache_reads_redis_and_backfills_local(monkeypatch):
    translation._translation_cache.clear()

    async def fake_get_json(key):
        return "cached from redis"

    monkeypatch.setattr(translation, "get_json", fake_get_json)

    cached = await translation._get_cached_translation("cache-key")

    assert cached == "cached from redis"
    assert translation._get_local_cached_translation("cache-key") == "cached from redis"


@pytest.mark.asyncio
async def test_translation_cache_falls_back_to_local(monkeypatch):
    translation._translation_cache.clear()

    async def fake_get_json(key):
        return None

    monkeypatch.setattr(translation, "get_json", fake_get_json)
    translation._set_local_cached_translation("cache-key", "cached locally")

    cached = await translation._get_cached_translation("cache-key")

    assert cached == "cached locally"


@pytest.mark.asyncio
async def test_translation_cache_writes_redis_and_local(monkeypatch):
    translation._translation_cache.clear()
    calls = []

    async def fake_set_json(key, value, ttl=None):
        calls.append((key, value, ttl))

    monkeypatch.setattr(translation, "set_json", fake_set_json)

    await translation._set_cached_translation("cache-key", "translated")

    assert calls == [("translation:v1:cache-key", "translated", translation.TRANSLATION_CACHE_TTL_SECONDS)]
    assert translation._get_local_cached_translation("cache-key") == "translated"
