import uuid
import os
import tempfile
from dataclasses import dataclass
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.models.fact import Fact, FactStatus
from app.deps import CurrentUser, DB, ensure_case_member
from app.services.agent_tasks import release_stale_agent_tasks
from app.services.cache import delete_pattern, get_json, set_json
from app.utils.timezone import local_iso, local_now

router = APIRouter()


class UpdateFactRequest(BaseModel):
    content: Optional[str] = None
    category: Optional[str] = None


def _truncate_source_text(text: str, max_chars: int = 12000) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return text[:head] + f"\n\n[... {len(text) - max_chars} chars omitted ...]\n\n" + text[-tail:]


@dataclass
class SourceDocumentContext:
    text: str
    document_name: str
    diagnostics: dict


def _structured_source_context(fact: Fact) -> tuple[str, str]:
    """Build a best-effort context from fact metadata when the original file is unavailable."""
    sd = dict(fact.structured_data or {})
    doc_name = str(sd.get("document_name") or sd.get("source") or "")
    parts: list[str] = []
    for key in (
        "document_name",
        "source",
        "quote",
        "title",
        "date",
        "organization",
        "impact",
        "numbers",
        "parse_prompt",
        "source_type",
    ):
        value = sd.get(key)
        if value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts), doc_name


def _looks_like_resume_context(fact: Fact, document_name: str, source_text: str) -> bool:
    sd = dict(fact.structured_data or {})
    haystack = " ".join([
        document_name or "",
        str(sd.get("document_name") or ""),
        str(sd.get("parse_prompt") or ""),
        str(sd.get("source") or ""),
        fact.category or "",
        source_text[:1200],
    ]).lower()
    markers = ("resume", "cv", "curriculum vitae", "简历", "履历", "个人综述", "个人简介")
    return any(marker in haystack for marker in markers)


def _extract_text_from_document_bytes(content: bytes, filename: str, mime_type: str) -> str:
    from app.agents.fact_extractor import extract_text_from_file

    suffix = os.path.splitext(filename or "")[1]
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_path = tmp.name
            tmp.write(content)
        extracted = extract_text_from_file(temp_path, mime_type)
        if extracted.strip():
            return extracted
        try:
            return content.decode("utf-8", errors="ignore")
        except Exception:
            return ""
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _fact_order(sort_by: str, sort_order: str):
    columns = {
        "updated_at": Fact.updated_at,
        "created_at": Fact.created_at,
        "category": Fact.category,
        "confidence_score": Fact.confidence_score,
        "status": Fact.status,
    }
    column = columns.get(sort_by, Fact.updated_at)
    direction = column.asc() if sort_order == "asc" else column.desc()
    return [direction, Fact.created_at.desc()]


def _fact_payload(f: Fact) -> dict:
    return {
        "id": str(f.id), "category": f.category, "content": f.content,
        "status": f.status, "confidence_score": float(f.confidence_score),
        "structured_data": f.structured_data or {},
        "created_at": local_iso(f.created_at),
        "updated_at": local_iso(f.updated_at),
    }


async def _invalidate_fact_cache(case_id: uuid.UUID) -> None:
    await delete_pattern(f"facts:{case_id}:*")
    await delete_pattern(f"agent-tasks:{case_id}:*")


async def _get_fact_for_user(fact_id: uuid.UUID, current_user, db: DB) -> Fact:
    result = await db.execute(select(Fact).where(Fact.id == fact_id))
    fact = result.scalar_one_or_none()
    if not fact:
        raise HTTPException(404, "Fact not found")
    await ensure_case_member(db, fact.case_id, current_user.id)
    return fact


async def _source_document_text(fact: Fact, db: DB) -> SourceDocumentContext:
    """Best-effort text extraction for a fact's source document."""
    metadata_context, metadata_doc_name = _structured_source_context(fact)
    if not fact.source_document_id:
        return SourceDocumentContext(
            text=_truncate_source_text(metadata_context),
            document_name=metadata_doc_name,
            diagnostics={
                "source": "fact_metadata" if metadata_context else "unavailable",
                "source_document_id": None,
                "source_text_available": bool(metadata_context),
                "error": "Fact has no linked source document.",
            },
        )

    from app.models.document import Document
    from app.routers.documents import read_document_bytes

    doc = await db.get(Document, fact.source_document_id)
    if not doc:
        return SourceDocumentContext(
            text=_truncate_source_text(metadata_context),
            document_name=metadata_doc_name,
            diagnostics={
                "source": "fact_metadata" if metadata_context else "unavailable",
                "source_document_id": str(fact.source_document_id),
                "source_text_available": bool(metadata_context),
                "error": "Linked source document record was not found.",
            },
        )

    doc_name = doc.original_filename or metadata_doc_name
    mime_type = doc.mime_type or ""
    try:
        content = read_document_bytes(doc)
        extracted = _extract_text_from_document_bytes(content, doc.original_filename or "", mime_type)
        if extracted.strip():
            return SourceDocumentContext(
                text=_truncate_source_text(extracted),
                document_name=doc_name,
                diagnostics={
                    "source": "uploaded_file",
                    "source_document_id": str(fact.source_document_id),
                    "source_text_available": True,
                },
            )
        error = "Original file was found, but no readable text could be extracted."
    except Exception as exc:
        error = str(exc)

    fallback_text = metadata_context
    return SourceDocumentContext(
        text=_truncate_source_text(fallback_text),
        document_name=doc_name,
        diagnostics={
            "source": "fact_metadata" if fallback_text else "unavailable",
            "source_document_id": str(fact.source_document_id),
            "source_text_available": bool(fallback_text),
            "error": error,
        },
    )




# ── List ───────────────────────────────────

@router.get("/cases/{case_id}/facts")
async def list_facts(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
):
    await ensure_case_member(db, case_id, current_user.id)
    cache_key = f"facts:{case_id}:{current_user.id}:active:{sort_by}:{sort_order}"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    result = await db.execute(
        select(Fact).where(Fact.case_id == case_id, Fact.is_deleted == False)
        .order_by(*_fact_order(sort_by, sort_order))
    )
    payload = [_fact_payload(f) for f in result.scalars()]
    await set_json(cache_key, payload)
    return payload


@router.get("/cases/{case_id}/facts/trash")
async def list_facts_trash(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
):
    await ensure_case_member(db, case_id, current_user.id)
    cache_key = f"facts:{case_id}:{current_user.id}:trash:{sort_by}:{sort_order}"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    result = await db.execute(
        select(Fact).where(Fact.case_id == case_id, Fact.is_deleted == True)
        .order_by(*_fact_order(sort_by, sort_order))
    )
    payload = [_fact_payload(f) for f in result.scalars()]
    await set_json(cache_key, payload)
    return payload


# ── Approve / Confirm / Dispute ────────────

@router.post("/{fact_id}/approve")
async def approve_fact(fact_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Toggle approval: extracted ↔ lawyer_approved"""
    fact = await _get_fact_for_user(fact_id, current_user, db)
    if fact.status == FactStatus.lawyer_approved:
        fact.status = FactStatus.extracted
    else:
        fact.status = FactStatus.lawyer_approved
    await db.commit()
    await _invalidate_fact_cache(fact.case_id)
    return {"id": str(fact.id), "status": fact.status}




class DisputeRequest(BaseModel):
    comment: str
    knowledge_ids: list[uuid.UUID] = Field(default_factory=list)


@router.post("/{fact_id}/dispute")
async def dispute_fact(fact_id: uuid.UUID, body: DisputeRequest, current_user: CurrentUser, db: DB):
    """
    Mark a fact as disputed and queue a background reparse using the dispute comment as guidance.
    """
    fact = await _get_fact_for_user(fact_id, current_user, db)
    if not body.comment.strip():
        raise HTTPException(400, "Dispute comment cannot be empty")

    dispute_comment = body.comment.strip()

    knowledge_refs: list[dict[str, str]] = []
    if body.knowledge_ids:
        from app.models.knowledge import KnowledgeItem

        result = await db.execute(
            select(KnowledgeItem).where(
                KnowledgeItem.id.in_(body.knowledge_ids),
                KnowledgeItem.user_id == current_user.id,
                KnowledgeItem.is_deleted == False,
                KnowledgeItem.item_type.in_(["prompt_template", "agent_strategy"]),
            )
        )
        selected_items = result.scalars().all()
        if len({str(item.id) for item in selected_items}) != len({str(item_id) for item_id in body.knowledge_ids}):
            raise HTTPException(400, "Invalid or unauthorized reparse knowledge id")
        for item in selected_items:
            knowledge_refs.append({
                "id": str(item.id),
                "title": item.title,
                "type": item.item_type,
            })

    from app.config import settings
    from app.models.agent_task import AgentTask, AgentTaskStatus, AgentTaskType
    from app.models.case import Case
    from app.models.organization import Organization

    locked_fact_result = await db.execute(
        select(Fact)
        .where(Fact.id == fact.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    fact = locked_fact_result.scalar_one()
    original_content = fact.content
    await release_stale_agent_tasks(
        db,
        case_id=fact.case_id,
        task_types=[AgentTaskType.fact_reparse],
        input_key="fact_id",
        input_value=str(fact.id),
        commit=False,
    )

    running_result = await db.execute(
        select(AgentTask)
        .where(
            AgentTask.case_id == fact.case_id,
            AgentTask.task_type == AgentTaskType.fact_reparse,
            AgentTask.status.in_([AgentTaskStatus.queued, AgentTaskStatus.processing]),
            AgentTask.input_params.op("->>")("fact_id") == str(fact.id),
        )
        .order_by(AgentTask.created_at.desc())
        .limit(1)
    )
    running_task = running_result.scalar_one_or_none()
    if running_task:
        return {
            "id": str(fact.id),
            "agent_task_id": str(running_task.id),
            "status": str(running_task.status.value if hasattr(running_task.status, "value") else running_task.status),
            "regenerated": False,
            "original_content": original_content,
            "message": "该事实已有重解析任务在后台处理中，请稍候查看 Agent 运行记录。",
        }

    sd = dict(fact.structured_data or {})
    sd["dispute_comment"] = dispute_comment
    sd["original_content"] = original_content
    sd["dispute_queued_at"] = local_iso(local_now())
    if knowledge_refs:
        sd["reparse_knowledge_refs"] = knowledge_refs

    case = await db.get(Case, fact.case_id)
    case_type = case.case_type.value if case and hasattr(case.case_type, "value") else (str(case.case_type) if case else "")
    case_title = case.title if case else ""
    org = await db.get(Organization, case.org_id) if case else None
    org_settings = org.settings if org and org.settings else {}

    fact.structured_data = sd
    fact.status = FactStatus.disputed
    agent_task = AgentTask(
        case_id=fact.case_id,
        task_type=AgentTaskType.fact_reparse,
        input_params={
            "case_id": str(fact.case_id),
            "case_title": case_title,
            "case_type": case_type,
            "fact_id": str(fact.id),
            "fact_category": fact.category,
            "comment": dispute_comment,
            "knowledge_ids": [str(item_id) for item_id in body.knowledge_ids],
            "knowledge_refs": knowledge_refs,
            "user_id": str(current_user.id),
            "original_content": original_content[:2000],
        },
        status=AgentTaskStatus.queued,
        priority=1,
        llm_model=org_settings.get("llm_model") or settings.LLM_MODEL,
    )
    db.add(agent_task)
    await db.commit()
    await db.refresh(agent_task)
    await _invalidate_fact_cache(fact.case_id)

    try:
        from app.workers.agent_tasks import reparse_fact as celery_task

        celery_task.delay(str(fact.case_id), str(fact.id), str(agent_task.id))
    except Exception as exc:
        return {
            "id": str(fact.id),
            "agent_task_id": str(agent_task.id),
            "status": "queued",
            "message": f"事实重解析任务已加入后台队列。Celery 暂未确认接收：{str(exc)[:80]}",
        }

    return {
        "id": str(fact.id),
        "agent_task_id": str(agent_task.id),
        "status": "queued",
        "regenerated": False,
        "original_content": original_content,
        "message": "事实重解析已在后台启动，可在 Agent 运行记录查看进度和结果。",
    }


# ── Update ─────────────────────────────────

@router.patch("/{fact_id}")
async def update_fact(fact_id: uuid.UUID, body: UpdateFactRequest, current_user: CurrentUser, db: DB):
    fact = await _get_fact_for_user(fact_id, current_user, db)
    if body.content is not None:
        fact.content = body.content
    if body.category is not None:
        fact.category = body.category
    await db.commit()
    await _invalidate_fact_cache(fact.case_id)
    return {"id": str(fact.id), "status": "updated"}


# ── Soft Delete ────────────────────────────

@router.delete("/{fact_id}")
async def soft_delete_fact(fact_id: uuid.UUID, current_user: CurrentUser, db: DB):
    fact = await _get_fact_for_user(fact_id, current_user, db)
    fact.is_deleted = True
    await db.commit()
    await _invalidate_fact_cache(fact.case_id)
    return {"id": str(fact.id), "status": "deleted"}


@router.post("/{fact_id}/restore")
async def restore_fact(fact_id: uuid.UUID, current_user: CurrentUser, db: DB):
    fact = await _get_fact_for_user(fact_id, current_user, db)
    fact.is_deleted = False
    await db.commit()
    await _invalidate_fact_cache(fact.case_id)
    return {"id": str(fact.id), "status": "restored"}


@router.delete("/{fact_id}/permanent")
async def permanent_delete_fact(fact_id: uuid.UUID, current_user: CurrentUser, db: DB):
    fact = await _get_fact_for_user(fact_id, current_user, db)
    if not fact.is_deleted:
        raise HTTPException(400, "Fact must be in trash before permanent deletion")
    case_id = fact.case_id
    await db.delete(fact)
    await db.commit()
    await _invalidate_fact_cache(case_id)
    return {"id": str(fact_id), "status": "permanently_deleted"}

# ── Upload Evidence ────────────────────────

from fastapi import UploadFile, File, Form


@router.post("/cases/{case_id}/upload-evidence")
async def upload_evidence(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    source_type: str = Form("legal_document"),
):
    """
    Upload an audit reference document or internet evidence file.
    AI parses the file and extracts facts with source annotations.
    In production, this would use an LLM to parse the document.
    For dev, generates simulated extracted facts.
    """
    await ensure_case_member(db, case_id, current_user.id)
    filename = file.filename or "unknown"
    content_bytes = await file.read()

    # Category based on source type
    category = "legal_precedent" if source_type == "legal_document" else "internet_research"

    # Simulated AI extraction results
    simulated_facts = [
        {
            "content": f"文档 '{filename}' 的演示占位记录：请核验审计证据来源、会计期间和相关业务，"
                       f"此记录不是已完成的事实提取结果。",
            "confidence_score": 0.85,
        },
        {
            "content": f"文档 '{filename}' 的演示复核提示：请核对金额、凭证编号和控制执行证据，"
                       f"人工确认前不得作为审计结论依据。",
            "confidence_score": 0.78,
        },
    ]

    facts_added = 0
    for item in simulated_facts:
        fact = Fact(
            case_id=case_id,
            category=category,
            content=item["content"],
            structured_data={
                "source": "审计参考文档" if source_type == "legal_document" else "互联网证据",
                "document_name": filename,
                "source_type": source_type,
                "type": "uploaded_evidence",
            },
            confidence_score=item["confidence_score"],
            status=FactStatus.extracted,
        )
        db.add(fact)
        facts_added += 1

    await db.commit()
    await _invalidate_fact_cache(case_id)
    return {"facts_added": facts_added, "filename": filename, "source_type": source_type}
