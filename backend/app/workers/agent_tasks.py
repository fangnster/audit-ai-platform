"""
Celery tasks: AI agent orchestration.
- generate_drafts: custom legal draft generation
- rewrite_section: section-level rewrite with Redis locking
- fix_fact: P0 priority fact correction after fact confirmation
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid

import redis

from app.workers.celery_app import celery_app
from app.config import settings
from app.llm.provider import strip_think_tags

logger = logging.getLogger(__name__)
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

SECTION_LOCK_TTL = 120  # seconds
DEFAULT_DOCUMENT_TYPE_LABELS = {
    "evidence": "证据材料",
    "award": "获奖证明",
    "original_contribution": "原创成果",
    "patent": "专利",
    "publication": "学术发表",
    "citation": "引用数据",
    "employment": "雇佣证明",
    "media": "媒体报道",
    "membership": "专业组织",
    "resume": "个人简历",
    "reference_letter": "推荐信",
    "petition_letter": "申请信",
    "rfi": "RFI 回复",
    "other": "其他",
}


def _truncate_text(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _get_db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import sync_database_url

    engine = create_engine(sync_database_url())
    return engine, Session(engine)


def _status_value(status) -> str:
    return str(status.value if hasattr(status, "value") else status)


def _mark_processing(agent_task) -> bool:
    from app.models.agent_task import AgentTaskStatus

    if not agent_task:
        return False
    if _status_value(agent_task.status) not in {AgentTaskStatus.queued.value, AgentTaskStatus.processing.value}:
        return False
    agent_task.status = AgentTaskStatus.processing
    agent_task.error_message = None
    return True


def _worker_may_continue(session, agent_task) -> bool:
    from app.models.agent_task import AgentTaskStatus

    if not agent_task:
        return False
    session.refresh(agent_task)
    return _status_value(agent_task.status) in {AgentTaskStatus.queued.value, AgentTaskStatus.processing.value}


def _mark_completed(agent_task, output_result: dict, started_at: float) -> None:
    from app.models.agent_task import AgentTaskStatus

    if agent_task:
        agent_task.status = AgentTaskStatus.completed
        agent_task.output_result = output_result
        agent_task.latency_ms = int((time.perf_counter() - started_at) * 1000)
        agent_task.error_message = None


def _mark_failed(agent_task, output_result: dict, started_at: float, error_message: str) -> None:
    from app.models.agent_task import AgentTaskStatus

    if agent_task:
        agent_task.status = AgentTaskStatus.failed
        agent_task.output_result = output_result
        agent_task.latency_ms = int((time.perf_counter() - started_at) * 1000)
        agent_task.error_message = error_message[:1000]


def _record_agent_task_error(agent_task_id: str, exc: Exception, started_at: float, *, final: bool) -> None:
    from app.models.agent_task import AgentTask, AgentTaskStatus

    engine, session = _get_db_session()
    try:
        with session:
            agent_task = session.get(AgentTask, uuid.UUID(agent_task_id))
            if not agent_task:
                return
            agent_task.status = AgentTaskStatus.failed if final else AgentTaskStatus.queued
            agent_task.error_message = str(exc)[:1000]
            agent_task.latency_ms = int((time.perf_counter() - started_at) * 1000)
            session.commit()
    finally:
        engine.dispose()


def _invalidate_case_runtime_cache(case_id: str) -> None:
    from app.services.cache import delete_pattern_sync

    delete_pattern_sync(f"drafts:{case_id}:*")
    delete_pattern_sync(f"facts:{case_id}:*")
    delete_pattern_sync(f"tasks:{case_id}:*")
    delete_pattern_sync(f"documents:{case_id}:*")
    delete_pattern_sync(f"agent-tasks:{case_id}:*")
    delete_pattern_sync("admin:v1:*")


def _fact_to_prompt_dict(fact) -> dict:
    structured = fact.structured_data or {}
    compact_structured = {
        key: _truncate_text(str(structured.get(key) or ""), settings.DRAFT_MAX_FACT_QUOTE_CHARS)
        for key in ("document_name", "source", "quote", "page")
        if structured.get(key) is not None
    }
    return {
        "id": str(fact.id),
        "source_document_id": str(fact.source_document_id) if fact.source_document_id else None,
        "category": fact.category,
        "content": _truncate_text(fact.content, settings.DRAFT_MAX_FACT_CHARS),
        "structured_data": compact_structured,
        "confidence_score": fact.confidence_score,
    }


def _fact_ref_title(fact) -> str:
    content = _truncate_text(fact.content, 180)
    return f"[{fact.category}] {content}" if content else f"[{fact.category}]"


def _source_document_name(fact, documents_by_id: dict) -> str:
    if fact.source_document_id and fact.source_document_id in documents_by_id:
        doc = documents_by_id[fact.source_document_id]
        return doc.original_filename or doc.filename
    structured = dict(fact.structured_data or {})
    return str(structured.get("document_name") or structured.get("source") or "未关联原始文件")


def _source_document_type(fact, documents_by_id: dict, doc_type_labels: dict) -> str:
    if fact.source_document_id and fact.source_document_id in documents_by_id:
        doc_type = str(documents_by_id[fact.source_document_id].doc_type or "")
        return str(doc_type_labels.get(doc_type) or DEFAULT_DOCUMENT_TYPE_LABELS.get(doc_type) or doc_type or "未知类型")
    return "未知类型"


def _draft_reference_payload(fact_rows: list, documents_by_id: dict, doc_type_labels: dict) -> tuple[list[dict], list[dict]]:
    fact_refs: list[dict] = []
    document_stats: dict[tuple[str, str], int] = {}
    for index, fact in enumerate(fact_rows, 1):
        structured = dict(fact.structured_data or {})
        document_name = _source_document_name(fact, documents_by_id)
        document_type = _source_document_type(fact, documents_by_id, doc_type_labels)
        document_stats[(document_name, document_type)] = document_stats.get((document_name, document_type), 0) + 1
        ref = {
            "title": f"{index}. {_fact_ref_title(fact)}",
            "source_document": document_name,
            "document_type": document_type,
            "confidence": round(float(fact.confidence_score or 0), 3),
            "status": _status_value(fact.status),
        }
        quote = structured.get("quote")
        page = structured.get("page")
        if quote:
            ref["quote"] = _truncate_text(str(quote), 260)
        if page:
            ref["page"] = str(page)
        fact_refs.append(ref)

    document_refs = [
        {
            "title": f"{name}（{doc_type}，引用事实 {count} 条）",
            "name": name,
            "document_type": doc_type,
            "fact_count": count,
        }
        for (name, doc_type), count in sorted(document_stats.items(), key=lambda item: item[0][0])
    ]
    return fact_refs, document_refs


def _format_draft_reference_appendix(fact_refs: list[dict], document_refs: list[dict]) -> str:
    if not fact_refs and not document_refs:
        return ""
    lines = [
        "---",
        "生成依据 / 溯源追踪（供律师审核，可在定稿前删除）",
        "",
    ]
    if document_refs:
        lines.append("引用文件：")
        for item in document_refs:
            lines.append(f"- {item['name']}（{item['document_type']}，引用事实 {item['fact_count']} 条）")
        lines.append("")
    if fact_refs:
        lines.append("引用事实：")
        for item in fact_refs:
            lines.append(f"- {item['title']}")
            lines.append(f"  来源文件：{item['source_document']}（{item['document_type']}）")
            if item.get("page"):
                lines.append(f"  页码/位置：{item['page']}")
            if item.get("quote"):
                lines.append(f"  原文摘录：{item['quote']}")
    return "\n".join(lines)


def _truncate_source_text(text: str, max_chars: int = 12000) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return text[:head] + f"\n\n[... {len(text) - max_chars} chars omitted ...]\n\n" + text[-tail:]


def _structured_source_context(fact) -> tuple[str, str]:
    structured = dict(fact.structured_data or {})
    doc_name = str(structured.get("document_name") or structured.get("source") or "")
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
        value = structured.get(key)
        if value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts), doc_name


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


def _source_document_text(fact, session) -> dict:
    metadata_context, metadata_doc_name = _structured_source_context(fact)
    if not fact.source_document_id:
        return {
            "text": _truncate_source_text(metadata_context),
            "document_name": metadata_doc_name,
            "diagnostics": {
                "source": "fact_metadata" if metadata_context else "unavailable",
                "source_document_id": None,
                "source_text_available": bool(metadata_context),
                "error": "Fact has no linked source document.",
            },
        }

    from app.models.document import Document
    from app.routers.documents import read_document_bytes

    doc = session.get(Document, fact.source_document_id)
    if not doc:
        return {
            "text": _truncate_source_text(metadata_context),
            "document_name": metadata_doc_name,
            "diagnostics": {
                "source": "fact_metadata" if metadata_context else "unavailable",
                "source_document_id": str(fact.source_document_id),
                "source_text_available": bool(metadata_context),
                "error": "Linked source document record was not found.",
            },
        }

    doc_name = doc.original_filename or metadata_doc_name
    try:
        content = read_document_bytes(doc)
        extracted = _extract_text_from_document_bytes(content, doc.original_filename or "", doc.mime_type or "")
        if extracted.strip():
            return {
                "text": _truncate_source_text(extracted),
                "document_name": doc_name,
                "diagnostics": {
                    "source": "uploaded_file",
                    "source_document_id": str(fact.source_document_id),
                    "source_text_available": True,
                },
            }
        error = "Original file was found, but no readable text could be extracted."
    except Exception as exc:
        error = str(exc)

    return {
        "text": _truncate_source_text(metadata_context),
        "document_name": doc_name,
        "diagnostics": {
            "source": "fact_metadata" if metadata_context else "unavailable",
            "source_document_id": str(fact.source_document_id),
            "source_text_available": bool(metadata_context),
            "error": error,
        },
    }


def _looks_like_resume_context(fact, document_name: str, source_text: str) -> bool:
    structured = dict(fact.structured_data or {})
    haystack = " ".join([
        document_name or "",
        str(structured.get("document_name") or ""),
        str(structured.get("parse_prompt") or ""),
        str(structured.get("source") or ""),
        fact.category or "",
        source_text[:1200],
    ]).lower()
    markers = ("resume", "cv", "curriculum vitae", "简历", "履历", "个人综述", "个人简介")
    return any(marker in haystack for marker in markers)


def _draft_history_refs(session, case_uuid: uuid.UUID, exclude_section_id: uuid.UUID | None = None) -> list[dict]:
    """Collect recent same-case draft history as generation guidance."""
    from app.models.draft import DraftRevision, DraftSection
    from sqlalchemy import select

    section_query = (
        select(DraftSection)
        .where(DraftSection.case_id == case_uuid, DraftSection.is_deleted == False)
        .order_by(DraftSection.updated_at.desc())
        .limit(4)
    )
    if exclude_section_id:
        section_query = section_query.where(DraftSection.id != exclude_section_id)

    refs: list[dict] = []
    for section in session.execute(section_query).scalars().all():
        refs.append({
            "title": f"当前历史文案：{section.section_title}",
            "type": "draft_history",
            "content": section.content,
        })

    revision_query = (
        select(DraftRevision)
        .where(DraftRevision.case_id == case_uuid)
        .order_by(DraftRevision.created_at.desc())
        .limit(4)
    )
    if exclude_section_id:
        revision_query = revision_query.where(DraftRevision.section_id != exclude_section_id)

    for revision in session.execute(revision_query).scalars().all():
        refs.append({
            "title": f"历史版本 #{revision.revision_number}：{revision.section_title}",
            "type": "draft_history",
            "content": revision.content_snapshot,
        })

    return refs[:6]


@celery_app.task(
    bind=True,
    max_retries=2,
    soft_time_limit=settings.DRAFT_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=settings.DRAFT_TASK_TIME_LIMIT_SECONDS,
    name="app.workers.agent_tasks.generate_drafts",
)
def generate_drafts(self, case_id: str, agent_task_id: str):
    """
    Generate one strategy-driven, lawyer-customized draft for a case.
    Reads selected facts, prompt, and knowledge from DB, then writes one full DraftSection.
    """
    from app.models.fact import Fact, FactStatus
    from app.models.draft import DraftRevision, DraftSection, SectionStatus
    from app.models.agent_task import AgentTask
    from app.models.case import Case
    from app.models.document import Document
    from app.models.organization import Organization
    from app.models.knowledge import KnowledgeItem
    from app.agents.draft_generator import DraftGenerationAgent
    from app.llm.provider import LLMService
    from sqlalchemy import select

    started_at = time.perf_counter()
    logger.info("agent_task_start type=generate_drafts task_id=%s case_id=%s", agent_task_id, case_id)
    engine, session = _get_db_session()
    try:
        with session:
            # Update task status
            agent_task = session.get(AgentTask, uuid.UUID(agent_task_id))
            if not _mark_processing(agent_task):
                logger.info("agent_task_skip_released type=generate_drafts task_id=%s case_id=%s", agent_task_id, case_id)
                return {"case_id": case_id, "skipped": "agent task already released"}
            session.commit()

            case = session.get(Case, uuid.UUID(case_id))
            if not case:
                if agent_task:
                    _mark_failed(agent_task, {"error": "case not found"}, started_at, "case not found")
                    session.commit()
                return {"error": "case not found"}

            # Read prompt, knowledge_ids, fact_ids from agent_task input_params
            input_params = (agent_task.input_params or {}) if agent_task else {}
            draft_title = input_params.get("title", "")
            user_prompt = input_params.get("prompt", "")
            strategy = input_params.get("strategy", "strongest_first")
            knowledge_ids = input_params.get("knowledge_ids", [])
            fact_ids = input_params.get("fact_ids", [])
            doc_type_labels = {
                **DEFAULT_DOCUMENT_TYPE_LABELS,
                **(input_params.get("doc_type_labels") or {}),
            }
            knowledge_ids = knowledge_ids[: settings.DRAFT_MAX_KNOWLEDGE_ITEMS]

            # Fetch facts: specific IDs if provided, otherwise approved facts with a non-deleted fallback.
            fact_rows = []
            if fact_ids:
                facts_result = session.execute(
                    select(Fact).where(
                        Fact.case_id == uuid.UUID(case_id),
                        Fact.id.in_([uuid.UUID(fid) for fid in fact_ids]),
                        Fact.is_deleted == False,
                    ).limit(settings.DRAFT_MAX_FACTS * 2)
                )
                fact_rows = facts_result.scalars().all()
            else:
                facts_result = session.execute(
                    select(Fact).where(
                        Fact.case_id == uuid.UUID(case_id),
                        Fact.status == FactStatus.lawyer_approved,
                        Fact.is_deleted == False,
                    )
                    .order_by(Fact.confidence_score.desc(), Fact.updated_at.desc())
                    .limit(settings.DRAFT_MAX_FACTS * 2)
                )
                fact_rows = facts_result.scalars().all()
                if not fact_rows:
                    facts_result = session.execute(
                        select(Fact).where(
                            Fact.case_id == uuid.UUID(case_id),
                            Fact.is_deleted == False,
                        )
                        .order_by(Fact.confidence_score.desc(), Fact.updated_at.desc())
                        .limit(settings.DRAFT_MAX_FACTS * 2)
                    )
                    fact_rows = facts_result.scalars().all()
            fact_rows = fact_rows[: settings.DRAFT_MAX_FACTS]
            facts = [_fact_to_prompt_dict(f) for f in fact_rows]

            if not facts:
                if agent_task:
                    _mark_failed(agent_task, {"error": "no facts", "case_id": case_id}, started_at, "no facts")
                    session.commit()
                return {"error": "no facts", "case_id": case_id}

            source_document_ids = {fact.source_document_id for fact in fact_rows if fact.source_document_id}
            documents_by_id = {}
            if source_document_ids:
                doc_result = session.execute(
                    select(Document).where(
                        Document.case_id == uuid.UUID(case_id),
                        Document.id.in_(source_document_ids),
                    )
                )
                documents_by_id = {doc.id: doc for doc in doc_result.scalars().all()}
            fact_refs, document_refs = _draft_reference_payload(fact_rows, documents_by_id, doc_type_labels)

            # Fetch knowledge items if specified
            knowledge_content = []
            if knowledge_ids:
                ki_result = session.execute(
                    select(KnowledgeItem).where(KnowledgeItem.id.in_([uuid.UUID(k) for k in knowledge_ids]))
                )
                for ki in ki_result.scalars().all():
                    knowledge_content.append({
                        "title": ki.title,
                        "type": ki.item_type,
                        "content": _truncate_text(ki.content, settings.DRAFT_MAX_KNOWLEDGE_CHARS),
                    })
            # Historical full drafts are intentionally not injected automatically.
            # Older same-case drafts can carry a filing-letter structure that overrides
            # the lawyer's current custom format request. Lawyers can still select
            # knowledge-base templates explicitly when they want a prior structure.
            history_refs: list[dict] = []

            org = session.get(Organization, case.org_id)
            org_settings = org.settings if org and org.settings else {}

            # Generate one main draft with lawyer-selected strategy.
            agent = DraftGenerationAgent(llm=LLMService(
                provider=org_settings.get("llm_provider"),
                api_key=org_settings.get("api_key"),
                base_url=org_settings.get("llm_base_url"),
                model=org_settings.get("llm_model"),
            ))
            content = _run_async(agent.generate_draft(
                facts=facts,
                case_type=case.case_type.value if hasattr(case.case_type, 'value') else str(case.case_type),
                draft_title=draft_title,
                user_prompt=user_prompt,
                strategy=strategy,
                knowledge_refs=knowledge_content,
            ))
            if not _worker_may_continue(session, agent_task):
                logger.info("agent_task_skip_released_after_llm type=generate_drafts task_id=%s case_id=%s", agent_task_id, case_id)
                return {"case_id": case_id, "skipped": "agent task already released"}
            drafts = {"main": content}
            draft_titles: list[str] = []

            # Persist each version as one full draft instead of splitting it into paragraph/section cards.
            for version, content in drafts.items():
                title, body = _full_draft_from_content(content, draft_title=draft_title)
                draft_titles.append(title)
                reference_appendix = _format_draft_reference_appendix(fact_refs, document_refs)
                if reference_appendix:
                    body = body.rstrip() + "\n\n" + reference_appendix
                section = DraftSection(
                    case_id=uuid.UUID(case_id),
                    section_order=1,
                    section_title=title,
                    content=body,
                    version=version,
                    status=SectionStatus.draft,
                )
                session.add(section)
                session.flush()
                session.add(DraftRevision(
                    section_id=section.id,
                    case_id=section.case_id,
                    revision_number=1,
                    section_title=section.section_title,
                    content_snapshot=section.content,
                    editor_role="agent",
                    editor_id=None,
                    change_summary="Initial AI generation",
                    revision_metadata={
                        "agent_task_id": agent_task_id,
                        "history_ref_count": len(history_refs),
                        "fact_refs": fact_refs,
                        "document_refs": document_refs,
                    },
                ))

            # Mark agent task complete
            _mark_completed(
                agent_task,
                {
                    "versions": list(drafts.keys()),
                    "draft_name": draft_titles[0] if draft_titles else draft_title,
                    "draft_titles": draft_titles,
                    "fact_count": len(facts),
                    "fact_refs": fact_refs,
                    "document_refs": document_refs,
                    "history_ref_count": len(history_refs),
                    "knowledge_ref_count": len(knowledge_content),
                },
                started_at,
            )
            session.commit()
            _invalidate_case_runtime_cache(case_id)
            logger.info("agent_task_done type=generate_drafts task_id=%s case_id=%s fact_count=%s", agent_task_id, case_id, len(facts))

            return {"case_id": case_id, "versions": list(drafts.keys()), "fact_count": len(facts)}

    except Exception as exc:
        final = self.request.retries >= self.max_retries
        _record_agent_task_error(agent_task_id, exc, started_at, final=final)
        logger.exception("agent_task_error type=generate_drafts task_id=%s case_id=%s final=%s", agent_task_id, case_id, final)
        countdown = min(90, 10 * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=countdown)
    finally:
        engine.dispose()


@celery_app.task(
    bind=True,
    max_retries=3,
    name="app.workers.agent_tasks.rewrite_section",
)
def rewrite_section(self, section_id: str, instruction: str, case_id: str, agent_task_id: str):
    """
    Rewrite a single draft section using a Redis distributed lock.
    Implements segment-level concurrency control.
    """
    from app.models.draft import DraftRevision, DraftSection, SectionStatus
    from app.models.agent_task import AgentTask
    from app.models.fact import Fact, FactStatus
    from app.models.case import Case
    from app.models.organization import Organization
    from app.models.knowledge import KnowledgeItem
    from app.agents.draft_generator import DraftGenerationAgent
    from app.llm.provider import LLMService
    from sqlalchemy import select

    lock_key = f"section:{case_id}:{section_id}:lock"

    # Acquire distributed lock
    acquired = redis_client.set(lock_key, agent_task_id, nx=True, ex=SECTION_LOCK_TTL)
    if not acquired:
        # Another task holds the lock — retry after 5s
        raise self.retry(countdown=5, max_retries=12)

    started_at = time.perf_counter()
    logger.info("agent_task_start type=rewrite_section task_id=%s case_id=%s section_id=%s", agent_task_id, case_id, section_id)
    engine, session = _get_db_session()
    try:
        with session:
            agent_task = session.get(AgentTask, uuid.UUID(agent_task_id))
            if not _mark_processing(agent_task):
                logger.info("agent_task_skip_released type=rewrite_section task_id=%s case_id=%s section_id=%s", agent_task_id, case_id, section_id)
                return {"section_id": section_id, "skipped": "agent task already released"}
            session.commit()

            section = session.get(DraftSection, uuid.UUID(section_id))
            if not section:
                if agent_task:
                    _mark_failed(agent_task, {"error": "section not found", "section_id": section_id}, started_at, "section not found")
                    session.commit()
                return {"error": "section not found"}

            input_params = (agent_task.input_params or {}) if agent_task else {}
            fact_ids = input_params.get("fact_ids", [])
            knowledge_ids = input_params.get("knowledge_ids", [])
            strategy = input_params.get("strategy", "strongest_first")

            if fact_ids:
                facts_result = session.execute(
                    select(Fact).where(
                        Fact.case_id == uuid.UUID(case_id),
                        Fact.id.in_([uuid.UUID(fid) for fid in fact_ids]),
                        Fact.is_deleted == False,
                    )
                )
                fact_rows = facts_result.scalars().all()
            else:
                facts_result = session.execute(
                    select(Fact).where(
                        Fact.case_id == uuid.UUID(case_id),
                        Fact.status == FactStatus.lawyer_approved,
                        Fact.is_deleted == False,
                    ).limit(20)
                )
                fact_rows = facts_result.scalars().all()
                if not fact_rows:
                    facts_result = session.execute(
                        select(Fact).where(
                            Fact.case_id == uuid.UUID(case_id),
                            Fact.is_deleted == False,
                        ).limit(20)
                    )
                    fact_rows = facts_result.scalars().all()

            facts = [_fact_to_prompt_dict(f) for f in fact_rows]

            knowledge_content = []
            if knowledge_ids:
                ki_result = session.execute(
                    select(KnowledgeItem).where(KnowledgeItem.id.in_([uuid.UUID(k) for k in knowledge_ids]))
                )
                for ki in ki_result.scalars().all():
                    knowledge_content.append({
                        "title": ki.title,
                        "type": ki.item_type,
                        "content": ki.content,
                    })
            # Do not automatically inject unrelated historical drafts into rewrites;
            # the current section plus explicit knowledge selections are enough context.
            history_refs: list[dict] = []

            case = session.get(Case, uuid.UUID(case_id))
            org = session.get(Organization, case.org_id) if case else None
            org_settings = org.settings if org and org.settings else {}

            # Rewrite via agent
            agent = DraftGenerationAgent(llm=LLMService(
                provider=org_settings.get("llm_provider"),
                api_key=org_settings.get("api_key"),
                base_url=org_settings.get("llm_base_url"),
                model=org_settings.get("llm_model"),
            ))
            new_content = _run_async(agent.rewrite_section(
                original_content=section.content,
                instruction=instruction,
                relevant_facts=facts,
                strategy=strategy,
                knowledge_refs=knowledge_content,
            ))
            if not _worker_may_continue(session, agent_task):
                logger.info("agent_task_skip_released_after_llm type=rewrite_section task_id=%s case_id=%s section_id=%s", agent_task_id, case_id, section_id)
                return {"section_id": section_id, "skipped": "agent task already released"}

            old_content = section.content
            revision_result = session.execute(
                select(DraftRevision.revision_number)
                .where(DraftRevision.section_id == section.id)
                .order_by(DraftRevision.revision_number.desc())
                .limit(1)
            )
            last_revision_number = revision_result.scalar_one_or_none() or 0
            session.add(DraftRevision(
                section_id=section.id,
                case_id=section.case_id,
                revision_number=last_revision_number + 1,
                section_title=section.section_title,
                content_snapshot=old_content,
                editor_role="agent",
                editor_id=None,
                change_summary=f"Agent rewrite: {instruction[:100]}",
                revision_metadata={"agent_task_id": agent_task_id},
            ))
            section.content = new_content
            section.status = SectionStatus.draft

            _mark_completed(
                agent_task,
                {
                    "section_id": section_id,
                    "instruction": instruction,
                    "strategy": strategy,
                    "history_ref_count": len(history_refs),
                },
                started_at,
            )

            session.commit()
            _invalidate_case_runtime_cache(case_id)

            # Notify via Redis pub/sub for WebSocket push
            redis_client.publish(
                f"case:{case_id}:updates",
                json.dumps({
                    "type": "section_updated",
                    "section_id": section_id,
                    "version": section.version,
                })
            )

            logger.info("agent_task_done type=rewrite_section task_id=%s case_id=%s section_id=%s", agent_task_id, case_id, section_id)
            return {"section_id": section_id, "status": "rewritten"}

    except Exception as exc:
        final = self.request.retries >= self.max_retries
        _record_agent_task_error(agent_task_id, exc, started_at, final=final)
        logger.exception("agent_task_error type=rewrite_section task_id=%s case_id=%s section_id=%s final=%s", agent_task_id, case_id, section_id, final)
        raise self.retry(exc=exc)
    finally:
        redis_client.delete(lock_key)  # Release lock
        engine.dispose()


@celery_app.task(
    bind=True,
    max_retries=3,
    name="app.workers.agent_tasks.fix_fact",
    queue="p0_fact_fix",
)
def fix_fact(self, case_id: str, fact_id: str, old_value: str, new_value: str):
    """
    P0 priority: update all draft sections that reference a corrected fact.
    Triggered when a fact is disputed or corrected.
    """
    from app.models.draft import DraftSection
    from sqlalchemy import select

    engine, session = _get_db_session()
    try:
        with session:
            sections = session.execute(
                select(DraftSection).where(DraftSection.case_id == uuid.UUID(case_id))
            ).scalars().all()

            updated = 0
            for section in sections:
                if old_value.lower() in section.content.lower():
                    section.content = section.content.replace(old_value, new_value)
                    updated += 1

            session.commit()
            _invalidate_case_runtime_cache(case_id)

            # Publish update event
            redis_client.publish(
                f"case:{case_id}:updates",
                json.dumps({"type": "fact_fixed", "fact_id": fact_id, "sections_updated": updated})
            )
            return {"fact_id": fact_id, "sections_updated": updated}

    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        engine.dispose()


@celery_app.task(
    bind=True,
    max_retries=2,
    name="app.workers.agent_tasks.reparse_fact",
)
def reparse_fact(self, case_id: str, fact_id: str, agent_task_id: str):
    """Reparse one disputed fact in the background and record detailed diagnostics."""
    from app.models.agent_task import AgentTask
    from app.models.fact import Fact, FactStatus
    from app.models.case import Case
    from app.models.organization import Organization
    from app.models.knowledge import KnowledgeItem
    from app.llm.provider import LLMService
    from app.utils.timezone import local_iso, local_now
    from sqlalchemy import select

    started_at = time.perf_counter()
    logger.info("agent_task_start type=reparse_fact task_id=%s case_id=%s fact_id=%s", agent_task_id, case_id, fact_id)
    engine, session = _get_db_session()
    try:
        with session:
            agent_task = session.get(AgentTask, uuid.UUID(agent_task_id))
            if not _mark_processing(agent_task):
                logger.info("agent_task_skip_released type=reparse_fact task_id=%s case_id=%s fact_id=%s", agent_task_id, case_id, fact_id)
                return {"fact_id": fact_id, "skipped": "agent task already released"}
            session.commit()

            fact = session.get(Fact, uuid.UUID(fact_id))
            if not fact:
                if agent_task:
                    _mark_failed(agent_task, {"error": "fact not found", "fact_id": fact_id}, started_at, "fact not found")
                    session.commit()
                return {"error": "fact not found", "fact_id": fact_id}

            input_params = dict(agent_task.input_params or {}) if agent_task else {}
            dispute_comment = str(input_params.get("comment") or "").strip()
            original_content = str(input_params.get("original_content") or fact.content or "")
            knowledge_ids = [str(item_id) for item_id in (input_params.get("knowledge_ids") or [])]
            user_id = input_params.get("user_id")

            knowledge_refs: list[dict] = []
            if knowledge_ids:
                filters = [
                    KnowledgeItem.id.in_([uuid.UUID(item_id) for item_id in knowledge_ids]),
                    KnowledgeItem.is_deleted == False,
                    KnowledgeItem.item_type.in_(["prompt_template", "agent_strategy"]),
                ]
                if user_id:
                    filters.append(KnowledgeItem.user_id == uuid.UUID(str(user_id)))
                result = session.execute(select(KnowledgeItem).where(*filters))
                for item in result.scalars().all():
                    knowledge_refs.append({
                        "id": str(item.id),
                        "title": item.title,
                        "type": item.item_type,
                        "content": _truncate_text(item.content, 2000),
                    })

            source_context = _source_document_text(fact, session)
            source_text = source_context["text"]
            doc_name = source_context["document_name"] or (fact.structured_data or {}).get("document_name", "未知文档")
            source_diagnostics = {
                "document_name": doc_name,
                **source_context["diagnostics"],
                "source_text_chars": len(source_text or ""),
            }

            source_section = source_text or (
                "The original document text is not available. Use only the original extracted fact, structured metadata, and lawyer correction below."
            )
            resume_reparse_rules = ""
            if _looks_like_resume_context(fact, doc_name, source_text):
                resume_reparse_rules = """

Resume/CV reparse rules:
- Treat resume/CV entries as objective facts, not as weak background details.
- If the lawyer points to an education, employment, publication, patent, award, membership, service, project, or metric entry, preserve the concrete date, title, organization, venue, number, and source wording when available.
- Revise this single fact precisely; do not replace it with a broad career summary.
- Do not add an immigration legal conclusion unless the lawyer specifically asks for one."""

            knowledge_section = ""
            if knowledge_refs:
                parts = [
                    f"--- {item['title']} ({item['type']}) ---\n{item['content']}"
                    for item in knowledge_refs
                ]
                knowledge_section = "\n\nLawyer-selected parsing prompt and agent strategy references:\n" + "\n\n".join(parts)

            prompt = f"""A lawyer disputed an extracted immigration case fact. Re-parse the source context and revise the fact according to the lawyer's comment.

Source document: {doc_name}
Fact category: {fact.category}
Source document text or available source context:
{source_section}
{knowledge_section}
{resume_reparse_rules}

Original extracted fact:
{original_content}

Lawyer dispute/comment:
{dispute_comment}

Return ONLY the revised fact content in 1-3 precise sentences. Do not add facts that are not supported by the source context, original fact, or lawyer correction."""

            case = session.get(Case, uuid.UUID(case_id))
            org = session.get(Organization, case.org_id) if case else None
            org_settings = org.settings if org and org.settings else {}
            fallback_used = False
            llm_error = None
            try:
                regenerated = _run_async(LLMService.from_org_settings(org_settings).generate(
                    prompt,
                    system="You are a careful legal fact extraction assistant. Revise extracted facts conservatively.",
                    temperature=0.2,
                    max_tokens=700,
                ))
            except Exception as exc:
                fallback_used = True
                llm_error = str(exc)
                regenerated = (
                    f"【基于异议重新生成】根据律师反馈「{dispute_comment}」，"
                    f"重新分析文档 '{doc_name}' 的内容：{fact.content} "
                    f"经修正后的事实描述已根据异议观点进行调整和补充。"
                )
            if not _worker_may_continue(session, agent_task):
                logger.info("agent_task_skip_released_after_llm type=reparse_fact task_id=%s case_id=%s fact_id=%s", agent_task_id, case_id, fact_id)
                return {"fact_id": fact_id, "skipped": "agent task already released"}

            structured = dict(fact.structured_data or {})
            structured["dispute_comment"] = dispute_comment
            structured["original_content"] = original_content
            structured["reparse_source"] = source_diagnostics
            structured["reparse_agent_task_id"] = agent_task_id
            structured["reparse_completed_at"] = local_iso(local_now())
            if knowledge_refs:
                structured["reparse_knowledge_refs"] = [
                    {"id": item["id"], "title": item["title"], "type": item["type"]}
                    for item in knowledge_refs
                ]
            if llm_error:
                structured["reparse_llm_error"] = llm_error[:500]

            fact.content = regenerated
            fact.structured_data = structured
            fact.status = FactStatus.extracted

            output_result = {
                "fact_id": fact_id,
                "fact_category": fact.category,
                "source_document": doc_name,
                "reparse_source": source_diagnostics,
                "knowledge_ref_count": len(knowledge_refs),
                "knowledge_refs": [
                    {"id": item["id"], "title": item["title"], "type": item["type"]}
                    for item in knowledge_refs
                ],
                "comment_chars": len(dispute_comment),
                "source_text_chars": len(source_text or ""),
                "prompt_chars": len(prompt),
                "fallback_used": fallback_used,
                "llm_error": llm_error[:500] if llm_error else None,
                "original_content": _truncate_text(original_content, 800),
                "new_content": _truncate_text(regenerated, 1200),
            }
            _mark_completed(agent_task, output_result, started_at)
            session.commit()
            _invalidate_case_runtime_cache(case_id)
            redis_client.publish(
                f"case:{case_id}:updates",
                json.dumps({"type": "fact_reparsed", "fact_id": fact_id, "task_id": agent_task_id}),
            )
            logger.info("agent_task_done type=reparse_fact task_id=%s case_id=%s fact_id=%s", agent_task_id, case_id, fact_id)
            return {"fact_id": fact_id, "status": "reparsed", "fallback_used": fallback_used}

    except Exception as exc:
        final = self.request.retries >= self.max_retries
        _record_agent_task_error(agent_task_id, exc, started_at, final=final)
        logger.exception("agent_task_error type=reparse_fact task_id=%s case_id=%s fact_id=%s final=%s", agent_task_id, case_id, fact_id, final)
        countdown = min(60, 10 * (2 ** self.request.retries))
        raise self.retry(exc=exc, countdown=countdown)
    finally:
        engine.dispose()


def _split_into_sections(content: str, draft_title: str = "") -> list[tuple[str, str]]:
    """
    Split generated draft content into sections based on headers.
    Returns list of (title, body) tuples.
    """
    import re

    def clean_title(value: str) -> str:
        value = value.strip()
        value = re.sub(r"^#{1,6}\s+", "", value)
        value = re.sub(r"^\*\*(.+)\*\*$", r"\1", value)
        value = re.sub(r"^(?:title|document title|petition title)[:：]\s*", "", value, flags=re.IGNORECASE)
        return value.strip(" \t:-–—")

    def looks_like_document_title(value: str) -> bool:
        title = clean_title(value)
        lower = title.lower()
        if not title or len(title) > 140:
            return False
        if lower in {"introduction", "background", "summary", "conclusion"}:
            return False
        if re.match(r"^(?:[ivx]+\.\s+|criterion\s+\d+)", lower, re.IGNORECASE):
            return False
        return any(token in lower for token in ("petition", "letter", "brief", "application", "申请", "文案"))

    content = strip_think_tags(content)
    lines = content.split('\n')

    document_title = clean_title(draft_title)
    first_content_idx = next((idx for idx, line in enumerate(lines) if line.strip()), None)
    if first_content_idx is not None:
        first_line = lines[first_content_idx].strip()
        first_title = ""
        if re.match(r"^#\s+\S+", first_line):
            first_title = clean_title(first_line)
        elif re.match(r"^\*\*.+\*\*$", first_line) or re.match(r"^(?:title|document title|petition title)[:：]\s*", first_line, re.IGNORECASE):
            first_title = clean_title(first_line)
        elif looks_like_document_title(first_line):
            first_title = clean_title(first_line)

        if first_title:
            document_title = first_title
            del lines[first_content_idx]

    sections: list[tuple[str, str]] = []
    # Match headers like "I. INTRODUCTION", "## Summary", "CRITERION 1:", etc.
    pattern = r'^(?:#{1,3}\s+|[IVX]+\.\s+|CRITERION\s+\d+[:\.]?\s*)(.+)$'
    current_title = document_title or "Generated Draft"
    current_body: list[str] = []

    for line in lines:
        m = re.match(pattern, line.strip(), re.IGNORECASE)
        if m and len(line.strip()) < 120:
            next_title = clean_title(m.group(1))
            has_body = bool('\n'.join(current_body).strip())
            if has_body:
                sections.append((current_title, '\n'.join(current_body).strip()))
                current_title = next_title
                current_body = []
            elif document_title and not sections:
                current_body = [next_title, ""]
            else:
                current_title = next_title
        else:
            current_body.append(line)

    if current_body or not sections:
        sections.append((current_title, '\n'.join(current_body).strip()))

    return sections if sections else [("Generated Draft", content)]


def _full_draft_from_content(content: str, draft_title: str = "") -> tuple[str, str]:
    """
    Return a single full-draft title/body pair.

    The model may still include Markdown headings inside the draft for readability,
    but the product treats each generated version as one full draft item.
    """
    cleaned = _strip_reasoning_and_code_fences(content)
    lines = cleaned.splitlines()
    title = draft_title.strip()

    if lines:
        first = lines[0].strip()
        if first.startswith("# "):
            title = title or first.lstrip("#").strip()
            body = "\n".join(lines[1:]).strip()
            return title or "Generated Draft", body or cleaned

    return title or "Generated Draft", cleaned


def _strip_reasoning_and_code_fences(content: str) -> str:
    import re
    value = strip_think_tags(content)
    value = re.sub(r"^```(?:markdown|md|text)?\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\s*```\s*$", "", value).strip()
    return value

@celery_app.task(
    bind=True,
    max_retries=2,
    name="app.workers.agent_tasks.generate_rfi",
)
def generate_rfi(self, case_id: str, rfi_text: str, agent_task_id: str):
    """
    Generate RFI/RFE response letter using AI.
    """
    from app.models.agent_task import AgentTask, AgentTaskStatus
    from app.models.fact import Fact, FactStatus
    from app.models.case import Case
    from app.models.organization import Organization
    from sqlalchemy import select
    from app.llm.provider import LLMService

    started_at = time.perf_counter()
    logger.info("agent_task_start type=generate_rfi task_id=%s case_id=%s", agent_task_id, case_id)
    engine, session = _get_db_session()
    try:
        with session:
            agent_task = session.get(AgentTask, uuid.UUID(agent_task_id))
            if not _mark_processing(agent_task):
                logger.info("agent_task_skip_released type=generate_rfi task_id=%s case_id=%s", agent_task_id, case_id)
                return {"case_id": case_id, "skipped": "agent task already released"}
            session.commit()

            facts_result = session.execute(
                select(Fact).where(
                    Fact.case_id == uuid.UUID(case_id),
                    Fact.status == FactStatus.lawyer_approved,
                ).limit(30)
            )
            facts = [{"category": f.category, "content": f.content} for f in facts_result.scalars().all()]
            facts_str = json.dumps(facts, ensure_ascii=False, indent=2)
            case = session.get(Case, uuid.UUID(case_id))
            org = session.get(Organization, case.org_id) if case else None
            org_settings = org.settings if org and org.settings else {}

            prompt = f"""
You are an expert US immigration lawyer. The USCIS has issued an RFI/RFE (Request for Evidence) for an EB-1A petition.
Please draft a professional, persuasive response letter addressing the USCIS's concerns.

RFI/RFE Text from USCIS:
{rfi_text}

Approved Case Facts:
{facts_str}

Please generate the response letter in markdown format.
"""
            # Call LLM
            response_content = _run_async(LLMService.from_org_settings(org_settings).generate(
                prompt=prompt,
                system_prompt="You are an expert US immigration lawyer.",
            ))

            # Save result (for simplicity, storing in agent_task output, in reality might be a new Document or DraftSection)
            _mark_completed(agent_task, {"rfi_response": response_content, "fact_count": len(facts)}, started_at)
            session.commit()
            _invalidate_case_runtime_cache(case_id)

            # Broadcast WS
            redis_client.publish(
                f"case:{case_id}",
                json.dumps({
                    "type": "rfi_generated",
                    "task_id": agent_task_id
                })
            )

            logger.info("agent_task_done type=generate_rfi task_id=%s case_id=%s fact_count=%s", agent_task_id, case_id, len(facts))
            return {"case_id": case_id, "status": "rfi_generated"}
    except Exception as exc:
        final = self.request.retries >= self.max_retries
        _record_agent_task_error(agent_task_id, exc, started_at, final=final)
        logger.exception("agent_task_error type=generate_rfi task_id=%s case_id=%s final=%s", agent_task_id, case_id, final)
        raise self.retry(exc=exc)
    finally:
        engine.dispose()
