import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import engine
from app.llm.provider import LLMService
from app.main import app


@pytest_asyncio.fixture
async def client():
    await engine.dispose()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await engine.dispose()


async def register_and_login(client: AsyncClient):
    email = f"translation-{uuid.uuid4().hex}@example.com"
    password = "password123"
    register = await client.post("/api/v1/auth/register", json={
        "email": email,
        "name": "Translation User",
        "password": password,
        "password_confirm": password,
        "firm_name": "Translation Law Group",
    })
    assert register.status_code == 201

    login = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": password,
    })
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_translation_uses_cache_and_omits_original_payload(client, monkeypatch):
    headers = await register_and_login(client)
    calls = {"count": 0}

    async def fake_translate(self, content, source_lang, target_lang, glossary=None, org_settings=None):
        calls["count"] += 1
        return f"{target_lang}:{content}"

    monkeypatch.setattr(LLMService, "translate", fake_translate)

    payload = {"content": "需要翻译的法律事实", "source_lang": "zh", "target_lang": "en"}
    first = await client.post("/api/v1/translate", headers=headers, json=payload)
    second = await client.post("/api/v1/translate", headers=headers, json=payload)

    assert first.status_code == 200
    assert first.json()["translated"] == "en:需要翻译的法律事实"
    assert first.json()["cached"] is False
    assert "original" not in first.json()

    assert second.status_code == 200
    assert second.json()["translated"] == "en:需要翻译的法律事实"
    assert second.json()["cached"] is True
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_translation_returns_immediately_when_source_and_target_match(client, monkeypatch):
    headers = await register_and_login(client)
    calls = {"count": 0}

    async def fake_translate(self, content, source_lang, target_lang, glossary=None, org_settings=None):
        calls["count"] += 1
        return content

    monkeypatch.setattr(LLMService, "translate", fake_translate)

    response = await client.post(
        "/api/v1/translate",
        headers=headers,
        json={"content": "Already translated", "source_lang": "en", "target_lang": "en"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "translated": "Already translated",
        "source_lang": "en",
        "target_lang": "en",
        "cached": True,
    }
    assert calls["count"] == 0
