"""
Celery tasks: document parsing and fact extraction.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
import uuid

from app.config import settings
from app.workers.celery_app import celery_app
from app.services.cache import delete_pattern_sync
from app.utils.timezone import local_iso, local_now

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run async coroutine in Celery sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _category_counts(raw_facts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in raw_facts:
        category = str(item.get("category") or "other")
        counts[category] = counts.get(category, 0) + 1
    return counts


def _mark_agent_task(session, agent_task_id: str | None, *, status, output_result: dict | None = None,
                     error_message: str | None = None, started_at: float | None = None):
    if not agent_task_id:
        return None
    from app.models.agent_task import AgentTask

    try:
        agent_task = session.get(AgentTask, uuid.UUID(agent_task_id))
    except Exception:
        return None
    if not agent_task:
        return None
    agent_task.status = status
    if output_result is not None:
        agent_task.output_result = output_result
    agent_task.error_message = error_message[:1000] if error_message else None
    if started_at is not None:
        agent_task.latency_ms = int((time.perf_counter() - started_at) * 1000)
    return agent_task


def _status_value(status) -> str:
    return str(status.value if hasattr(status, "value") else status)


def _worker_may_continue(session, agent_task_id: str | None) -> bool:
    if not agent_task_id:
        return True
    from app.models.agent_task import AgentTask, AgentTaskStatus

    agent_task = session.get(AgentTask, uuid.UUID(agent_task_id))
    if not agent_task:
        return False
    return _status_value(agent_task.status) in {AgentTaskStatus.queued.value, AgentTaskStatus.processing.value}


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=settings.PARSE_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=settings.PARSE_TASK_TIME_LIMIT_SECONDS,
    name="app.workers.document_tasks.parse_document",
)
def parse_document(self, document_id: str, file_path: str, mime_type: str,
                   doc_type: str, case_type: str, case_id: str, lawyer_guidance: str = "",
                   agent_task_id: str | None = None):
    """
    Parse a document and extract facts into the DB.
    Triggered after a file is uploaded.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import sync_database_url
    from app.llm.provider import LLMService
    from app.models.case import Case
    from app.models.document import Document, ParseStatus
    from app.models.agent_task import AgentTaskStatus
    from app.models.fact import Fact, FactStatus
    from app.models.organization import Organization
    from app.agents.fact_extractor import DocumentTextExtractionError, FactExtractionAgent
    from app.routers.documents import read_document_bytes

    # Use sync engine for Celery
    engine = create_engine(sync_database_url())

    agent = None
    temp_path = ""
    started_at = time.perf_counter()
    try:
        with Session(engine) as session:
            doc = session.get(Document, uuid.UUID(document_id))
            if not doc:
                logger.error(f"Document {document_id} not found")
                _mark_agent_task(
                    session,
                    agent_task_id,
                    status=AgentTaskStatus.failed,
                    output_result={"document_id": document_id, "error": "document not found"},
                    error_message="document not found",
                    started_at=started_at,
                )
                session.commit()
                return {"error": "document not found"}

            if not _worker_may_continue(session, agent_task_id):
                logger.info("parse_document_skip_released task_id=%s document_id=%s", agent_task_id, document_id)
                return {"document_id": document_id, "skipped": "agent task already released"}

            # Mark as parsing
            doc.parse_status = ParseStatus.parsing
            _mark_agent_task(session, agent_task_id, status=AgentTaskStatus.processing)
            session.commit()
            delete_pattern_sync(f"documents:{case_id}:*")
            delete_pattern_sync(f"tasks:{case_id}:*")
            delete_pattern_sync(f"agent-tasks:{case_id}:*")
            delete_pattern_sync("admin:v1:*")

            case = session.get(Case, uuid.UUID(case_id))
            org = session.get(Organization, case.org_id) if case else None
            org_settings = org.settings if org and org.settings else {}

            parse_path = file_path
            if not parse_path or not os.path.exists(parse_path):
                content = read_document_bytes(doc)
                suffix = os.path.splitext(doc.original_filename or "")[1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    temp_path = tmp.name
                    tmp.write(content)
                parse_path = temp_path

            # Extract facts (sync wrapper around async agent)
            agent = FactExtractionAgent(llm=LLMService.from_org_settings(org_settings))
            raw_facts = _run_async(agent.extract_facts(
                file_path=parse_path,
                mime_type=mime_type,
                doc_type=doc_type,
                case_type=case_type,
                lawyer_guidance=lawyer_guidance,
                document_name=doc.original_filename or doc.filename,
            ))

            if not _worker_may_continue(session, agent_task_id):
                logger.info("parse_document_skip_released_after_llm task_id=%s document_id=%s", agent_task_id, document_id)
                return {"document_id": document_id, "skipped": "agent task already released"}

            # Persist facts
            inserted = 0
            for f in raw_facts:
                structured = dict(f.get("structured_data") or {})
                structured.setdefault("document_name", doc.original_filename or doc.filename)
                if lawyer_guidance:
                    structured["parse_prompt"] = lawyer_guidance
                fact = Fact(
                    case_id=uuid.UUID(case_id),
                    source_document_id=uuid.UUID(document_id),
                    category=f.get("category", "other"),
                    content=f.get("content", ""),
                    structured_data=structured,
                    confidence_score=float(f.get("confidence_score", 1.0)),
                    status=FactStatus.extracted,
                )
                session.add(fact)
                inserted += 1

            diagnostics = dict(agent.last_diagnostics or {})
            output_result = {
                "document_id": document_id,
                "document_name": doc.original_filename or doc.filename,
                "doc_type": doc_type,
                "case_type": case_type,
                "facts_extracted": inserted,
                "fact_categories": _category_counts(raw_facts),
                "prompt_used": bool(lawyer_guidance),
                "prompt_chars": len(lawyer_guidance or ""),
                "diagnostics": diagnostics,
                "warning": diagnostics.get("warning") or ("readable_text_short" if diagnostics.get("text_quality") == "short" else None),
            }
            doc.parse_status = ParseStatus.parsed
            doc.extracted_metadata = {
                "fact_count": inserted,
                "mode": "llm_background_trigger",
                "prompt": lawyer_guidance or None,
                "parsed_at": local_iso(local_now()),
                "diagnostics": diagnostics,
                "warning": output_result["warning"],
            }
            _mark_agent_task(
                session,
                agent_task_id,
                status=AgentTaskStatus.completed,
                output_result=output_result,
                started_at=started_at,
            )
            session.commit()
            delete_pattern_sync(f"documents:{case_id}:*")
            delete_pattern_sync(f"facts:{case_id}:*")
            delete_pattern_sync(f"tasks:{case_id}:*")
            delete_pattern_sync(f"agent-tasks:{case_id}:*")
            delete_pattern_sync("admin:v1:*")

            logger.info(f"Parsed doc {document_id}: {inserted} facts extracted")
            return {"document_id": document_id, "facts_extracted": inserted}

    except DocumentTextExtractionError as exc:
        logger.error(f"parse_document text extraction failed for {document_id}: {exc}")
        try:
            with Session(engine) as session:
                doc = session.get(Document, uuid.UUID(document_id))
                if doc:
                    doc.parse_status = ParseStatus.failed
                    diagnostics = dict(agent.last_diagnostics or {}) if agent else {}
                    doc.extracted_metadata = {
                        "fact_count": 0,
                        "mode": "llm_background_trigger",
                        "prompt": lawyer_guidance or None,
                        "parsed_at": local_iso(local_now()),
                        "diagnostics": diagnostics,
                        "error": str(exc),
                    }
                    _mark_agent_task(
                        session,
                        agent_task_id,
                        status=AgentTaskStatus.failed,
                        output_result={
                            "document_id": document_id,
                            "document_name": doc.original_filename or doc.filename,
                            "doc_type": doc_type,
                            "facts_extracted": 0,
                            "diagnostics": diagnostics,
                            "error": str(exc),
                        },
                        error_message=str(exc),
                        started_at=started_at,
                    )
                    session.commit()
                    delete_pattern_sync(f"documents:{case_id}:*")
                    delete_pattern_sync(f"tasks:{case_id}:*")
                    delete_pattern_sync(f"agent-tasks:{case_id}:*")
                    delete_pattern_sync("admin:v1:*")
        except Exception:
            pass
        return {"document_id": document_id, "error": str(exc)}
    except Exception as exc:
        logger.error(f"parse_document failed for {document_id}: {exc}")
        # Mark as failed
        try:
            with Session(engine) as session:
                doc = session.get(Document, uuid.UUID(document_id))
                if doc:
                    doc.parse_status = ParseStatus.failed
                    final = self.request.retries >= self.max_retries
                    _mark_agent_task(
                        session,
                        agent_task_id,
                        status=AgentTaskStatus.failed if final else AgentTaskStatus.queued,
                        output_result={
                            "document_id": document_id,
                            "document_name": doc.original_filename or doc.filename,
                            "doc_type": doc_type,
                            "facts_extracted": 0,
                            "diagnostics": dict(agent.last_diagnostics or {}) if agent else {},
                            "error": str(exc),
                        },
                        error_message=str(exc),
                        started_at=started_at,
                    )
                    session.commit()
                    delete_pattern_sync(f"documents:{case_id}:*")
                    delete_pattern_sync(f"tasks:{case_id}:*")
                    delete_pattern_sync(f"agent-tasks:{case_id}:*")
                    delete_pattern_sync("admin:v1:*")
        except Exception:
            pass
        raise self.retry(exc=exc)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
        engine.dispose()
