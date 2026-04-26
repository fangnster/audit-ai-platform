import pytest
import uuid
from httpx import ASGITransport, AsyncClient

from app.database import engine
from app.agents.fact_extractor import FactExtractionAgent
from app.main import app
from app.routers import documents


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
async def test_document_parse_reports_llm_failure(monkeypatch):
    await engine.dispose()

    async def fail_extract(*args, **kwargs):
        raise RuntimeError("unknown model")

    monkeypatch.setattr(FactExtractionAgent, "extract_facts", fail_extract)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            email = f"parse-fail-{uuid.uuid4().hex}@example.com"
            password = "password123"
            await client.post("/api/v1/auth/register", json={
                "email": email,
                "name": "Parse Failure Tester",
                "password": password,
                "password_confirm": password,
                "org_name": "Parse Failure Law Group",
            })
            login = await client.post("/api/v1/auth/login", data={"username": email, "password": password})
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

            case_res = await client.post("/api/v1/cases", headers=headers, json={
                "title": "Parse Failure Case",
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

            parse_res = await client.post(f"/api/v1/documents/{doc_id}/parse", headers=headers, json={})

            assert parse_res.status_code == 502
            assert "Document parsing failed" in parse_res.json()["detail"]

            list_res = await client.get(f"/api/v1/documents/cases/{case_id}/documents", headers=headers)
            list_res.raise_for_status()
            parsed_doc = next(item for item in list_res.json() if item["id"] == doc_id)
            assert parsed_doc["parse_status"] == "failed"
    finally:
        await engine.dispose()
