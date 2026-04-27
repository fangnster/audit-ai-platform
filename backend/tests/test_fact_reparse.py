import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.agent_task import AgentTask, AgentTaskStatus, AgentTaskType
from app.models.fact import Fact, FactStatus
from app.routers import documents, facts
from app.workers import agent_tasks


class FakeDb:
    def __init__(self, doc):
        self.doc = doc

    async def get(self, model, value):
        return self.doc


@pytest.mark.asyncio
async def test_source_document_text_reads_uploaded_file_bytes(monkeypatch, tmp_path):
    doc_id = uuid.uuid4()
    storage_path = "org/case/lawyer/evidence/source.txt"
    original_text = "Original source file text with corrected patent number US-123."
    source_path = tmp_path / "source.txt"
    source_path.write_bytes(original_text.encode("utf-8"))

    doc = SimpleNamespace(
        id=doc_id,
        original_filename="source.txt",
        storage_path=storage_path,
        file_size=source_path.stat().st_size,
        mime_type="text/plain",
    )
    fact = SimpleNamespace(
        source_document_id=doc_id,
        structured_data={"document_name": "source.txt"},
    )

    monkeypatch.setattr(documents, "local_storage_path", lambda value: str(source_path))
    monkeypatch.setattr(documents, "legacy_local_storage_path", lambda value: str(tmp_path / "missing.txt"))

    context = await facts._source_document_text(fact, FakeDb(doc))

    assert "corrected patent number US-123" in context.text
    assert context.document_name == "source.txt"
    assert context.diagnostics["source"] == "uploaded_file"
    assert context.diagnostics["source_text_available"] is True


@pytest.mark.asyncio
async def test_source_document_text_falls_back_to_fact_metadata(monkeypatch, tmp_path):
    doc_id = uuid.uuid4()
    doc = SimpleNamespace(
        id=doc_id,
        original_filename="missing.pdf",
        storage_path="org/case/lawyer/evidence/missing.pdf",
        file_size=120,
        mime_type="application/pdf",
    )
    fact = SimpleNamespace(
        source_document_id=doc_id,
        structured_data={
            "document_name": "missing.pdf",
            "quote": "Quoted source context preserved with the fact.",
            "source": "expert_letter.pdf",
        },
    )

    class BrokenStorage:
        def get_object(self, **kwargs):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(documents, "local_storage_path", lambda value: str(tmp_path / "missing-local.pdf"))
    monkeypatch.setattr(documents, "legacy_local_storage_path", lambda value: str(tmp_path / "missing-legacy.pdf"))
    monkeypatch.setattr(documents, "storage_client", lambda: BrokenStorage())

    context = await facts._source_document_text(fact, FakeDb(doc))

    assert "Quoted source context preserved with the fact." in context.text
    assert context.document_name == "missing.pdf"
    assert context.diagnostics["source"] == "fact_metadata"
    assert context.diagnostics["source_text_available"] is True
    assert "storage unavailable" in context.diagnostics["error"]


@pytest.mark.asyncio
async def test_fact_dispute_queues_reparse_agent_task(monkeypatch):
    await engine.dispose()
    dispatched = {"calls": []}

    def fake_delay(*args):
        dispatched["calls"].append(args)

    monkeypatch.setattr(agent_tasks.reparse_fact, "delay", fake_delay)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = f"fact-reparse-{uuid.uuid4().hex}@example.com"
            password = "password123"
            await client.post("/api/v1/auth/register", json={
                "email": email,
                "name": "Fact Reparse Tester",
                "password": password,
                "password_confirm": password,
                "org_name": "Fact Reparse Law Group",
            })
            login = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            case_res = await client.post("/api/v1/cases", headers=headers, json={
                "title": "Fact Reparse Case",
                "case_type": "EB1A",
                "client_email": "client@example.com",
            })
            case_res.raise_for_status()
            case_id = uuid.UUID(case_res.json()["id"])

            async with AsyncSessionLocal() as db:
                fact = Fact(
                    case_id=case_id,
                    category="resume",
                    content="Original resume fact about a patent.",
                    structured_data={"document_name": "resume.pdf"},
                    confidence_score=0.88,
                    status=FactStatus.extracted,
                )
                db.add(fact)
                await db.commit()
                await db.refresh(fact)
                fact_id = str(fact.id)

                stale_at = datetime.now(timezone.utc) - timedelta(minutes=settings.AGENT_TASK_PROCESSING_TIMEOUT_MINUTES + 5)
                stale_task = AgentTask(
                    case_id=case_id,
                    task_type=AgentTaskType.fact_reparse,
                    input_params={"case_id": str(case_id), "fact_id": fact_id, "fact_category": "resume"},
                    status=AgentTaskStatus.processing,
                    created_at=stale_at,
                    updated_at=stale_at,
                )
                db.add(stale_task)
                await db.commit()
                await db.refresh(stale_task)
                stale_task_id = str(stale_task.id)

            res = await client.post(
                f"/api/v1/facts/{fact_id}/dispute",
                headers=headers,
                json={"comment": "请保留专利编号和授权日期", "knowledge_ids": []},
            )
            res.raise_for_status()
            body = res.json()

            assert body["status"] == "queued"
            assert body["agent_task_id"]
            assert body["agent_task_id"] != stale_task_id
            assert dispatched["calls"][0] == (str(case_id), fact_id, body["agent_task_id"])

            duplicate_res = await client.post(
                f"/api/v1/facts/{fact_id}/dispute",
                headers=headers,
                json={"comment": "再次重解析同一事实", "knowledge_ids": []},
            )
            duplicate_res.raise_for_status()
            duplicate_body = duplicate_res.json()
            assert duplicate_body["agent_task_id"] == body["agent_task_id"]
            assert "已有重解析任务" in duplicate_body["message"]
            assert len(dispatched["calls"]) == 1

            list_res = await client.get(f"/api/v1/facts/cases/{case_id}/facts", headers=headers)
            list_res.raise_for_status()
            queued_fact = next(item for item in list_res.json() if item["id"] == fact_id)
            assert queued_fact["status"] == "disputed"
            assert queued_fact["structured_data"]["dispute_comment"] == "请保留专利编号和授权日期"

            tasks_res = await client.get(f"/api/v1/drafts/cases/{case_id}/agent-tasks", headers=headers)
            tasks_res.raise_for_status()
            task = next(item for item in tasks_res.json() if item["id"] == body["agent_task_id"])
            assert task["task_type"] == "fact_reparse"
            assert task["status"] == "queued"
            assert task["input_params"]["fact_id"] == fact_id
            assert task["summary"]["fact_category"] == "resume"
            assert "Original resume fact" in task["human_context"]["fact"]["title"]
            stale_task = next(item for item in tasks_res.json() if item["id"] == stale_task_id)
            assert stale_task["status"] == "failed"
            assert stale_task["output_result"]["error"] == "agent_task_timeout"
    finally:
        await engine.dispose()
