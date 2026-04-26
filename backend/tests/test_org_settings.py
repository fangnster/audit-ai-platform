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


async def _register_and_auth(client: AsyncClient) -> dict[str, str]:
    email = f"org-settings-{uuid.uuid4().hex}@example.com"
    password = "password123"
    await client.post("/api/v1/auth/register", json={
        "email": email,
        "name": "Org Settings Tester",
        "password": password,
        "password_confirm": password,
        "org_name": "Org Settings Law Group",
    })
    login = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": password,
    })
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_org_settings_do_not_return_api_key(client):
    headers = await _register_and_auth(client)

    update = await client.patch("/api/v1/orgs/me/settings", headers=headers, json={
        "llm_provider": "minimax",
        "llm_model": "MiniMax-M2.7",
        "llm_base_url": "https://api.minimaxi.com/v1",
        "api_key": "secret-test-key",
    })
    assert update.status_code == 200
    assert update.json()["settings"]["api_key_configured"] is True
    assert "api_key" not in update.json()["settings"]

    settings = await client.get("/api/v1/orgs/me/settings", headers=headers)
    assert settings.status_code == 200
    assert settings.json()["api_key_configured"] is True
    assert "api_key" not in settings.json()


@pytest.mark.asyncio
async def test_org_llm_generation_test_uses_saved_settings(client, monkeypatch):
    headers = await _register_and_auth(client)
    captured = {}

    async def fake_generate(self, prompt, system="", temperature=0.3, max_tokens=4096, org_settings=None, **kwargs):
        captured["prompt"] = prompt
        captured["system"] = system
        captured["temperature"] = temperature
        captured["max_tokens"] = max_tokens
        captured["org_settings"] = org_settings
        return "model-test-ok"

    monkeypatch.setattr(LLMService, "generate", fake_generate)

    await client.patch("/api/v1/orgs/me/settings", headers=headers, json={
        "llm_provider": "minimax",
        "llm_model": "MiniMax-M2.7",
        "llm_base_url": "https://api.minimaxi.com/v1",
        "api_key": "secret-test-key",
    })

    response = await client.post("/api/v1/orgs/me/settings/test-generation", headers=headers, json={})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["provider"] == "minimax"
    assert body["model"] == "MiniMax-M2.7"
    assert body["base_url"] == "https://api.minimaxi.com/v1"
    assert body["sample"] == "model-test-ok"
    assert captured["org_settings"]["api_key"] == "secret-test-key"
    assert captured["temperature"] == 0
    assert captured["max_tokens"] == 1024


@pytest.mark.asyncio
async def test_org_llm_generation_test_reports_model_errors(client, monkeypatch):
    headers = await _register_and_auth(client)

    async def fake_generate(self, prompt, system="", temperature=0.3, max_tokens=4096, org_settings=None, **kwargs):
        raise RuntimeError("LLM HTTP 400: unknown model 'bad-model'")

    monkeypatch.setattr(LLMService, "generate", fake_generate)

    await client.patch("/api/v1/orgs/me/settings", headers=headers, json={
        "llm_provider": "minimax",
        "llm_model": "bad-model",
        "llm_base_url": "https://api.minimaxi.com/v1",
        "api_key": "secret-test-key",
    })

    response = await client.post("/api/v1/orgs/me/settings/test-generation", headers=headers, json={})

    assert response.status_code == 502
    assert "LLM generation test failed" in response.json()["detail"]
    assert "unknown model" in response.json()["detail"]


@pytest.mark.asyncio
async def test_org_llm_generation_test_ignores_unsaved_request_body(client, monkeypatch):
    headers = await _register_and_auth(client)
    captured = {}

    async def fake_generate(self, prompt, system="", temperature=0.3, max_tokens=4096, org_settings=None, **kwargs):
        captured["org_settings"] = org_settings
        return "model-test-ok"

    monkeypatch.setattr(LLMService, "generate", fake_generate)

    await client.patch("/api/v1/orgs/me/settings", headers=headers, json={
        "llm_provider": "minimax",
        "llm_model": "MiniMax-M2.7",
        "llm_base_url": "https://api.minimaxi.com/v1",
        "api_key": "secret-test-key",
    })

    response = await client.post("/api/v1/orgs/me/settings/test-generation", headers=headers, json={
        "llm_provider": "other",
        "llm_model": "unsaved-model",
        "llm_base_url": "api.example.test/v1",
        "api_key": "unsaved-key",
    })

    assert response.status_code == 200
    assert captured["org_settings"]["llm_provider"] == "minimax"
    assert captured["org_settings"]["llm_model"] == "MiniMax-M2.7"
    assert captured["org_settings"]["llm_base_url"] == "https://api.minimaxi.com/v1"
    assert captured["org_settings"]["api_key"] == "secret-test-key"


@pytest.mark.asyncio
async def test_org_llm_generation_test_rejects_base_url_without_scheme(client):
    headers = await _register_and_auth(client)

    await client.patch("/api/v1/orgs/me/settings", headers=headers, json={
        "llm_provider": "minimax",
        "llm_model": "MiniMax-M2.7",
        "llm_base_url": "api.minimaxi.com/v1",
        "api_key": "secret-test-key",
    })

    response = await client.post("/api/v1/orgs/me/settings/test-generation", headers=headers, json={})

    assert response.status_code == 422
    assert "Base URL must start" in response.json()["detail"]
