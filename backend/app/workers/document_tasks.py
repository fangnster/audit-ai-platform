"""
Celery tasks: document parsing and fact extraction.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

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


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="app.workers.document_tasks.parse_document",
)
def parse_document(self, document_id: str, file_path: str, mime_type: str,
                   doc_type: str, case_type: str, case_id: str, lawyer_guidance: str = ""):
    """
    Parse a document and extract facts into the DB.
    Triggered after a file is uploaded.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.config import settings
    from app.llm.provider import LLMService
    from app.models.case import Case
    from app.models.document import Document, ParseStatus
    from app.models.fact import Fact, FactStatus
    from app.models.organization import Organization
    from app.agents.fact_extractor import FactExtractionAgent

    # Use sync engine for Celery
    sync_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    engine = create_engine(sync_url)

    try:
        with Session(engine) as session:
            doc = session.get(Document, uuid.UUID(document_id))
            if not doc:
                logger.error(f"Document {document_id} not found")
                return {"error": "document not found"}

            # Mark as parsing
            doc.parse_status = ParseStatus.parsing
            session.commit()
            delete_pattern_sync(f"documents:{case_id}:*")

            case = session.get(Case, uuid.UUID(case_id))
            org = session.get(Organization, case.org_id) if case else None
            org_settings = org.settings if org and org.settings else {}

            # Extract facts (sync wrapper around async agent)
            agent = FactExtractionAgent(llm=LLMService.from_org_settings(org_settings))
            raw_facts = _run_async(agent.extract_facts(
                file_path=file_path,
                mime_type=mime_type,
                doc_type=doc_type,
                case_type=case_type,
                lawyer_guidance=lawyer_guidance,
            ))

            # Persist facts
            inserted = 0
            for f in raw_facts:
                fact = Fact(
                    case_id=uuid.UUID(case_id),
                    source_document_id=uuid.UUID(document_id),
                    category=f.get("category", "other"),
                    content=f.get("content", ""),
                    structured_data=f.get("structured_data", {}),
                    confidence_score=float(f.get("confidence_score", 1.0)),
                    status=FactStatus.extracted,
                )
                session.add(fact)
                inserted += 1

            doc.parse_status = ParseStatus.parsed
            doc.extracted_metadata = {"fact_count": inserted, "parsed_at": local_iso(local_now())}
            session.commit()
            delete_pattern_sync(f"documents:{case_id}:*")
            delete_pattern_sync(f"facts:{case_id}:*")

            logger.info(f"Parsed doc {document_id}: {inserted} facts extracted")
            return {"document_id": document_id, "facts_extracted": inserted}

    except Exception as exc:
        logger.error(f"parse_document failed for {document_id}: {exc}")
        # Mark as failed
        try:
            with Session(engine) as session:
                doc = session.get(Document, uuid.UUID(document_id))
                if doc:
                    doc.parse_status = ParseStatus.failed
                    session.commit()
                    delete_pattern_sync(f"documents:{case_id}:*")
        except Exception:
            pass
        raise self.retry(exc=exc)
    finally:
        engine.dispose()
