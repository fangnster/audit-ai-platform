"""
Documents router — file upload, category filter, parse trigger.
"""
from __future__ import annotations

import uuid
import os
import re
import logging
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, delete as sa_delete, func, select
from sqlalchemy.orm import Session

from app.deps import CurrentUser, DB, ensure_case_member
from app.database import sync_database_url
from app.models.document import Document, DocumentBlob, UploaderRole, ParseStatus
from app.models.organization import DocumentCategory
from app.config import settings
from app.services.agent_tasks import release_stale_agent_tasks
from app.services.cache import delete_pattern, get_json, set_json
from app.utils.timezone import local_display, local_iso, local_now

router = APIRouter()
logger = logging.getLogger(__name__)


BUILTIN_DOCUMENT_TYPES = [
    {"id": "evidence", "label": "证据材料", "icon": "📄", "enabled": True, "builtin": True},
    {"id": "award", "label": "获奖证明", "icon": "🏆", "enabled": True, "builtin": True},
    {"id": "original_contribution", "label": "原创成果", "icon": "✨", "enabled": True, "builtin": True},
    {"id": "patent", "label": "专利", "icon": "💡", "enabled": True, "builtin": True},
    {"id": "publication", "label": "学术发表", "icon": "📝", "enabled": True, "builtin": True},
    {"id": "citation", "label": "引用数据", "icon": "📊", "enabled": True, "builtin": True},
    {"id": "employment", "label": "雇佣证明", "icon": "💼", "enabled": True, "builtin": True},
    {"id": "media", "label": "媒体报道", "icon": "📰", "enabled": True, "builtin": True},
    {"id": "membership", "label": "专业组织", "icon": "🏛️", "enabled": True, "builtin": True},
    {"id": "resume", "label": "个人简历", "icon": "👤", "enabled": True, "builtin": True},
    {"id": "reference_letter", "label": "推荐信", "icon": "✉️", "enabled": True, "builtin": True},
    {"id": "petition_letter", "label": "申请信", "icon": "📋", "enabled": True, "builtin": True},
    {"id": "rfi", "label": "RFI 回复", "icon": "📮", "enabled": True, "builtin": True},
    {"id": "other", "label": "其他", "icon": "📁", "enabled": True, "builtin": True},
]
BUILTIN_DOCUMENT_TYPE_IDS = {item["id"] for item in BUILTIN_DOCUMENT_TYPES}


class DocumentTypeItem(BaseModel):
    id: str
    label: str
    icon: str = "📄"
    enabled: bool = True
    builtin: bool = False


class DocumentTypeSettingsRequest(BaseModel):
    items: list[DocumentTypeItem]


def _normalize_doc_type_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", (value or "").strip().lower()).strip("_")
    if not normalized:
        raise HTTPException(400, "Document type id cannot be empty")
    if len(normalized) > 60:
        normalized = normalized[:60].rstrip("_")
    return normalized


def _normalize_doc_type_item(item: dict, *, builtin: bool = False) -> dict:
    item_id = _normalize_doc_type_id(str(item.get("id") or ""))
    label = str(item.get("label") or item_id).strip()[:40] or item_id
    icon = str(item.get("icon") or "📄").strip()[:8] or "📄"
    return {
        "id": item_id,
        "label": label,
        "icon": icon,
        "enabled": bool(item.get("enabled", True)),
        "builtin": builtin or item_id in BUILTIN_DOCUMENT_TYPE_IDS,
    }


def _document_types_for_user(user) -> list[dict]:
    defaults = {item["id"]: dict(item) for item in BUILTIN_DOCUMENT_TYPES}
    profile = dict(getattr(user, "profile", None) or {})
    stored = ((profile.get("document_type_settings") or {}).get("items") or [])
    ordered_ids: list[str] = []

    for raw in stored:
        if not isinstance(raw, dict):
            continue
        try:
            normalized = _normalize_doc_type_item(raw)
        except HTTPException:
            continue
        defaults[normalized["id"]] = normalized
        ordered_ids.append(normalized["id"])

    ordered: list[dict] = []
    seen: set[str] = set()
    for item_id in ordered_ids:
        if item_id in defaults and item_id not in seen:
            ordered.append(defaults[item_id])
            seen.add(item_id)
    for item in BUILTIN_DOCUMENT_TYPES:
        if item["id"] not in seen:
            ordered.append(defaults[item["id"]])
            seen.add(item["id"])
    for item_id, item in defaults.items():
        if item_id not in seen:
            ordered.append(item)
    return ordered


def _validate_document_type_for_user(doc_type: str, user) -> str:
    normalized = _normalize_doc_type_id(doc_type)
    allowed = {item["id"] for item in _document_types_for_user(user) if item.get("enabled")}
    if normalized not in allowed:
        raise HTTPException(400, "Invalid or disabled document type")
    return normalized


def _safe_storage_segment(value: str, fallback: str) -> str:
    raw = os.path.basename(str(value or "").replace("\x00", ""))
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    return (safe or fallback)[:120]


def _safe_storage_filename(filename: str) -> str:
    raw_name = os.path.basename(str(filename or "upload").replace("\x00", "")) or "upload"
    stem, ext = os.path.splitext(raw_name)
    safe_stem = _safe_storage_segment(stem, "upload")
    safe_ext = re.sub(r"[^A-Za-z0-9.]+", "", ext)[:20]
    if safe_ext == ".":
        safe_ext = ""
    return f"{safe_stem}{safe_ext}"[:180] or "upload"


def build_storage_path(org_id, case_id, uploader_role: str, category_name: str, filename: str) -> str:
    import uuid as _uuid
    safe_role = _safe_storage_segment(uploader_role, "role")
    safe_category = _safe_storage_segment(category_name, "category")
    safe = _safe_storage_filename(filename)
    prefix = _uuid.uuid4().hex[:8]
    return f"org/{org_id}/case/{case_id}/{safe_role}/{safe_category}/{prefix}_{safe}"


def attachment_headers(filename: str) -> dict[str, str]:
    """Build an RFC 5987-compatible attachment header for non-ASCII filenames."""
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "download"
    encoded_name = quote(filename, safe="")
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"}


def _enum_text(value) -> str:
    return str(value.value if hasattr(value, "value") else value)


def _document_type_label_for_user(doc_type: str, user) -> str:
    type_id = str(doc_type or "")
    for item in _document_types_for_user(user):
        if item.get("id") == type_id:
            return str(item.get("label") or type_id)
    return type_id


def _short_trace_text(value, limit: int = 500) -> str:
    text = str(value or "").strip().replace("\r\n", "\n")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"...（已截断 {len(text) - limit} 字）"


def _fact_trace_pairs(fact, *, document_name: str, document_type: str) -> list[tuple[str, str]]:
    structured = dict(fact.structured_data or {})
    pairs: list[tuple[str, str]] = [
        ("来源文件", document_name),
        ("上传文件类型", document_type),
    ]
    for label, key in (
        ("页码/位置", "page"),
        ("原文摘录", "quote"),
        ("原始来源说明", "source"),
        ("标题/项目", "title"),
        ("日期", "date"),
        ("机构/组织", "organization"),
    ):
        value = structured.get(key)
        if value is not None and str(value).strip():
            pairs.append((label, _short_trace_text(value)))
    return pairs


def local_storage_path(storage_path: str) -> str:
    return os.path.join("/tmp", "immigration_uploads", storage_path)


def legacy_local_storage_path(storage_path: str) -> str:
    return f"/tmp/{storage_path.replace('/', '_')}"


async def _save_document_blob(db, storage_path: str, content: bytes, mime_type: str | None) -> None:
    existing = await db.get(DocumentBlob, storage_path)
    if existing:
        existing.content = content
        existing.file_size = len(content)
        existing.mime_type = mime_type
        return
    db.add(DocumentBlob(
        storage_path=storage_path,
        content=content,
        file_size=len(content),
        mime_type=mime_type,
    ))


def _read_document_blob(storage_path: str) -> tuple[bytes | None, str | None]:
    engine = create_engine(sync_database_url(), pool_pre_ping=True)
    try:
        with Session(engine) as session:
            blob = session.get(DocumentBlob, storage_path)
            if blob and blob.content:
                return bytes(blob.content), None
            return None, None
    except Exception as exc:
        return None, str(exc)
    finally:
        engine.dispose()


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


def _is_local_storage_endpoint(endpoint: str | None = None) -> bool:
    endpoint = settings.STORAGE_ENDPOINT_URL if endpoint is None else endpoint
    if not endpoint:
        return True
    lowered = endpoint.lower()
    return any(host in lowered for host in ("minio", "localhost", "127.0.0.1", "::1"))


def _remote_object_storage_required() -> bool:
    return bool(
        settings.STORAGE_ENDPOINT_URL
        and settings.STORAGE_ACCESS_KEY
        and settings.STORAGE_SECRET_KEY
        and not _is_local_storage_endpoint()
    )


def storage_key_candidates(storage_path: str) -> list[str]:
    key = str(storage_path or "")
    candidates = [key]
    if key and not key.isascii():
        encoded = quote(key, safe="/")
        if encoded not in candidates:
            candidates.append(encoded)
    return candidates


def ensure_local_bucket_exists(s3) -> None:
    endpoint = settings.STORAGE_ENDPOINT_URL or ""
    if not endpoint or not _is_local_storage_endpoint(endpoint):
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

    db_content, db_error = _read_document_blob(doc.storage_path)
    if db_content:
        return db_content

    object_errors: list[str] = []
    try:
        s3 = storage_client()
    except Exception as exc:
        detail = "; ".join(local_errors) if local_errors else "no local fallback file"
        raise FileNotFoundError(f"file not found in storage ({detail}; object storage: {exc})") from exc

    for key in storage_key_candidates(doc.storage_path):
        try:
            obj = s3.get_object(Bucket=settings.STORAGE_BUCKET_NAME, Key=key)
            content = obj["Body"].read()
            if content:
                return content
            object_errors.append(f"{key}: empty")
        except Exception as exc:
            object_errors.append(f"{key}: {exc}")

    if db_error:
        local_errors.append(f"database fallback: {db_error}")
    detail = "; ".join(local_errors) if local_errors else "no local fallback file"
    object_detail = "; ".join(object_errors) if object_errors else "not attempted"
    raise FileNotFoundError(f"file not found in storage ({detail}; object storage: {object_detail})")


async def _invalidate_document_cache(case_id: uuid.UUID) -> None:
    await delete_pattern(f"documents:{case_id}:*")
    await delete_pattern(f"agent-tasks:{case_id}:*")
    await delete_pattern("admin:v1:*")


async def _get_document_for_user(doc_id: uuid.UUID, current_user, db: DB) -> Document:
    doc = await db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    await ensure_case_member(db, doc.case_id, current_user.id)
    return doc


async def upload_to_storage(file: UploadFile, storage_path: str, db=None) -> int:
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
    except Exception as exc:
        if _remote_object_storage_required():
            logger.warning(
                "object_storage_upload_failed storage_path=%s size=%s error=%s",
                storage_path,
                len(content),
                str(exc)[:500],
            )
            if db is not None:
                max_bytes = int(settings.DOCUMENT_DB_FALLBACK_MAX_BYTES or 0)
                if max_bytes > 0 and len(content) > max_bytes:
                    raise RuntimeError(
                        "object storage upload failed and file exceeds database fallback limit"
                    ) from exc
                await _save_document_blob(db, storage_path, content, file.content_type or "application/octet-stream")
                logger.warning(
                    "document_saved_to_database_fallback storage_path=%s size=%s",
                    storage_path,
                    len(content),
                )
                return len(content)
            raise RuntimeError(f"object storage upload failed: {exc}") from exc
        # In dev, save locally as fallback.
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


@router.get("/types")
async def list_document_types(current_user: CurrentUser):
    return {"items": _document_types_for_user(current_user)}


@router.patch("/types")
async def update_document_types(body: DocumentTypeSettingsRequest, current_user: CurrentUser, db: DB):
    if len(body.items) > 40:
        raise HTTPException(400, "Too many document types")

    normalized: list[dict] = []
    seen: set[str] = set()
    for item in body.items:
        normalized_item = _normalize_doc_type_item(item.model_dump())
        if normalized_item["id"] in seen:
            continue
        seen.add(normalized_item["id"])
        normalized.append(normalized_item)

    if not any(item["enabled"] for item in normalized):
        raise HTTPException(400, "At least one document type must be enabled")

    profile = dict(current_user.profile or {})
    profile["document_type_settings"] = {"items": normalized}
    current_user.profile = profile
    await db.commit()
    await db.refresh(current_user)
    return {"items": _document_types_for_user(current_user)}


@router.post("/cases/{case_id}/documents", status_code=201)
async def upload_document(
    case_id: uuid.UUID,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    category_id: Optional[uuid.UUID] = Form(None),
    current_user: CurrentUser = ...,
    db: DB = ...,
):
    """
    Upload a document to the case.
    Storage path still contains the legacy org_id FK shell.
    """
    from app.models.case import Case

    case = await db.get(Case, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    await ensure_case_member(db, case_id, current_user.id)

    # TODO(org): do not infer business role from organization membership.
    uploader_role = UploaderRole.lawyer
    doc_type_value = _validate_document_type_for_user(doc_type, current_user)

    # Get category name for path
    category_name = "other"
    if category_id:
        cat = await db.get(DocumentCategory, category_id)
        if cat:
            category_name = cat.name

    # Build storage path
    storage_path = build_storage_path(case.org_id, case_id, uploader_role.value, category_name, file.filename or "upload")

    # Save to object storage
    try:
        file_size = await upload_to_storage(file, storage_path, db=db)
    except RuntimeError as exc:
        raise HTTPException(503, "文件上传到对象存储失败，请稍后重试或联系管理员。") from exc

    # Create document record
    doc = Document(
        case_id=case_id,
        category_id=category_id,
        filename=f"{uuid.uuid4().hex[:8]}_{file.filename}",
        original_filename=file.filename or "upload",
        doc_type=doc_type_value,
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
        "doc_type": str(doc.doc_type),
        "uploader_role": str(doc.uploader_role.value if hasattr(doc.uploader_role, "value") else doc.uploader_role),
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
        query = query.where(Document.doc_type == _normalize_doc_type_id(doc_type))
    elif category:
        # Legacy: filter by DocumentCategory name
        cat_result = await db.execute(
            select(DocumentCategory).where(DocumentCategory.name == category)
        )
        cat = cat_result.scalar_one_or_none()
        if cat:
            query = query.where(Document.category_id == cat.id)

    display_time = func.coalesce(Document.updated_at, Document.created_at)
    result = await db.execute(query.order_by(display_time.desc(), Document.created_at.desc()))
    docs = result.scalars().all()

    payload = [
        {
            "id": str(d.id),
            "filename": d.original_filename,
            "doc_type": str(d.doc_type),
            "uploader_role": str(d.uploader_role.value if hasattr(d.uploader_role, "value") else d.uploader_role),
            "parse_status": str(d.parse_status.value if hasattr(d.parse_status, "value") else d.parse_status),
            "category_id": str(d.category_id) if d.category_id else None,
            "file_size": d.file_size,
            "extracted_metadata": d.extracted_metadata or {},
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
    """Queue AI parsing on a document with optional prompt guidance."""
    doc = await _get_document_for_user(doc_id, current_user, db)
    locked_doc_result = await db.execute(
        select(Document)
        .where(Document.id == doc.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    doc = locked_doc_result.scalar_one()

    from app.models.case import Case
    from app.models.organization import Organization
    from app.models.agent_task import AgentTask, AgentTaskStatus, AgentTaskType
    from app.agents.fact_extractor import strip_think_tags

    prompt = strip_think_tags(body.prompt) if body and body.prompt else None

    case = await db.get(Case, doc.case_id)
    case_type = case.case_type.value if case and hasattr(case.case_type, 'value') else 'EB1A'
    doc_type_val = doc.doc_type.value if hasattr(doc.doc_type, 'value') else str(doc.doc_type)
    org = await db.get(Organization, case.org_id) if case else None
    org_settings = org.settings if org and org.settings else {}
    await release_stale_agent_tasks(
        db,
        case_id=doc.case_id,
        task_types=[AgentTaskType.fact_extract],
        input_key="document_id",
        input_value=str(doc.id),
        commit=False,
    )

    running_result = await db.execute(
        select(AgentTask)
        .where(
            AgentTask.case_id == doc.case_id,
            AgentTask.task_type == AgentTaskType.fact_extract,
            AgentTask.status.in_([AgentTaskStatus.queued, AgentTaskStatus.processing]),
            AgentTask.input_params.op("->>")("document_id") == str(doc.id),
        )
        .order_by(AgentTask.created_at.desc())
        .limit(1)
    )
    running_task = running_result.scalar_one_or_none()
    if running_task:
        return {
            "doc_id": str(doc.id),
            "agent_task_id": str(running_task.id),
            "already_running": True,
            "status": str(running_task.status.value if hasattr(running_task.status, "value") else running_task.status),
            "message": "该文件已有解析任务在后台处理中，请稍候查看 Agent 运行记录。",
        }

    doc.parse_status = ParseStatus.parsing
    doc.extracted_metadata = {
        **(doc.extracted_metadata or {}),
        "mode": "llm_background_trigger",
        "prompt": prompt,
        "queued_at": local_iso(local_now()),
    }
    agent_task = AgentTask(
        case_id=doc.case_id,
        task_type=AgentTaskType.fact_extract,
        input_params={
            "case_id": str(doc.case_id),
            "document_id": str(doc.id),
            "document_name": doc.original_filename or doc.filename,
            "doc_type": doc_type_val,
            "case_type": case_type,
            "prompt": prompt or "",
            "prompt_chars": len(prompt or ""),
            "mime_type": doc.mime_type or "",
        },
        status=AgentTaskStatus.queued,
        priority=2,
        llm_model=org_settings.get("llm_model") or settings.LLM_MODEL,
    )
    db.add(agent_task)
    await db.commit()
    await db.refresh(agent_task)
    await _invalidate_document_cache(doc.case_id)

    try:
        from app.workers.document_tasks import parse_document as celery_task

        celery_task.delay(
            str(doc.id),
            "",
            doc.mime_type or "",
            doc_type_val,
            case_type,
            str(doc.case_id),
            prompt or "",
            str(agent_task.id),
        )
    except Exception as e:
        return {
            "doc_id": str(doc.id),
            "agent_task_id": str(agent_task.id),
            "status": "queued",
            "message": f"解析任务已加入后台队列。Celery 暂未确认接收：{str(e)[:80]}",
        }

    return {
        "doc_id": str(doc.id),
        "agent_task_id": str(agent_task.id),
        "status": "queued",
        "message": "解析任务已在后台启动，可在 Agent 运行记录查看进度和结果。",
    }


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
    await db.execute(sa_delete(DocumentBlob).where(DocumentBlob.storage_path == doc.storage_path))
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
    doc_type_label = _document_type_label_for_user(str(doc.doc_type), current_user)

    # Build metadata section
    meta = doc.extracted_metadata or {}
    parse_prompt = meta.get("prompt", "")
    fact_count = len(facts)

    if export_format == "md":
        lines = [f"# 文档解析导出 — {doc.original_filename}\n"]
        lines.append(f"- **导出时间**：{now}")
        lines.append(f"- **创建时间**：{local_display(doc.created_at)}")
        lines.append(f"- **修改时间**：{local_display(doc.updated_at or doc.created_at)}")
        lines.append(f"- **原始文件名**：{doc.original_filename}")
        lines.append(f"- **上传文件类型**：{doc_type_label}")
        lines.append(f"- **解析状态**：{_enum_text(doc.parse_status)}")
        lines.append(f"- **提取事实数**：{fact_count}")
        if parse_prompt:
            lines.append(f"- **解析提示词**：{parse_prompt}")
        lines.append("\n---\n")
        lines.append("## 来源追踪说明")
        lines.append("- 本导出按原始上传文件汇总 AI 提取的事实，供律师复核事实来源。")
        lines.append("- 每条事实下方列出来源文件、上传文件类型、页码/位置、原文摘录等可读线索；若原文件未提供相关字段，则不会显示。")
        lines.append("\n---\n")
        if facts:
            for i, f in enumerate(facts, 1):
                lines.append(f"## 事实 {i} — [{f.category}]")
                lines.append(f"**状态**: {_enum_text(f.status)}  |  **置信度**: {float(f.confidence_score or 0):.0%}\n")
                lines.append(f"**创建时间**: {local_display(f.created_at)}  |  **修改时间**: {local_display(f.updated_at or f.created_at)}\n")
                lines.append(f"{f.content}\n")
                lines.append("**来源追踪**")
                for label, value in _fact_trace_pairs(f, document_name=doc.original_filename, document_type=doc_type_label):
                    lines.append(f"- **{label}**：{value}")
                lines.append("")
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
        lines.append(f"原始文件名：{doc.original_filename}")
        lines.append(f"上传文件类型：{doc_type_label}")
        lines.append(f"解析状态：{_enum_text(doc.parse_status)}")
        lines.append(f"提取事实数：{fact_count}")
        if parse_prompt:
            lines.append(f"解析提示词：{parse_prompt}")
        lines.append("=" * 60)
        lines.append("来源追踪说明：")
        lines.append("本导出按原始上传文件汇总 AI 提取的事实，供律师复核事实来源。")
        lines.append("每条事实下方列出来源文件、上传文件类型、页码/位置、原文摘录等可读线索；若原文件未提供相关字段，则不会显示。")
        lines.append("=" * 60)
        if facts:
            for i, f in enumerate(facts, 1):
                lines.append(f"\n事实 {i} [{f.category}]")
                lines.append(f"状态: {_enum_text(f.status)}  |  置信度: {float(f.confidence_score or 0):.0%}")
                lines.append(f"创建时间: {local_display(f.created_at)}  |  修改时间: {local_display(f.updated_at or f.created_at)}")
                lines.append("-" * 40)
                lines.append(f.content)
                lines.append("来源追踪：")
                for label, value in _fact_trace_pairs(f, document_name=doc.original_filename, document_type=doc_type_label):
                    lines.append(f"- {label}：{value}")
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
    """Get system document categories.

    TODO(org): org-specific categories are intentionally ignored for now.
    """
    from app.models.organization import DocumentCategory
    query = select(DocumentCategory).where(
        DocumentCategory.org_id == None
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
