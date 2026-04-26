"""
Documents router — file upload, category filter, parse trigger.
"""
from __future__ import annotations

import uuid
import os
import re
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.deps import CurrentUser, DB, ensure_case_member
from app.models.document import Document, DocType, UploaderRole, ParseStatus
from app.models.organization import DocumentCategory
from app.config import settings
from app.services.cache import delete_pattern, get_json, set_json
from app.utils.timezone import local_display, local_iso, local_now

router = APIRouter()


def build_storage_path(org_id, case_id, uploader_role: str, category_name: str, filename: str) -> str:
    import uuid as _uuid
    safe = re.sub(r"[^\w.\-]", "_", filename)
    prefix = _uuid.uuid4().hex[:8]
    return f"org/{org_id}/case/{case_id}/{uploader_role}/{category_name}/{prefix}_{safe}"


def attachment_headers(filename: str) -> dict[str, str]:
    """Build an RFC 5987-compatible attachment header for non-ASCII filenames."""
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "download"
    encoded_name = quote(filename, safe="")
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"}


def local_storage_path(storage_path: str) -> str:
    return os.path.join("/tmp", "immigration_uploads", storage_path)


def legacy_local_storage_path(storage_path: str) -> str:
    return f"/tmp/{storage_path.replace('/', '_')}"


def storage_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.STORAGE_ENDPOINT_URL or None,
        aws_access_key_id=settings.STORAGE_ACCESS_KEY,
        aws_secret_access_key=settings.STORAGE_SECRET_KEY,
        region_name=settings.STORAGE_REGION or None,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_local_bucket_exists(s3) -> None:
    endpoint = settings.STORAGE_ENDPOINT_URL or ""
    if not any(host in endpoint for host in ("minio", "localhost", "127.0.0.1")):
        return
    try:
        s3.head_bucket(Bucket=settings.STORAGE_BUCKET_NAME)
    except Exception:
        s3.create_bucket(Bucket=settings.STORAGE_BUCKET_NAME)


def read_document_bytes(doc: Document) -> bytes:
    """Read the stored original document bytes from local fallback or object storage."""
    if (doc.file_size or 0) <= 0:
        raise FileNotFoundError("stored file is empty")

    local_errors: list[str] = []
    for path_builder in (local_storage_path, legacy_local_storage_path):
        local_path = path_builder(doc.storage_path)
        try:
            if not os.path.exists(local_path):
                continue
            with open(local_path, "rb") as f:
                content = f.read()
            if content:
                return content
            local_errors.append(f"{local_path}: empty")
        except Exception as exc:
            local_errors.append(f"{local_path}: {exc}")

    try:
        s3 = storage_client()
        obj = s3.get_object(Bucket=settings.STORAGE_BUCKET_NAME, Key=doc.storage_path)
        content = obj["Body"].read()
        if content:
            return content
        raise FileNotFoundError("stored object is empty")
    except Exception as exc:
        detail = "; ".join(local_errors) if local_errors else "no local fallback file"
        raise FileNotFoundError(f"file not found in storage ({detail}; object storage: {exc})") from exc


async def _invalidate_document_cache(case_id: uuid.UUID) -> None:
    await delete_pattern(f"documents:{case_id}:*")


async def _get_document_for_user(doc_id: uuid.UUID, current_user, db: DB) -> Document:
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    await ensure_case_member(db, doc.case_id, current_user.id)
    return doc


async def upload_to_storage(file: UploadFile, storage_path: str) -> int:
    """Upload file bytes to S3/R2/MinIO. Returns file size."""
    content = await file.read()
    try:
        s3 = storage_client()
        ensure_local_bucket_exists(s3)
        s3.put_object(
            Bucket=settings.STORAGE_BUCKET_NAME,
            Key=storage_path,
            Body=content,
            ContentType=file.content_type or "application/octet-stream",
        )
        return len(content)
    except Exception:
        # In dev, save locally as fallback
        local_path = local_storage_path(storage_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(content)
        return len(content)


class DocumentResponse(BaseModel):
    id: uuid.UUID
    filename: str
    doc_type: str
    uploader_role: str
    parse_status: str
    storage_path: str
    category_id: Optional[uuid.UUID]
    model_config = {"from_attributes": True}


@router.post("/cases/{case_id}/documents", status_code=201)
async def upload_document(
    case_id: uuid.UUID,
    file: UploadFile = File(...),
    doc_type: DocType = Form(...),
    category_id: Optional[uuid.UUID] = Form(None),
    current_user: CurrentUser = ...,
    db: DB = ...,
):
    """
    Upload a document to the case.
    Storage path: org/{org_id}/case/{case_id}/{role}/{category}/{file}
    Automatically triggers AI fact extraction (async Celery task).
    """
    from app.models.case import Case, CaseMember
    from app.models.organization import OrgMember

    # Get case + org
    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    await ensure_case_member(db, case_id, current_user.id)

    # Determine uploader role
    member_result = await db.execute(
        select(OrgMember).where(OrgMember.user_id == current_user.id, OrgMember.org_id == case.org_id)
    )
    member = member_result.scalar_one_or_none()
    uploader_role = UploaderRole.lawyer if member and member.role.value in ("firm_admin", "lead_lawyer", "associate") else UploaderRole.client

    # Get category name for path
    category_name = "other"
    if category_id:
        cat = await db.get(DocumentCategory, category_id)
        if cat:
            category_name = cat.name

    # Build storage path
    storage_path = build_storage_path(case.org_id, case_id, uploader_role.value, category_name, file.filename or "upload")

    # Save to object storage
    file_size = await upload_to_storage(file, storage_path)

    # Create document record
    doc = Document(
        case_id=case_id,
        category_id=category_id,
        filename=f"{uuid.uuid4().hex[:8]}_{file.filename}",
        original_filename=file.filename or "upload",
        doc_type=doc_type,
        storage_path=storage_path,
        file_size=file_size,
        mime_type=file.content_type or "application/octet-stream",
        uploader_id=current_user.id,
        uploader_role=uploader_role,
        parse_status=ParseStatus.pending,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    await _invalidate_document_cache(case_id)

    # No auto-parse — document stays as 'pending' until manually triggered
    parse_status = "pending"

    return {
        "id": str(doc.id),
        "filename": doc.original_filename,
        "doc_type": doc.doc_type,
        "uploader_role": doc.uploader_role,
        "parse_status": parse_status,
        "storage_path": doc.storage_path,
        "category_id": str(doc.category_id) if doc.category_id else None,
        "message": f"Upload successful. Parse status: {parse_status}.",
    }


@router.get("/cases/{case_id}/documents")
async def list_documents(
    case_id: uuid.UUID,
    category: Optional[str] = None,
    doc_type: Optional[str] = None,
    uploader_role: Optional[str] = None,
    show_deleted: bool = False,
    current_user: CurrentUser = ...,
    db: DB = ...,
):
    """List documents. Filterable by doc_type or category name."""
    await ensure_case_member(db, case_id, current_user.id)
    cache_key = (
        f"documents:{case_id}:{current_user.id}:{category or '-'}:{doc_type or '-'}:"
        f"{uploader_role or '-'}:{show_deleted}"
    )
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    query = select(Document).where(
        Document.case_id == case_id,
        Document.is_deleted == show_deleted,
    )

    if uploader_role:
        query = query.where(Document.uploader_role == uploader_role)

    # Filter by doc_type (primary filter used by frontend)
    if doc_type:
        query = query.where(Document.doc_type == doc_type)
    elif category:
        # Legacy: filter by DocumentCategory name
        cat_result = await db.execute(
            select(DocumentCategory).where(DocumentCategory.name == category)
        )
        cat = cat_result.scalar_one_or_none()
        if cat:
            query = query.where(Document.category_id == cat.id)

    result = await db.execute(query.order_by(Document.created_at.desc()))
    docs = result.scalars().all()

    payload = [
        {
            "id": str(d.id),
            "filename": d.original_filename,
            "doc_type": d.doc_type,
            "uploader_role": d.uploader_role,
            "parse_status": d.parse_status,
            "category_id": str(d.category_id) if d.category_id else None,
            "file_size": d.file_size,
            "created_at": local_iso(d.created_at),
            "updated_at": local_iso(d.updated_at or d.created_at),
            "is_deleted": d.is_deleted,
        }
        for d in docs
    ]
    await set_json(cache_key, payload)
    return payload

class ParseRequest(BaseModel):
    prompt: Optional[str] = None


@router.post("/{doc_id}/parse")
async def trigger_parse(doc_id: uuid.UUID, body: Optional[ParseRequest] = None, current_user: CurrentUser = ..., db: DB = ...):
    """Manually trigger AI parsing on a document with optional prompt guidance."""
    doc = await _get_document_for_user(doc_id, current_user, db)

    from app.models.fact import Fact, FactStatus
    from app.models.case import Case
    from app.models.organization import Organization
    from app.agents.fact_extractor import FactExtractionAgent, strip_think_tags
    from app.llm.provider import LLMService

    prompt = strip_think_tags(body.prompt) if body and body.prompt else None

    # Get case type
    case = await db.get(Case, doc.case_id)
    case_type = case.case_type.value if case and hasattr(case.case_type, 'value') else 'EB1A'
    doc_type_val = doc.doc_type.value if hasattr(doc.doc_type, 'value') else str(doc.doc_type)
    org = await db.get(Organization, case.org_id) if case else None
    org_settings = org.settings if org and org.settings else {}

    doc.parse_status = ParseStatus.parsing
    await db.commit()
    await _invalidate_document_cache(doc.case_id)

    temp_path = ""
    try:
        import tempfile

        content = read_document_bytes(doc)
        suffix = os.path.splitext(doc.original_filename or "")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = tmp.name
            tmp.write(content)

        agent = FactExtractionAgent(llm=LLMService.from_org_settings(org_settings))
        extracted = await agent.extract_facts(
            file_path=temp_path,
            mime_type=doc.mime_type or "",
            doc_type=doc_type_val,
            case_type=case_type,
            lawyer_guidance=prompt or "",
        )

        inserted = 0
        for f_data in extracted:
            structured = dict(f_data.get("structured_data") or {})
            structured.setdefault("document_name", doc.original_filename)
            if prompt:
                structured["parse_prompt"] = prompt
            fact = Fact(
                case_id=doc.case_id,
                source_document_id=doc.id,
                category=f_data.get("category", "other"),
                content=f_data.get("content", ""),
                structured_data=structured,
                confidence_score=float(f_data.get("confidence_score", 1.0)),
                status=FactStatus.extracted,
            )
            db.add(fact)
            inserted += 1

        doc.parse_status = ParseStatus.parsed
        doc.extracted_metadata = {
            "fact_count": inserted,
            "mode": "llm_sync_trigger",
            "prompt": prompt,
            "parsed_at": local_iso(local_now()),
        }
        await db.commit()
        await _invalidate_document_cache(doc.case_id)
        await delete_pattern(f"facts:{doc.case_id}:*")
        return {"doc_id": str(doc.id), "status": "parsed", "facts_extracted": inserted, "prompt_used": prompt}
    except Exception as e:
        doc.parse_status = ParseStatus.failed
        await db.commit()
        await _invalidate_document_cache(doc.case_id)
        await delete_pattern(f"facts:{doc.case_id}:*")
        raise HTTPException(status_code=502, detail=f"Document parsing failed: {e}") from e
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


# ── Download ────────────────────────────────

@router.get("/{doc_id}/download")
async def download_document(doc_id: uuid.UUID, current_user: CurrentUser = ..., db: DB = ...):
    """Download original uploaded file."""
    import io
    from starlette.responses import StreamingResponse

    doc = await _get_document_for_user(doc_id, current_user, db)

    filename = doc.original_filename.replace('"', "_")
    headers = attachment_headers(filename)
    try:
        content = read_document_bytes(doc)
    except FileNotFoundError as exc:
        if "empty" in str(exc).lower():
            raise HTTPException(410, "Stored file is empty. Please upload this document again.")
        raise HTTPException(404, "File not found in storage")
    return StreamingResponse(
        io.BytesIO(content),
        media_type=doc.mime_type,
        headers=headers,
    )


# ── Soft Delete / Restore / Trash ──────────

@router.delete("/{doc_id}")
async def soft_delete_document(doc_id: uuid.UUID, current_user: CurrentUser, db: DB):
    doc = await _get_document_for_user(doc_id, current_user, db)
    doc.is_deleted = True
    await db.commit()
    await _invalidate_document_cache(doc.case_id)
    return {"id": str(doc.id), "status": "deleted"}


@router.post("/{doc_id}/restore")
async def restore_document(doc_id: uuid.UUID, current_user: CurrentUser, db: DB):
    doc = await _get_document_for_user(doc_id, current_user, db)
    doc.is_deleted = False
    await db.commit()
    await _invalidate_document_cache(doc.case_id)
    return {"id": str(doc.id), "status": "restored"}


@router.delete("/{doc_id}/permanent")
async def permanent_delete_document(doc_id: uuid.UUID, current_user: CurrentUser, db: DB):
    doc = await _get_document_for_user(doc_id, current_user, db)
    if not doc.is_deleted:
        raise HTTPException(400, "Document must be in trash before permanent deletion")
    case_id = doc.case_id
    await db.delete(doc)
    await db.commit()
    await _invalidate_document_cache(case_id)
    return {"id": str(doc_id), "status": "permanently_deleted"}

@router.get("/{doc_id}/export-text")
async def export_document_text(doc_id: uuid.UUID, export_format: str = "txt", current_user: CurrentUser = ..., db: DB = ...):
    """Export parsed/extracted text content of a document as a downloadable file.
    Collects all facts extracted from this document and renders them."""
    import io
    from starlette.responses import StreamingResponse
    from app.models.fact import Fact

    doc = await _get_document_for_user(doc_id, current_user, db)

    # Get all facts extracted from this document
    result = await db.execute(
        select(Fact).where(
            Fact.source_document_id == doc_id,
            Fact.is_deleted == False,
        ).order_by(Fact.created_at)
    )
    facts = result.scalars().all()

    now = local_display()
    safe_name = doc.original_filename.replace('"', '_').replace('/', '_')[:50]

    # Build metadata section
    meta = doc.extracted_metadata or {}
    parse_prompt = meta.get("prompt", "")
    fact_count = len(facts)

    if export_format == "md":
        lines = [f"# 文档解析导出 — {doc.original_filename}\n"]
        lines.append(f"- **导出时间**：{now}")
        lines.append(f"- **创建时间**：{local_display(doc.created_at)}")
        lines.append(f"- **修改时间**：{local_display(doc.updated_at or doc.created_at)}")
        lines.append(f"- **文档类型**：{doc.doc_type}")
        lines.append(f"- **解析状态**：{doc.parse_status}")
        lines.append(f"- **提取事实数**：{fact_count}")
        if parse_prompt:
            lines.append(f"- **解析提示词**：{parse_prompt}")
        lines.append("\n---\n")
        if facts:
            for i, f in enumerate(facts, 1):
                lines.append(f"## 事实 {i} — [{f.category}]")
                lines.append(f"**状态**: {f.status}  |  **置信度**: {f.confidence_score:.0%}\n")
                lines.append(f"**创建时间**: {local_display(f.created_at)}  |  **修改时间**: {local_display(f.updated_at or f.created_at)}\n")
                lines.append(f"{f.content}\n")
        else:
            lines.append("暂无提取事实。\n")
        content = "\n".join(lines)
        buf = io.BytesIO(content.encode("utf-8"))
        return StreamingResponse(
            buf,
            media_type="text/markdown; charset=utf-8",
            headers=attachment_headers(f"{safe_name}_parsed.md"),
        )
    else:  # txt
        lines = [f"文档解析导出 — {doc.original_filename}"]
        lines.append(f"导出时间：{now}")
        lines.append(f"创建时间：{local_display(doc.created_at)}")
        lines.append(f"修改时间：{local_display(doc.updated_at or doc.created_at)}")
        lines.append(f"文档类型：{doc.doc_type}")
        lines.append(f"解析状态：{doc.parse_status}")
        lines.append(f"提取事实数：{fact_count}")
        if parse_prompt:
            lines.append(f"解析提示词：{parse_prompt}")
        lines.append("=" * 60)
        if facts:
            for i, f in enumerate(facts, 1):
                lines.append(f"\n事实 {i} [{f.category}]")
                lines.append(f"状态: {f.status}  |  置信度: {f.confidence_score:.0%}")
                lines.append(f"创建时间: {local_display(f.created_at)}  |  修改时间: {local_display(f.updated_at or f.created_at)}")
                lines.append("-" * 40)
                lines.append(f.content)
        else:
            lines.append("\n暂无提取事实。")
        content = "\n".join(lines)
        buf = io.BytesIO(content.encode("utf-8"))
        return StreamingResponse(
            buf,
            media_type="text/plain; charset=utf-8",
            headers=attachment_headers(f"{safe_name}_parsed.txt"),
        )


@router.get("/categories")
async def list_categories(org_id: Optional[uuid.UUID] = None, db: DB = ...):
    """Get available document categories (system + org-specific)."""
    from app.models.organization import DocumentCategory
    query = select(DocumentCategory).where(
        (DocumentCategory.org_id == None) |  # system presets
        (DocumentCategory.org_id == org_id if org_id else DocumentCategory.org_id == None)
    ).order_by(DocumentCategory.sort_order)
    result = await db.execute(query)
    cats = result.scalars().all()
    return [
        {"id": str(c.id), "name": c.name, "display_name": c.display_name,
         "icon": c.icon, "is_system": c.is_system}
        for c in cats
    ]


@router.get("/{doc_id}/versions")
async def get_versions(doc_id: uuid.UUID, current_user: CurrentUser, db: DB):
    from app.models.document import DocumentVersion
    await _get_document_for_user(doc_id, current_user, db)
    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version_number.desc())
    )
    versions = result.scalars().all()
    return [
        {"version": v.version_number, "editor_role": v.editor_role,
         "change_summary": v.change_summary, "created_at": local_iso(v.created_at)}
        for v in versions
    ]
