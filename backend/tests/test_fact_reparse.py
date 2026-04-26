import uuid
from types import SimpleNamespace

import pytest

from app.routers import documents, facts


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
