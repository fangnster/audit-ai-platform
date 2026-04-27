from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_task import AgentTask
from app.models.case import Case, CaseMember
from app.models.document import Document, DocumentBlob, DocumentVersion
from app.models.draft import DraftRevision, DraftSection, LawyerTask, UserSession
from app.models.fact import Fact, FactCollaboration
from app.models.knowledge import KnowledgeItem
from app.models.organization import DocumentCategory, Organization, OrgMember, Team
from app.models.user import User
from app.routers.documents import legacy_local_storage_path, local_storage_path, storage_client, storage_key_candidates
from app.services.cache import delete_pattern
from app.config import settings


@dataclass
class DeleteSummary:
    cases_deleted: int = 0
    users_deleted: int = 0
    documents_deleted: int = 0
    files_deleted: int = 0
    knowledge_items_deleted: int = 0
    storage_errors: list[str] = field(default_factory=list)

    def merge(self, other: "DeleteSummary") -> None:
        self.cases_deleted += other.cases_deleted
        self.users_deleted += other.users_deleted
        self.documents_deleted += other.documents_deleted
        self.files_deleted += other.files_deleted
        self.knowledge_items_deleted += other.knowledge_items_deleted
        self.storage_errors.extend(other.storage_errors)

    def as_dict(self) -> dict:
        return {
            "cases_deleted": self.cases_deleted,
            "users_deleted": self.users_deleted,
            "documents_deleted": self.documents_deleted,
            "files_deleted": self.files_deleted,
            "knowledge_items_deleted": self.knowledge_items_deleted,
            "storage_errors": self.storage_errors,
        }


async def _execute_delete(db: AsyncSession, stmt) -> int:
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


def _delete_local_file(path: str) -> bool:
    if not os.path.exists(path):
        return False
    os.unlink(path)
    return True


def delete_stored_file(storage_path: str) -> tuple[int, list[str]]:
    """Best-effort deletion for both dev local fallback files and object storage."""
    deleted = 0
    errors: list[str] = []

    for path_builder in (local_storage_path, legacy_local_storage_path):
        try:
            if _delete_local_file(path_builder(storage_path)):
                deleted += 1
        except Exception as exc:
            errors.append(f"local:{storage_path}: {exc}")

    if settings.STORAGE_ENDPOINT_URL:
        try:
            s3 = storage_client()
        except Exception as exc:
            errors.append(f"object:{storage_path}: {exc}")
            return deleted, errors
        for key in storage_key_candidates(storage_path):
            try:
                s3.delete_object(Bucket=settings.STORAGE_BUCKET_NAME, Key=key)
                deleted += 1
            except Exception as exc:
                errors.append(f"object:{key}: {exc}")

    return deleted, errors


async def delete_documents_by_ids(db: AsyncSession, document_ids: list[uuid.UUID]) -> DeleteSummary:
    summary = DeleteSummary()
    if not document_ids:
        return summary

    docs = (await db.execute(select(Document).where(Document.id.in_(document_ids)))).scalars().all()
    if not docs:
        return summary

    for doc in docs:
        files_deleted, storage_errors = delete_stored_file(doc.storage_path)
        summary.files_deleted += files_deleted
        summary.storage_errors.extend(storage_errors)

    doc_ids = [doc.id for doc in docs]
    storage_paths = [doc.storage_path for doc in docs]
    if storage_paths:
        summary.files_deleted += await _execute_delete(
            db,
            sa_delete(DocumentBlob).where(DocumentBlob.storage_path.in_(storage_paths)),
        )
    await db.execute(update(Fact).where(Fact.source_document_id.in_(doc_ids)).values(source_document_id=None))
    await _execute_delete(db, sa_delete(DocumentVersion).where(DocumentVersion.document_id.in_(doc_ids)))
    summary.documents_deleted += await _execute_delete(db, sa_delete(Document).where(Document.id.in_(doc_ids)))
    return summary


async def delete_case_tree(db: AsyncSession, case_id: uuid.UUID) -> DeleteSummary:
    summary = DeleteSummary()
    case = await db.get(Case, case_id)
    if not case:
        return summary

    doc_ids = (await db.execute(select(Document.id).where(Document.case_id == case_id))).scalars().all()
    summary.merge(await delete_documents_by_ids(db, list(doc_ids)))

    fact_ids = (await db.execute(select(Fact.id).where(Fact.case_id == case_id))).scalars().all()
    if fact_ids:
        await _execute_delete(db, sa_delete(FactCollaboration).where(FactCollaboration.fact_id.in_(fact_ids)))
    await _execute_delete(db, sa_delete(Fact).where(Fact.case_id == case_id))

    await _execute_delete(db, sa_delete(DraftRevision).where(DraftRevision.case_id == case_id))
    await _execute_delete(db, sa_delete(DraftSection).where(DraftSection.case_id == case_id))
    await _execute_delete(db, sa_delete(LawyerTask).where(LawyerTask.case_id == case_id))
    await _execute_delete(db, sa_delete(AgentTask).where(AgentTask.case_id == case_id))
    await _execute_delete(db, sa_delete(UserSession).where(UserSession.case_id == case_id))
    await _execute_delete(db, sa_delete(CaseMember).where(CaseMember.case_id == case_id))
    summary.cases_deleted += await _execute_delete(db, sa_delete(Case).where(Case.id == case_id))

    await invalidate_case_related_caches(case_id)
    return summary


async def _cleanup_empty_org_shells(db: AsyncSession, org_ids: list[uuid.UUID]) -> None:
    for org_id in set(org_ids):
        member_count = await db.scalar(select(func.count()).select_from(OrgMember).where(OrgMember.org_id == org_id))
        case_count = await db.scalar(select(func.count()).select_from(Case).where(Case.org_id == org_id))
        knowledge_count = await db.scalar(select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.org_id == org_id))
        if member_count or case_count or knowledge_count:
            continue
        await _execute_delete(db, sa_delete(DocumentCategory).where(DocumentCategory.org_id == org_id))
        await _execute_delete(db, sa_delete(Team).where(Team.org_id == org_id))
        await _execute_delete(db, sa_delete(Organization).where(Organization.id == org_id))


async def delete_user_tree(db: AsyncSession, user_id: uuid.UUID) -> DeleteSummary:
    summary = DeleteSummary()
    user = await db.get(User, user_id)
    if not user:
        return summary

    lead_case_ids = (await db.execute(select(Case.id).where(Case.lead_lawyer_id == user_id))).scalars().all()
    for case_id in lead_case_ids:
        summary.merge(await delete_case_tree(db, case_id))

    remaining_doc_ids = (await db.execute(select(Document.id).where(Document.uploader_id == user_id))).scalars().all()
    summary.merge(await delete_documents_by_ids(db, list(remaining_doc_ids)))

    fact_ids = (await db.execute(select(FactCollaboration.fact_id).where(FactCollaboration.user_id == user_id))).scalars().all()
    await _execute_delete(db, sa_delete(FactCollaboration).where(FactCollaboration.user_id == user_id))
    if fact_ids:
        for fact_id in set(fact_ids):
            fact = await db.get(Fact, fact_id)
            if fact:
                await delete_pattern(f"facts:{fact.case_id}:*")

    await _execute_delete(db, sa_delete(DocumentVersion).where(DocumentVersion.editor_id == user_id))
    await _execute_delete(db, sa_delete(DraftRevision).where(DraftRevision.editor_id == user_id))
    await db.execute(update(LawyerTask).where(LawyerTask.approved_by_id == user_id).values(approved_by_id=None))
    await _execute_delete(db, sa_delete(LawyerTask).where(LawyerTask.created_by_id == user_id))

    summary.knowledge_items_deleted += await _execute_delete(
        db,
        sa_delete(KnowledgeItem).where(KnowledgeItem.user_id == user_id),
    )
    await _execute_delete(db, sa_delete(UserSession).where(UserSession.user_id == user_id))
    await _execute_delete(db, sa_delete(CaseMember).where(CaseMember.user_id == user_id))

    org_ids = (await db.execute(select(OrgMember.org_id).where(OrgMember.user_id == user_id))).scalars().all()
    await _execute_delete(db, sa_delete(OrgMember).where(OrgMember.user_id == user_id))
    await _cleanup_empty_org_shells(db, list(org_ids))

    summary.users_deleted += await _execute_delete(db, sa_delete(User).where(User.id == user_id))
    await invalidate_global_caches()
    return summary


async def invalidate_case_related_caches(case_id: uuid.UUID) -> None:
    await delete_pattern(f"documents:{case_id}:*")
    await delete_pattern(f"facts:{case_id}:*")
    await delete_pattern(f"drafts:{case_id}:*")
    await delete_pattern(f"tasks:{case_id}:*")
    await delete_pattern(f"agent-tasks:{case_id}:*")
    await invalidate_global_caches()


async def invalidate_global_caches() -> None:
    await delete_pattern("cases:*")
    await delete_pattern("cases:v2:*")
    await delete_pattern("admin:v1:*")
    await delete_pattern("knowledge:v1:*")
