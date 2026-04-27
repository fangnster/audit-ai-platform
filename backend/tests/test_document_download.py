import pytest
import uuid
from datetime import datetime, timedelta, timezone
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.agents.fact_extractor import DocumentTextExtractionError, FactExtractionAgent
from app.main import app
from app.models.agent_task import AgentTask, AgentTaskStatus, AgentTaskType
from app.models.document import Document, ParseStatus
from app.routers import documents
from app.workers import document_tasks


def test_attachment_header_supports_chinese_filename():
    header = documents.attachment_headers("尊敬的黄嵋女士.docx")["Content-Disposition"]

    header.encode("latin-1")
    assert "filename=" in header
    assert "filename*=UTF-8''" in header


@pytest.mark.asyncio
async def test_upload_fallback_preserves_file_bytes(monkeypatch, tmp_path):
    class FakeUpload:
        content_type = "text/plain"

        async def read(self):
            return b"downloadable content"

    class BrokenStorage:
        def put_object(self, **kwargs):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(documents, "storage_client", lambda: BrokenStorage())
    monkeypatch.setattr(
        documents,
        "local_storage_path",
        lambda storage_path: str(tmp_path / storage_path.replace("/", "_")),
    )

    size = await documents.upload_to_storage(FakeUpload(), "org/case/lawyer/other/test.txt")

    saved = tmp_path / "org_case_lawyer_other_test.txt"
    assert size == len(b"downloadable content")
    assert saved.read_bytes() == b"downloadable content"


@pytest.mark.asyncio
async def test_uploaded_document_download_returns_original_bytes():
    await engine.dispose()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = f"download-test-{uuid.uuid4().hex}@example.com"
            password = "password123"
            await client.post("/api/v1/auth/register", json={
                "email": email,
                "name": "Download Tester",
                "password": password,
                "password_confirm": password,
                "org_name": "Download Test Law Group",
            })
            login = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            case_res = await client.post("/api/v1/cases", headers=headers, json={
                "title": "Download Case",
                "case_type": "EB1A",
                "client_email": "client@example.com",
            })
            case_res.raise_for_status()
            case_id = case_res.json()["id"]

            original = b"not empty document bytes"
            upload_res = await client.post(
                f"/api/v1/documents/cases/{case_id}/documents",
                headers=headers,
                data={"doc_type": "evidence"},
                files={"file": ("download.txt", original, "text/plain")},
            )
            upload_res.raise_for_status()
            doc_id = upload_res.json()["id"]

            list_res = await client.get(f"/api/v1/documents/cases/{case_id}/documents", headers=headers)
            list_res.raise_for_status()
            uploaded_doc = next(item for item in list_res.json() if item["id"] == doc_id)
            assert uploaded_doc["created_at"].endswith("+08:00")
            assert uploaded_doc["updated_at"].endswith("+08:00")

            download_res = await client.get(f"/api/v1/documents/{doc_id}/download", headers=headers)
            download_res.raise_for_status()

            assert download_res.content == original
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_document_type_settings_allow_original_contribution_and_custom_upload():
    await engine.dispose()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = f"doc-types-{uuid.uuid4().hex}@example.com"
            password = "password123"
            await client.post("/api/v1/auth/register", json={
                "email": email,
                "name": "Document Type Tester",
                "password": password,
                "password_confirm": password,
                "org_name": "Document Type Law Group",
            })
            login = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            types_res = await client.get("/api/v1/documents/types", headers=headers)
            types_res.raise_for_status()
            assert any(item["id"] == "original_contribution" for item in types_res.json()["items"])
            assert any(item["id"] == "resume" for item in types_res.json()["items"])

            update_res = await client.patch("/api/v1/documents/types", headers=headers, json={
                "items": [
                    {"id": "original_contribution", "label": "原创成果", "icon": "✨", "enabled": True, "builtin": True},
                    {"id": "custom_portfolio", "label": "作品集", "icon": "🧾", "enabled": True},
                ],
            })
            update_res.raise_for_status()
            returned_ids = {item["id"] for item in update_res.json()["items"]}
            assert {"original_contribution", "custom_portfolio"}.issubset(returned_ids)

            case_res = await client.post("/api/v1/cases", headers=headers, json={
                "title": "Custom Type Case",
                "case_type": "EB1A",
                "client_email": "client@example.com",
            })
            case_res.raise_for_status()
            case_id = case_res.json()["id"]

            for doc_type in ("original_contribution", "custom_portfolio"):
                upload_res = await client.post(
                    f"/api/v1/documents/cases/{case_id}/documents",
                    headers=headers,
                    data={"doc_type": doc_type},
                    files={"file": (f"{doc_type}.txt", b"source text", "text/plain")},
                )
                upload_res.raise_for_status()
                assert upload_res.json()["doc_type"] == doc_type

            list_res = await client.get(f"/api/v1/documents/cases/{case_id}/documents", headers=headers)
            list_res.raise_for_status()
            uploaded_types = {item["doc_type"] for item in list_res.json()}
            assert {"original_contribution", "custom_portfolio"}.issubset(uploaded_types)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fact_extractor_uses_parse_budget_and_original_contribution_guidance(tmp_path):
    class FakeParseLLM:
        def __init__(self):
            self.prompt = ""
            self.system = ""
            self.max_tokens = 0

        async def extract_json(self, prompt, system="", max_tokens=2048):
            self.prompt = prompt
            self.system = system
            self.max_tokens = max_tokens
            return """[
              {
                "category": "original_contribution",
                "content": "The work introduced an adopted technical contribution.",
                "structured_data": {"impact": "adopted by peers"},
                "confidence_score": 0.91
              }
            ]"""

    source = tmp_path / "long.txt"
    source.write_text("A" * 5000 + "\nIMPORTANT TAIL", encoding="utf-8")

    llm = FakeParseLLM()
    facts = await FactExtractionAgent(llm=llm).extract_facts(
        file_path=str(source),
        mime_type="text/plain",
        doc_type="original_contribution",
        case_type="EB1A",
        lawyer_guidance="G" * 5000,
        max_content_chars=1000,
    )

    assert facts[0]["category"] == "original_contribution"
    assert llm.max_tokens == settings.PARSE_MAX_OUTPUT_TOKENS
    assert "original contribution" in llm.prompt
    assert f"at most {settings.PARSE_MAX_FACTS}" in llm.prompt
    assert "IMPORTANT TAIL" in llm.prompt
    assert "G" * (settings.PARSE_MAX_LAWYER_GUIDANCE_CHARS + 1) not in llm.prompt


@pytest.mark.asyncio
async def test_fact_extractor_detects_resume_and_retries_empty_result(tmp_path):
    class FakeRetryLLM:
        def __init__(self):
            self.prompts = []
            self.max_tokens = []

        async def extract_json(self, prompt, system="", max_tokens=2048):
            self.prompts.append(prompt)
            self.max_tokens.append(max_tokens)
            if len(self.prompts) == 1:
                return "[]"
            return """[
              {
                "category": "education",
                "content": "The applicant earned a Ph.D. from Example University in 2012.",
                "structured_data": {"organization": "Example University", "date": "2012", "source": "Education"},
                "confidence_score": 0.9
              }
            ]"""

    source = tmp_path / "profile.txt"
    source.write_text(
        "Education: Ph.D., Example University, 2012\n"
        "Employment: Senior Researcher, Example Lab, 2015-2020\n",
        encoding="utf-8",
    )

    llm = FakeRetryLLM()
    agent = FactExtractionAgent(llm=llm)
    facts = await agent.extract_facts(
        file_path=str(source),
        mime_type="text/plain",
        doc_type="custom_profile",
        case_type="EB1A",
        document_name="CV - Applicant.pdf",
    )

    assert facts[0]["category"] == "education"
    assert len(llm.prompts) == 2
    assert llm.max_tokens == [settings.PARSE_RESUME_MAX_OUTPUT_TOKENS, settings.PARSE_RESUME_MAX_OUTPUT_TOKENS]
    assert "Document name: CV - Applicant.pdf" in llm.prompts[0]
    assert "Resume/CV parsing aid" in llm.prompts[0]
    assert "previous extraction returned no facts" in llm.prompts[1].lower()
    assert agent.last_diagnostics["resolved_doc_type"] == "resume"
    assert agent.last_diagnostics["fallback_retry_used"] is True
    assert agent.last_diagnostics["fact_count"] == 1


@pytest.mark.asyncio
async def test_fact_extractor_retries_low_yield_resume_result(tmp_path):
    class FakeLowYieldLLM:
        def __init__(self):
            self.prompts = []

        async def extract_json(self, prompt, system="", max_tokens=2048):
            self.prompts.append(prompt)
            if len(self.prompts) == 1:
                return """[
                  {
                    "category": "other",
                    "content": "The applicant has a professional resume.",
                    "structured_data": {"source": "Summary"},
                    "confidence_score": 0.7
                  }
                ]"""
            return """[
              {
                "category": "education",
                "content": "The applicant earned a Ph.D. from Example University in 2012.",
                "structured_data": {"organization": "Example University", "date": "2012", "source": "Education"},
                "confidence_score": 0.9
              },
              {
                "category": "employment",
                "content": "The applicant served as Senior Researcher at Example Lab from 2015 to 2020.",
                "structured_data": {"organization": "Example Lab", "date": "2015-2020", "source": "Employment"},
                "confidence_score": 0.9
              },
              {
                "category": "publication",
                "content": "The applicant authored a selected publication listed in the CV.",
                "structured_data": {"source": "Publications"},
                "confidence_score": 0.82
              }
            ]"""

    source = tmp_path / "resume.txt"
    source.write_text(
        (
            "Education\nPh.D., Example University, 2012\n"
            "Employment\nSenior Researcher, Example Lab, 2015-2020\n"
            "Publications\nExample Paper, Example Conference, 2019\n"
        ) * 4,
        encoding="utf-8",
    )

    llm = FakeLowYieldLLM()
    agent = FactExtractionAgent(llm=llm)
    facts = await agent.extract_facts(
        file_path=str(source),
        mime_type="text/plain",
        doc_type="resume",
        case_type="EB1A",
        document_name="resume.txt",
    )

    assert len(facts) == 3
    assert len(llm.prompts) == 2
    assert agent.last_diagnostics["fallback_reason"] == "low_yield_resume"


@pytest.mark.asyncio
async def test_fact_extractor_rejects_unreadable_text(tmp_path):
    class FakeLLM:
        async def extract_json(self, prompt, system="", max_tokens=2048):
            raise AssertionError("LLM should not be called when no text was extracted")

    source = tmp_path / "empty.txt"
    source.write_text("   ", encoding="utf-8")
    agent = FactExtractionAgent(llm=FakeLLM())

    with pytest.raises(DocumentTextExtractionError):
        await agent.extract_facts(
            file_path=str(source),
            mime_type="text/plain",
            doc_type="resume",
            case_type="EB1A",
            document_name="resume.txt",
        )

    assert agent.last_diagnostics["text_quality"] == "unreadable"


@pytest.mark.asyncio
async def test_document_parse_queues_background_task(monkeypatch):
    await engine.dispose()

    dispatched = {"calls": []}

    def fake_delay(*args):
        dispatched["calls"].append(args)

    monkeypatch.setattr(document_tasks.parse_document, "delay", fake_delay)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = f"parse-queue-{uuid.uuid4().hex}@example.com"
            password = "password123"
            await client.post("/api/v1/auth/register", json={
                "email": email,
                "name": "Parse Queue Tester",
                "password": password,
                "password_confirm": password,
                "org_name": "Parse Queue Law Group",
            })
            login = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            case_res = await client.post("/api/v1/cases", headers=headers, json={
                "title": "Parse Queue Case",
                "case_type": "EB1A",
                "client_email": "client@example.com",
            })
            case_res.raise_for_status()
            case_id = case_res.json()["id"]

            upload_res = await client.post(
                f"/api/v1/documents/cases/{case_id}/documents",
                headers=headers,
                data={"doc_type": "evidence"},
                files={"file": ("parse.txt", b"source text", "text/plain")},
            )
            upload_res.raise_for_status()
            doc_id = upload_res.json()["id"]

            stale_at = datetime.now(timezone.utc) - timedelta(minutes=settings.AGENT_TASK_PROCESSING_TIMEOUT_MINUTES + 5)
            async with AsyncSessionLocal() as db:
                stale_task = AgentTask(
                    case_id=uuid.UUID(case_id),
                    task_type=AgentTaskType.fact_extract,
                    input_params={"case_id": case_id, "document_id": doc_id, "document_name": "parse.txt"},
                    status=AgentTaskStatus.processing,
                    created_at=stale_at,
                    updated_at=stale_at,
                )
                db.add(stale_task)
                doc = await db.get(Document, uuid.UUID(doc_id))
                doc.parse_status = ParseStatus.parsing
                await db.commit()
                await db.refresh(stale_task)
                stale_task_id = str(stale_task.id)

            parse_res = await client.post(f"/api/v1/documents/{doc_id}/parse", headers=headers, json={})

            parse_res.raise_for_status()
            parse_body = parse_res.json()
            assert parse_body["status"] == "queued"
            assert parse_body["doc_id"] == doc_id
            assert parse_body["agent_task_id"]
            assert parse_body["agent_task_id"] != stale_task_id
            assert dispatched["calls"][0][0] == doc_id
            assert dispatched["calls"][0][-1] == parse_body["agent_task_id"]

            duplicate_res = await client.post(f"/api/v1/documents/{doc_id}/parse", headers=headers, json={})
            duplicate_res.raise_for_status()
            duplicate_body = duplicate_res.json()
            assert duplicate_body["agent_task_id"] == parse_body["agent_task_id"]
            assert "已有解析任务" in duplicate_body["message"]
            assert len(dispatched["calls"]) == 1

            list_res = await client.get(f"/api/v1/documents/cases/{case_id}/documents", headers=headers)
            list_res.raise_for_status()
            parsed_doc = next(item for item in list_res.json() if item["id"] == doc_id)
            assert parsed_doc["parse_status"] == "parsing"

            tasks_res = await client.get(f"/api/v1/drafts/cases/{case_id}/agent-tasks", headers=headers)
            tasks_res.raise_for_status()
            task = next(item for item in tasks_res.json() if item["id"] == parse_body["agent_task_id"])
            assert task["task_type"] == "fact_extract"
            assert task["status"] == "queued"
            assert task["input_params"]["document_id"] == doc_id
            assert task["summary"]["document_name"] == "parse.txt"
            assert task["human_context"]["document"]["name"] == "parse.txt"
            stale_task = next(item for item in tasks_res.json() if item["id"] == stale_task_id)
            assert stale_task["status"] == "failed"
            assert stale_task["output_result"]["error"] == "agent_task_timeout"
    finally:
        await engine.dispose()
