"""Reconcile schema drift and add query-path indexes.

Revision ID: 005_reconcile_schema_indexes
Revises: 004_harden_knowledge_item_type
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = "005_reconcile_schema_indexes"
down_revision = "004_harden_knowledge_item_type"
branch_labels = None
depends_on = None


def _columns(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _add_bool_column_if_missing(inspector, table_name: str, column_name: str) -> None:
    if column_name in _columns(inspector, table_name):
        return
    op.add_column(
        table_name,
        sa.Column(column_name, sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def _drop_column_if_exists(inspector, table_name: str, column_name: str) -> None:
    if column_name in _columns(inspector, table_name):
        op.drop_column(table_name, column_name)


def _create_index_if_missing(inspector, table_name: str, index_name: str, columns: list) -> None:
    if index_name not in _indexes(inspector, table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # Align soft-delete columns used by the app but missing from older migrations.
    for table_name in ("cases", "documents", "facts", "draft_sections", "client_tasks"):
        if table_name in inspector.get_table_names():
            _add_bool_column_if_missing(inspector, table_name, "is_deleted")

    # Remove stale required client_id columns from early schema drafts. Client info now
    # lives in cases.metadata and tasks are case-scoped.
    if "cases" in inspector.get_table_names():
        if "idx_cases_client" in _indexes(inspector, "cases"):
            op.drop_index("idx_cases_client", table_name="cases")
        _drop_column_if_exists(inspector, "cases", "client_id")
    if "client_tasks" in inspector.get_table_names():
        if "idx_client_tasks_client_status" in _indexes(inspector, "client_tasks"):
            op.drop_index("idx_client_tasks_client_status", table_name="client_tasks")
        _drop_column_if_exists(inspector, "client_tasks", "client_id")

    # Query-path indexes for current routers/workers.
    if "case_members" in inspector.get_table_names():
        _create_index_if_missing(inspector, "case_members", "idx_case_members_user_case", ["user_id", "case_id"])
    if "documents" in inspector.get_table_names():
        _create_index_if_missing(
            inspector,
            "documents",
            "idx_documents_case_deleted_created",
            ["case_id", "is_deleted", sa.text("created_at DESC")],
        )
    if "facts" in inspector.get_table_names():
        _create_index_if_missing(
            inspector,
            "facts",
            "idx_facts_case_deleted_created",
            ["case_id", "is_deleted", sa.text("created_at DESC")],
        )
    if "draft_sections" in inspector.get_table_names():
        _create_index_if_missing(
            inspector,
            "draft_sections",
            "idx_draft_sections_case_deleted_version_order",
            ["case_id", "is_deleted", "version", "section_order"],
        )
    if "client_tasks" in inspector.get_table_names():
        _create_index_if_missing(inspector, "client_tasks", "idx_client_tasks_case_deleted", ["case_id", "is_deleted"])
    if "knowledge_items" in inspector.get_table_names():
        _create_index_if_missing(
            inspector,
            "knowledge_items",
            "idx_knowledge_items_org_deleted_type_updated",
            ["org_id", "is_deleted", "item_type", sa.text("updated_at DESC")],
        )
    if "agent_tasks" in inspector.get_table_names():
        _create_index_if_missing(
            inspector,
            "agent_tasks",
            "idx_agent_tasks_case_created",
            ["case_id", sa.text("created_at DESC")],
        )
    if "draft_revisions" in inspector.get_table_names():
        _create_index_if_missing(
            inspector,
            "draft_revisions",
            "idx_draft_revisions_case_created",
            ["case_id", sa.text("created_at DESC")],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    drop_indexes = {
        "case_members": ["idx_case_members_user_case"],
        "documents": ["idx_documents_case_deleted_created"],
        "facts": ["idx_facts_case_deleted_created"],
        "draft_sections": ["idx_draft_sections_case_deleted_version_order"],
        "client_tasks": ["idx_client_tasks_case_deleted"],
        "knowledge_items": ["idx_knowledge_items_org_deleted_type_updated"],
        "agent_tasks": ["idx_agent_tasks_case_created"],
        "draft_revisions": ["idx_draft_revisions_case_created"],
    }
    for table_name, index_names in drop_indexes.items():
        if table_name not in inspector.get_table_names():
            continue
        existing = _indexes(inspector, table_name)
        for index_name in index_names:
            if index_name in existing:
                op.drop_index(index_name, table_name=table_name)
