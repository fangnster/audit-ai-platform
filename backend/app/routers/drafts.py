"""
Drafts router — custom draft generation, section management, rewrite.
"""
from __future__ import annotations

import uuid
import io
import re
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from app.deps import CurrentUser, DB, ensure_case_member
from app.models.draft import DraftRevision, DraftSection, SectionStatus
from app.models.agent_task import AgentTask, AgentTaskType, AgentTaskStatus
from app.models.document import Document
from app.models.fact import Fact
from app.models.knowledge import KnowledgeItem
from app.services.agent_tasks import release_stale_agent_tasks
from app.services.cache import delete_pattern, get_json, set_json
from app.utils.timezone import local_display, local_iso

router = APIRouter()

STRATEGY_LABELS = {
    "strongest_first": "最强证据优先",
    "conservative": "保守严谨",
    "narrative": "叙事结构",
    "criterion": "法律要件结构",
    "rfe_response": "RFE/NOID 逐条回应",
    "resume_profile": "履历时间线",
    "legal_criteria": "法律要件组织",
    "original_contribution": "原创贡献链条",
    "external_recognition": "外部认可优先",
    "critical_role": "关键岗位影响",
    "rewrite_tighten": "压缩稳健重写",
    "rewrite_keep_facts": "保留事实重组",
}


def _compact_agent_payload(value, *, string_limit: int = 2400, list_limit: int = 30, depth: int = 0):
    """Keep Agent records detailed enough for auditing without returning huge prompts."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= string_limit else value[:string_limit].rstrip() + f"...（已截断 {len(value) - string_limit} 字符）"
    if isinstance(value, list):
        items = [_compact_agent_payload(item, string_limit=string_limit, list_limit=list_limit, depth=depth + 1) for item in value[:list_limit]]
        if len(value) > list_limit:
            items.append({"truncated_items": len(value) - list_limit})
        return items
    if isinstance(value, dict):
        if depth >= 4:
            text = str(value)
            return text if len(text) <= string_limit else text[:string_limit].rstrip() + "..."
        return {
            str(key): _compact_agent_payload(item, string_limit=string_limit, list_limit=list_limit, depth=depth + 1)
            for key, item in value.items()
        }
    return str(value)


def _to_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except Exception:
        return None


def _collect_uuid_values(payload: dict, keys: tuple[str, ...]) -> set[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    for key in keys:
        raw = payload.get(key)
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            parsed = _to_uuid(value)
            if parsed:
                ids.add(parsed)
    return ids


def _fact_label(fact: Fact) -> str:
    content = (fact.content or "").strip().replace("\n", " ")
    if len(content) > 120:
        content = content[:120].rstrip() + "..."
    return f"{fact.category} · {content}" if content else fact.category


async def _agent_task_human_context(db: DB, case_id: uuid.UUID, current_user, tasks: list[AgentTask]) -> dict[str, dict]:
    document_ids: set[uuid.UUID] = set()
    fact_ids: set[uuid.UUID] = set()
    section_ids: set[uuid.UUID] = set()
    knowledge_ids: set[uuid.UUID] = set()

    for task in tasks:
        input_params = task.input_params or {}
        output_result = task.output_result or {}
        document_ids |= _collect_uuid_values(input_params, ("document_id", "source_document_id"))
        document_ids |= _collect_uuid_values(output_result, ("document_id", "source_document_id"))
        reparse_source = output_result.get("reparse_source") if isinstance(output_result.get("reparse_source"), dict) else {}
        document_ids |= _collect_uuid_values(reparse_source, ("source_document_id",))

        fact_ids |= _collect_uuid_values(input_params, ("fact_id", "fact_ids"))
        fact_ids |= _collect_uuid_values(output_result, ("fact_id", "fact_ids"))

        section_ids |= _collect_uuid_values(input_params, ("section_id",))
        section_ids |= _collect_uuid_values(output_result, ("section_id",))

        knowledge_ids |= _collect_uuid_values(input_params, ("knowledge_ids",))
        knowledge_ids |= _collect_uuid_values(output_result, ("knowledge_ids",))

    documents: dict[uuid.UUID, Document] = {}
    if document_ids:
        result = await db.execute(
            select(Document).where(Document.case_id == case_id, Document.id.in_(document_ids))
        )
        documents = {item.id: item for item in result.scalars().all()}

    facts: dict[uuid.UUID, Fact] = {}
    if fact_ids:
        result = await db.execute(
            select(Fact).where(Fact.case_id == case_id, Fact.id.in_(fact_ids))
        )
        facts = {item.id: item for item in result.scalars().all()}

    sections: dict[uuid.UUID, DraftSection] = {}
    if section_ids:
        result = await db.execute(
            select(DraftSection).where(DraftSection.case_id == case_id, DraftSection.id.in_(section_ids))
        )
        sections = {item.id: item for item in result.scalars().all()}

    knowledge: dict[uuid.UUID, KnowledgeItem] = {}
    if knowledge_ids:
        result = await db.execute(
            select(KnowledgeItem).where(
                KnowledgeItem.id.in_(knowledge_ids),
                KnowledgeItem.user_id == current_user.id,
                KnowledgeItem.is_deleted == False,
            )
        )
        knowledge = {item.id: item for item in result.scalars().all()}

    contexts: dict[str, dict] = {}
    for task in tasks:
        input_params = task.input_params or {}
        output_result = task.output_result or {}
        context: dict = {}

        document_id = _to_uuid(input_params.get("document_id") or output_result.get("document_id"))
        if document_id and document_id in documents:
            doc = documents[document_id]
            context["document"] = {
                "name": doc.original_filename or doc.filename,
                "type": doc.doc_type,
            }

        reparse_source = output_result.get("reparse_source") if isinstance(output_result.get("reparse_source"), dict) else {}
        source_document_id = _to_uuid(
            input_params.get("source_document_id")
            or output_result.get("source_document_id")
            or reparse_source.get("source_document_id")
        )
        if source_document_id and source_document_id in documents:
            doc = documents[source_document_id]
            context["source_document"] = {
                "name": doc.original_filename or doc.filename,
                "type": doc.doc_type,
            }

        fact_id = _to_uuid(input_params.get("fact_id") or output_result.get("fact_id"))
        if fact_id and fact_id in facts:
            fact = facts[fact_id]
            context["fact"] = {
                "title": _fact_label(fact),
                "category": fact.category,
                "content": fact.content,
            }

        requested_fact_ids = [
            parsed for parsed in (_to_uuid(value) for value in input_params.get("fact_ids", []))
            if parsed and parsed in facts
        ]
        if requested_fact_ids:
            context["facts"] = [
                {
                    "title": _fact_label(facts[item_id]),
                    "category": facts[item_id].category,
                    "content": facts[item_id].content,
                }
                for item_id in requested_fact_ids
            ]

        section_id = _to_uuid(input_params.get("section_id") or output_result.get("section_id"))
        if section_id and section_id in sections:
            section = sections[section_id]
            context["section"] = {
                "title": section.section_title,
                "version": section.version,
            }

        requested_knowledge_ids = [
            parsed for parsed in (_to_uuid(value) for value in input_params.get("knowledge_ids", []))
            if parsed and parsed in knowledge
        ]
        if requested_knowledge_ids:
            context["knowledge_refs"] = [
                {
                    "title": knowledge[item_id].title,
                    "type": knowledge[item_id].item_type,
                }
                for item_id in requested_knowledge_ids
            ]
        else:
            refs = input_params.get("knowledge_refs") or output_result.get("knowledge_refs") or []
            if isinstance(refs, list):
                context["knowledge_refs"] = [
                    {
                        "title": str(item.get("title") or item.get("id") or ""),
                        "type": str(item.get("type") or ""),
                    }
                    for item in refs
                    if isinstance(item, dict) and (item.get("title") or item.get("id"))
                ]

        strategy = input_params.get("strategy") or output_result.get("strategy")
        if strategy:
            context["strategy_name"] = STRATEGY_LABELS.get(str(strategy), str(strategy))

        contexts[str(task.id)] = context
    return contexts


def _agent_task_summary(task: AgentTask) -> dict:
    output = task.output_result or {}
    input_params = task.input_params or {}
    task_type = str(task.task_type.value if hasattr(task.task_type, "value") else task.task_type)
    if task_type == AgentTaskType.fact_extract.value:
        diagnostics = output.get("diagnostics") or {}
        coverage = diagnostics.get("coverage") or {}
        return {
            "document_name": output.get("document_name") or input_params.get("document_name"),
            "facts_extracted": output.get("facts_extracted"),
            "doc_type": output.get("doc_type") or input_params.get("doc_type"),
            "text_quality": diagnostics.get("text_quality"),
            "chunk_count": diagnostics.get("chunk_count"),
            "coverage_score": coverage.get("coverage_score"),
            "potential_gap_count": coverage.get("potential_gap_count"),
            "warning": output.get("warning"),
        }
    if task_type == AgentTaskType.fact_reparse.value:
        return {
            "fact_category": output.get("fact_category") or input_params.get("fact_category"),
            "source_document": output.get("source_document"),
            "knowledge_ref_count": output.get("knowledge_ref_count"),
            "fallback_used": output.get("fallback_used"),
            "source_text_chars": output.get("source_text_chars"),
        }
    if task_type == AgentTaskType.draft_generate.value:
        return {
            "title": input_params.get("title"),
            "strategy": input_params.get("strategy"),
            "fact_count": output.get("fact_count"),
            "knowledge_ref_count": output.get("knowledge_ref_count"),
            "versions": output.get("versions"),
        }
    if task_type == AgentTaskType.rewrite_section.value:
        return {
            "section_id": input_params.get("section_id"),
            "strategy": output.get("strategy") or input_params.get("strategy"),
            "knowledge_ref_count": output.get("knowledge_ref_count"),
            "history_ref_count": output.get("history_ref_count"),
        }
    return {}


def attachment_headers(filename: str) -> dict[str, str]:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "download"
    encoded_name = quote(filename, safe="")
    return {"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"}


def download_response(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers=attachment_headers(filename),
    )


class RewriteRequest(BaseModel):
    instruction: str
    strategy: str = "strongest_first"
    knowledge_ids: list[str] = []
    fact_ids: list[str] = []


class ClientInputRequest(BaseModel):
    slot_id: str
    content: str


class GenerateRequest(BaseModel):
    title: str = ""
    prompt: str = ""
    strategy: str = "strongest_first"
    knowledge_ids: list[str] = []
    fact_ids: list[str] = []  # specific facts to use; empty = all approved


class UpdateSectionRequest(BaseModel):
    content_preview: str | None = None
    section_title: str | None = None


async def _validate_user_knowledge_ids(db: DB, knowledge_ids: list[str], current_user: CurrentUser) -> list[str]:
    if not knowledge_ids:
        return []
    try:
        parsed_ids = [uuid.UUID(item_id) for item_id in knowledge_ids]
    except ValueError as exc:
        raise HTTPException(400, "Invalid knowledge id") from exc

    result = await db.execute(
        select(KnowledgeItem.id).where(
            KnowledgeItem.id.in_(parsed_ids),
            KnowledgeItem.user_id == current_user.id,
            KnowledgeItem.is_deleted == False,
        )
    )
    requested_ids = [str(item_id) for item_id in parsed_ids]
    valid_ids = {str(item_id) for item_id in result.scalars().all()}
    if len(valid_ids) != len(set(requested_ids)):
        raise HTTPException(400, "Invalid or unauthorized knowledge id")
    return requested_ids


def _draft_order(sort_by: str, sort_order: str):
    columns = {
        "updated_at": DraftSection.updated_at,
        "created_at": DraftSection.created_at,
        "section_title": DraftSection.section_title,
        "section_order": DraftSection.section_order,
    }
    column = columns.get(sort_by, DraftSection.updated_at)
    direction = column.asc() if sort_order == "asc" else column.desc()
    return [direction, DraftSection.section_order.asc()]


def _draft_payload(s: DraftSection) -> dict:
    return {
        "id": str(s.id),
        "version": s.version,
        "section_order": s.section_order,
        "section_title": s.section_title,
        "content_preview": s.content[:300] + "..." if len(s.content) > 300 else s.content,
        "content": s.content,
        "status": s.status,
        "pending_slots": s.pending_slots,
        "criterion": s.criterion,
        "created_at": local_iso(s.created_at),
        "updated_at": local_iso(s.updated_at),
    }


async def _invalidate_draft_cache(case_id: uuid.UUID) -> None:
    await delete_pattern(f"drafts:{case_id}:*")


async def _ensure_case_access(db: DB, case_id: uuid.UUID, current_user) -> None:
    user_id = getattr(current_user, "id", None)
    if user_id is not None:
        await ensure_case_member(db, case_id, user_id)


async def _get_section_for_user(section_id: uuid.UUID, current_user, db: DB) -> DraftSection:
    section = await db.get(DraftSection, section_id)
    if not section:
        raise HTTPException(404, "Section not found")
    await _ensure_case_access(db, section.case_id, current_user)
    return section


async def create_draft_revision(
    db: DB,
    section: DraftSection,
    *,
    editor_role: str,
    editor_id: uuid.UUID | None,
    change_summary: str,
    metadata: dict | None = None,
) -> DraftRevision:
    result = await db.execute(
        select(DraftRevision.revision_number)
        .where(DraftRevision.section_id == section.id)
        .order_by(DraftRevision.revision_number.desc())
        .limit(1)
    )
    last_number = result.scalar_one_or_none() or 0
    revision = DraftRevision(
        section_id=section.id,
        case_id=section.case_id,
        revision_number=last_number + 1,
        section_title=section.section_title,
        content_snapshot=section.content,
        editor_role=editor_role,
        editor_id=editor_id,
        change_summary=change_summary,
        revision_metadata=metadata or {},
    )
    db.add(revision)
    return revision


@router.post("/cases/{case_id}/generate")
async def generate_drafts(case_id: uuid.UUID, body: GenerateRequest, current_user: CurrentUser, db: DB):
    """
    Trigger draft generation using user prompt + optional knowledge base items.
    Creates an AgentTask record and dispatches to worker queue.
    """
    await _ensure_case_access(db, case_id, current_user)
    knowledge_ids = await _validate_user_knowledge_ids(db, body.knowledge_ids, current_user)
    await release_stale_agent_tasks(db, case_id=case_id, task_types=[AgentTaskType.draft_generate], commit=False)
    running_result = await db.execute(
        select(AgentTask).where(
            AgentTask.case_id == case_id,
            AgentTask.task_type == AgentTaskType.draft_generate,
            AgentTask.status.in_([AgentTaskStatus.queued, AgentTaskStatus.processing]),
        )
        .order_by(AgentTask.created_at.desc())
        .limit(1)
    )
    running_task = running_result.scalar_one_or_none()
    if running_task:
        return {
            "case_id": str(case_id),
            "agent_task_id": str(running_task.id),
            "status": str(running_task.status.value if hasattr(running_task.status, "value") else running_task.status),
            "message": "已有文案生成任务正在处理中，请稍候完成后再发起新的生成。",
        }
    # Create agent task record
    agent_task = AgentTask(
        case_id=case_id,
        task_type=AgentTaskType.draft_generate,
        input_params={
            "case_id": str(case_id),
            "title": body.title,
            "prompt": body.prompt,
            "strategy": body.strategy,
            "knowledge_ids": knowledge_ids,
            "fact_ids": body.fact_ids,
        },
        status=AgentTaskStatus.queued,
        priority=3,
        llm_model="MiniMax-M2.7",
    )
    db.add(agent_task)
    await db.commit()
    await db.refresh(agent_task)
    await _invalidate_draft_cache(case_id)

    # Dispatch to Celery
    try:
        from app.workers.agent_tasks import generate_drafts as celery_task
        celery_task.delay(str(case_id), str(agent_task.id))
        return {
            "case_id": str(case_id),
            "agent_task_id": str(agent_task.id),
            "status": "queued",
            "message": "文案生成已启动，AI 将根据提示词和知识库参考生成文案。",
        }
    except Exception as e:
        # Dev mode: run synchronously
        return {
            "case_id": str(case_id),
            "agent_task_id": str(agent_task.id),
            "status": "queued",
            "message": f"已加入队列 (Celery 未运行: {str(e)[:80]})。启动 worker 后将自动处理。",
        }


@router.get("/cases/{case_id}")
async def list_sections(
    case_id: uuid.UUID,
    version: Optional[str] = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    current_user: CurrentUser = ...,
    db: DB = ...,
):
    """Get all draft sections, optionally filtered by version (a/b/c)."""
    await _ensure_case_access(db, case_id, current_user)
    cache_key = f"drafts:{case_id}:{current_user.id}:active:{version or 'all'}:{sort_by}:{sort_order}"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    query = select(DraftSection).where(
        DraftSection.case_id == case_id,
        DraftSection.is_deleted == False,
    )
    if version:
        query = query.where(DraftSection.version == version)
    query = query.order_by(*_draft_order(sort_by, sort_order))

    result = await db.execute(query)
    sections = result.scalars().all()

    payload = [_draft_payload(s) for s in sections]
    await set_json(cache_key, payload)
    return payload


@router.get("/cases/{case_id}/trash")
async def list_trash_sections(
    case_id: uuid.UUID,
    version: Optional[str] = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    current_user: CurrentUser = ...,
    db: DB = ...,
):
    """Get deleted draft sections (trash)."""
    await _ensure_case_access(db, case_id, current_user)
    cache_key = f"drafts:{case_id}:{current_user.id}:trash:{version or 'all'}:{sort_by}:{sort_order}"
    cached = await get_json(cache_key)
    if cached is not None:
        return cached
    query = select(DraftSection).where(
        DraftSection.case_id == case_id,
        DraftSection.is_deleted == True,
    )
    if version:
        query = query.where(DraftSection.version == version)
    query = query.order_by(*_draft_order(sort_by, sort_order))
    result = await db.execute(query)
    sections = result.scalars().all()
    payload = [_draft_payload(s) for s in sections]
    await set_json(cache_key, payload)
    return payload


@router.get("/cases/{case_id}/export")
async def export_drafts(
    case_id: uuid.UUID,
    version: Optional[str] = None,
    format: str = "docx",
    current_user: CurrentUser = ...,
    db: DB = ...,
):
    """
    Export draft sections as a downloadable file.
    Supported formats: txt, md, docx
    """
    await _ensure_case_access(db, case_id, current_user)
    query = select(DraftSection).where(
        DraftSection.case_id == case_id,
        DraftSection.is_deleted == False,
    )
    if version:
        query = query.where(DraftSection.version == version)
    query = query.order_by(DraftSection.section_order)
    result = await db.execute(query)
    sections = result.scalars().all()

    if not sections:
        raise HTTPException(404, "No sections to export")

    version_label = version.upper() if version else "ALL"

    if format == "md":
        lines = [f"# 文案导出 — {version_label}版\n"]
        lines.append(f"导出时间：{local_display()}\n")
        lines.append("---\n")
        for s in sections:
            lines.append(f"## {s.section_title}\n")
            lines.append(f"*Created: {local_display(s.created_at)}  |  Updated: {local_display(s.updated_at)}*\n")
            if s.criterion:
                lines.append(f"*Criterion: {s.criterion}*\n")
            lines.append(f"{s.content}\n")
            lines.append("---\n")
        content = "\n".join(lines)
        return download_response(
            content.encode("utf-8"),
            "text/markdown; charset=utf-8",
            f"draft_{version_label}.md",
        )

    elif format == "docx":
        try:
            from docx import Document as DocxDocument
            from docx.shared import Pt
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            raise HTTPException(400, "python-docx not installed. Use txt or md format.")

        doc = DocxDocument()
        # Title
        title = doc.add_heading(f"文案导出 — {version_label}版", level=0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph(f"导出时间：{local_display()}")
        doc.add_paragraph("" )  # spacer

        for s in sections:
            doc.add_heading(s.section_title, level=2)
            doc.add_paragraph(f"创建时间：{local_display(s.created_at)}    修改时间：{local_display(s.updated_at)}")
            if s.criterion:
                p = doc.add_paragraph(f"Criterion: {s.criterion}")
                p.runs[0].italic = True
            para = doc.add_paragraph(s.content)
            for run in para.runs:
                run.font.size = Pt(11)
            doc.add_paragraph("")  # spacer

        buf = io.BytesIO()
        doc.save(buf)
        return download_response(
            buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            f"draft_{version_label}.docx",
        )

    else:  # txt default
        lines = [f"文案导出 — {version_label}版"]
        lines.append(f"导出时间：{local_display()}")
        lines.append("=" * 60)
        for s in sections:
            lines.append(f"\n{s.section_title}")
            lines.append(f"创建时间：{local_display(s.created_at)}  |  修改时间：{local_display(s.updated_at)}")
            lines.append("-" * 40)
            if s.criterion:
                lines.append(f"[Criterion: {s.criterion}]")
            lines.append(s.content)
            lines.append("")
        content = "\n".join(lines)
        return download_response(
            content.encode("utf-8"),
            "text/plain; charset=utf-8",
            f"draft_{version_label}.txt",
        )


@router.get("/sections/{section_id}/export")
async def export_section(
    section_id: uuid.UUID,
    format: str = "docx",
    current_user: CurrentUser = ...,
    db: DB = ...,
    ):
    """Export a single draft section as a downloadable file."""
    section = await _get_section_for_user(section_id, current_user, db)

    now = local_display()
    safe_title = section.section_title.replace("/", "_").replace(" ", "_")[:50]

    if format == "md":
        lines = [f"# {section.section_title}\n"]
        lines.append(f"导出时间：{now}\n")
        lines.append(f"创建时间：{local_display(section.created_at)}  |  修改时间：{local_display(section.updated_at)}\n")
        if section.criterion:
            lines.append(f"*Criterion: {section.criterion}*\n")
        lines.append("---\n")
        lines.append(section.content)
        content = "\n".join(lines)
        return download_response(
            content.encode("utf-8"),
            "text/markdown; charset=utf-8",
            f"{safe_title}.md",
        )

    elif format == "docx":
        try:
            from docx import Document as DocxDocument
            from docx.shared import Pt
        except ImportError:
            raise HTTPException(400, "python-docx not installed. Use txt or md format.")

        doc = DocxDocument()
        doc.add_heading(section.section_title, level=1)
        doc.add_paragraph(f"导出时间：{now}")
        doc.add_paragraph(f"创建时间：{local_display(section.created_at)}    修改时间：{local_display(section.updated_at)}")
        if section.criterion:
            p = doc.add_paragraph(f"Criterion: {section.criterion}")
            p.runs[0].italic = True
        para = doc.add_paragraph(section.content)
        for run in para.runs:
            run.font.size = Pt(11)

        buf = io.BytesIO()
        doc.save(buf)
        return download_response(
            buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            f"{safe_title}.docx",
        )

    else:  # txt
        lines = [section.section_title]
        lines.append(f"导出时间：{now}")
        lines.append(f"创建时间：{local_display(section.created_at)}  |  修改时间：{local_display(section.updated_at)}")
        lines.append("=" * 40)
        if section.criterion:
            lines.append(f"[Criterion: {section.criterion}]")
        lines.append(section.content)
        content = "\n".join(lines)
        return download_response(
            content.encode("utf-8"),
            "text/plain; charset=utf-8",
            f"{safe_title}.txt",
        )


@router.get("/sections/{section_id}")
async def get_section(section_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Get full section content."""
    section = await _get_section_for_user(section_id, current_user, db)
    return {
        "id": str(section.id),
        "version": section.version,
        "section_title": section.section_title,
        "content": section.content,
        "status": section.status,
        "pending_slots": section.pending_slots,
        "created_at": local_iso(section.created_at),
        "updated_at": local_iso(section.updated_at),
    }


@router.post("/sections/{section_id}/rewrite")
async def rewrite_section(
    section_id: uuid.UUID,
    body: RewriteRequest,
    current_user: CurrentUser,
    db: DB,
):
    """
    Trigger AI rewrite of a section (P1 priority Celery task).
    Uses Redis distributed lock to prevent concurrent edits.
    """
    section = await _get_section_for_user(section_id, current_user, db)
    knowledge_ids = await _validate_user_knowledge_ids(db, body.knowledge_ids, current_user)

    # Create agent task
    agent_task = AgentTask(
        case_id=section.case_id,
        task_type=AgentTaskType.rewrite_section,
        input_params={
            "section_id": str(section_id),
            "instruction": body.instruction,
            "strategy": body.strategy,
            "knowledge_ids": knowledge_ids,
            "fact_ids": body.fact_ids,
        },
        status=AgentTaskStatus.queued,
        priority=1,
        llm_model="MiniMax-M2.7",
    )
    db.add(agent_task)
    await db.commit()
    await db.refresh(agent_task)

    # Check for existing lock
    import redis as _redis
    from app.config import settings
    r = _redis.from_url(settings.REDIS_URL, decode_responses=True)
    lock_key = f"section:{section.case_id}:{section_id}:lock"
    existing_lock = r.get(lock_key)
    if existing_lock:
        return {
            "section_id": str(section_id),
            "agent_task_id": str(agent_task.id),
            "status": "queued",
            "message": "Section is being edited by another agent. Your request is queued.",
        }

    # Dispatch
    try:
        from app.workers.agent_tasks import rewrite_section as celery_task
        celery_task.delay(str(section_id), body.instruction, str(section.case_id), str(agent_task.id))
    except Exception:
        pass

    return {
        "section_id": str(section_id),
        "agent_task_id": str(agent_task.id),
        "status": "queued",
        "instruction": body.instruction,
        "message": "Rewrite started. Update will be pushed via WebSocket when complete.",
    }


@router.patch("/sections/{section_id}/slot-input")
async def slot_input(section_id: uuid.UUID, body: ClientInputRequest, current_user: CurrentUser, db: DB):
    """Lawyer fills in a pending slot in the draft."""
    section = await _get_section_for_user(section_id, current_user, db)

    slots = section.pending_slots or {}
    if body.slot_id in slots:
        slots[body.slot_id]["filled_content"] = body.content
        slots[body.slot_id]["filled_by"] = str(current_user.id)
        section.pending_slots = slots
    else:
        raise HTTPException(400, f"Slot '{body.slot_id}' not found in this section")

    await db.commit()
    await _invalidate_draft_cache(section.case_id)
    return {"section_id": str(section_id), "slot_id": body.slot_id, "saved": True}


@router.post("/cases/{case_id}/rfi/generate")
async def generate_rfi(case_id: uuid.UUID, rfi_text: str, current_user: CurrentUser, db: DB):
    """Generate RFI/RFE response letter using AI."""
    from app.models.fact import Fact, FactStatus

    await _ensure_case_access(db, case_id, current_user)
    # Get approved facts for context
    result = await db.execute(
        select(Fact).where(
            Fact.case_id == case_id,
            Fact.status == FactStatus.lawyer_approved,
        ).limit(30)
    )
    facts = [{"category": f.category, "content": f.content} for f in result.scalars().all()]

    # Create agent task
    agent_task = AgentTask(
        case_id=case_id,
        task_type=AgentTaskType.rfi_generate,
        input_params={"rfi_text": rfi_text[:500], "fact_count": len(facts)},
        status=AgentTaskStatus.queued,
        priority=1,
        llm_model="MiniMax-M2.7",
    )
    db.add(agent_task)
    await db.commit()

    return {
        "agent_task_id": str(agent_task.id),
        "status": "queued",
        "message": "RFI response generation started. Will complete in ~1-2 minutes.",
    }


@router.get("/cases/{case_id}/agent-tasks")
async def list_agent_tasks(
    case_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    sort_order: str = "desc",
    ):
    """List all agent tasks for a case (for progress monitoring)."""
    await _ensure_case_access(db, case_id, current_user)
    await release_stale_agent_tasks(db, case_id=case_id)
    order = AgentTask.updated_at.asc() if sort_order == "asc" else AgentTask.updated_at.desc()
    result = await db.execute(
        select(AgentTask)
        .where(AgentTask.case_id == case_id)
        .order_by(order, AgentTask.created_at.desc())
        .limit(20)
    )
    tasks = result.scalars().all()
    human_contexts = await _agent_task_human_context(db, case_id, current_user, tasks)
    return [
        {
            "id": str(t.id),
            "task_type": t.task_type,
            "status": str(t.status.value if hasattr(t.status, "value") else t.status),
            "priority": t.priority,
            "llm_model": t.llm_model,
            "created_at": local_iso(t.created_at),
            "updated_at": local_iso(t.updated_at),
            "latency_ms": t.latency_ms or 0,
            "token_usage": t.token_usage or 0,
            "error_message": t.error_message,
            "input_params": _compact_agent_payload(t.input_params or {}),
            "output_result": _compact_agent_payload(t.output_result or {}),
            "summary": _compact_agent_payload(_agent_task_summary(t)),
            "human_context": _compact_agent_payload(human_contexts.get(str(t.id), {})),
        }
        for t in tasks
    ]


# ── Update Section ─────────────────────────

@router.patch("/sections/{section_id}")
async def update_section(
    section_id: uuid.UUID,
    body: UpdateSectionRequest,
    current_user: CurrentUser,
    db: DB,
    ):
    """Update a draft section's content or title."""
    section = await _get_section_for_user(section_id, current_user, db)
    title_changed = body.section_title is not None and body.section_title != section.section_title
    content_changed = body.content_preview is not None and body.content_preview != section.content
    if title_changed or content_changed:
        await create_draft_revision(
            db,
            section,
            editor_role="lawyer",
            editor_id=current_user.id,
            change_summary="Manual edit",
            metadata={"title_changed": title_changed, "content_changed": content_changed},
        )
    if body.content_preview is not None:
        section.content = body.content_preview
    if body.section_title is not None:
        section.section_title = body.section_title
    await db.commit()
    await _invalidate_draft_cache(section.case_id)
    return {"id": str(section_id), "status": "updated"}


@router.get("/sections/{section_id}/revisions")
async def list_section_revisions(section_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """List saved draft history snapshots for one full draft."""
    section = await _get_section_for_user(section_id, current_user, db)
    result = await db.execute(
        select(DraftRevision)
        .where(DraftRevision.section_id == section_id)
        .order_by(DraftRevision.revision_number.desc())
    )
    revisions = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "revision_number": r.revision_number,
            "section_title": r.section_title,
            "content_preview": r.content_snapshot[:240] + "..." if len(r.content_snapshot) > 240 else r.content_snapshot,
            "content": r.content_snapshot,
            "editor_role": r.editor_role,
            "change_summary": r.change_summary,
            "created_at": local_iso(r.created_at),
        }
        for r in revisions
    ]


@router.post("/sections/{section_id}/revisions/{revision_id}/restore")
async def restore_section_revision(
    section_id: uuid.UUID,
    revision_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
):
    """Restore a draft from a saved history snapshot, while preserving current content first."""
    section = await _get_section_for_user(section_id, current_user, db)
    revision = await db.get(DraftRevision, revision_id)
    if not revision or revision.section_id != section_id:
        raise HTTPException(404, "Revision not found")

    await create_draft_revision(
        db,
        section,
        editor_role="lawyer",
        editor_id=current_user.id,
        change_summary=f"Before restoring revision {revision.revision_number}",
        metadata={"restored_revision_id": str(revision_id)},
    )
    section.section_title = revision.section_title
    section.content = revision.content_snapshot
    section.status = SectionStatus.draft
    await db.commit()
    await _invalidate_draft_cache(section.case_id)
    return {"id": str(section_id), "status": "restored", "revision_number": revision.revision_number}


# ── Soft Delete / Restore / Permanent Delete ──

@router.delete("/sections/{section_id}")
async def soft_delete_section(section_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Move a draft section to trash (soft delete)."""
    section = await _get_section_for_user(section_id, current_user, db)
    section.is_deleted = True
    await db.commit()
    await _invalidate_draft_cache(section.case_id)
    return {"id": str(section_id), "status": "moved_to_trash"}


@router.post("/sections/{section_id}/restore")
async def restore_section(section_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Restore a deleted draft section from trash."""
    section = await _get_section_for_user(section_id, current_user, db)
    if not section.is_deleted:
        raise HTTPException(404, "Section not found in trash")
    section.is_deleted = False
    await db.commit()
    await _invalidate_draft_cache(section.case_id)
    return {"id": str(section_id), "status": "restored"}


@router.post("/sections/{section_id}/permanent-delete")
async def permanent_delete_section(section_id: uuid.UUID, current_user: CurrentUser, db: DB):
    """Permanently delete a draft section. Must be in trash first."""
    section = await _get_section_for_user(section_id, current_user, db)
    if not section.is_deleted:
        raise HTTPException(400, "Section must be in trash before permanent deletion")
    case_id = section.case_id
    await db.delete(section)
    await db.commit()
    await _invalidate_draft_cache(case_id)
    return {"id": str(section_id), "status": "permanently_deleted"}
