import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.agent_task import AgentTask, AgentTaskStatus, AgentTaskType
from app.workers import agent_tasks


@pytest.mark.asyncio
async def test_draft_generation_releases_stale_running_task(monkeypatch):
    await engine.dispose()
    dispatched = {"calls": []}

    def fake_delay(*args):
        dispatched["calls"].append(args)

    monkeypatch.setattr(agent_tasks.generate_drafts, "delay", fake_delay)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = f"draft-release-{uuid.uuid4().hex}@example.com"
            password = "password123"
            await client.post("/api/v1/auth/register", json={
                "email": email,
                "name": "Draft Release Tester",
                "password": password,
                "password_confirm": password,
                "org_name": "Draft Release Law Group",
            })
            login = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            case_res = await client.post("/api/v1/cases", headers=headers, json={
                "title": "Draft Release Case",
                "case_type": "EB1A",
                "client_email": "client@example.com",
            })
            case_res.raise_for_status()
            case_id = case_res.json()["id"]

            stale_at = datetime.now(timezone.utc) - timedelta(minutes=settings.AGENT_TASK_PROCESSING_TIMEOUT_MINUTES + 5)
            async with AsyncSessionLocal() as db:
                stale_task = AgentTask(
                    case_id=uuid.UUID(case_id),
                    task_type=AgentTaskType.draft_generate,
                    input_params={"case_id": case_id, "title": "Old draft", "prompt": "Old prompt"},
                    status=AgentTaskStatus.processing,
                    created_at=stale_at,
                    updated_at=stale_at,
                )
                db.add(stale_task)
                await db.commit()
                await db.refresh(stale_task)
                stale_task_id = str(stale_task.id)

            generate_res = await client.post(
                f"/api/v1/drafts/cases/{case_id}/generate",
                headers=headers,
                json={
                    "title": "Fresh draft",
                    "prompt": "Generate a short case summary.",
                    "strategy": "strongest_first",
                    "knowledge_ids": [],
                    "fact_ids": [],
                },
            )
            generate_res.raise_for_status()
            body = generate_res.json()

            assert body["status"] == "queued"
            assert body["agent_task_id"] != stale_task_id
            assert dispatched["calls"] == [(case_id, body["agent_task_id"])]

            tasks_res = await client.get(f"/api/v1/drafts/cases/{case_id}/agent-tasks", headers=headers)
            tasks_res.raise_for_status()
            tasks = tasks_res.json()
            stale_task = next(item for item in tasks if item["id"] == stale_task_id)
            new_task = next(item for item in tasks if item["id"] == body["agent_task_id"])
            assert stale_task["status"] == "failed"
            assert stale_task["output_result"]["error"] == "agent_task_timeout"
            assert new_task["status"] == "queued"
    finally:
        await engine.dispose()
