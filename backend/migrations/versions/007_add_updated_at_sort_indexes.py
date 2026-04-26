"""Add updated-at indexes for sortable work lists.

Revision ID: 007_add_updated_at_sort_indexes
Revises: 006_normalize_schema_metadata
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa


revision = "007_add_updated_at_sort_indexes"
down_revision = "006_normalize_schema_metadata"
branch_labels = None
depends_on = None


def _tables(inspector) -> set[str]:
    return set(inspector.get_table_names())


def _indexes(inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _create_index_if_missing(inspector, table_name: str, index_name: str, columns: list) -> None:
    if index_name not in _indexes(inspector, table_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(inspector, table_name: str, index_name: str) -> None:
    if index_name in _indexes(inspector, table_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = _tables(inspector)

    if "facts" in tables:
        _create_index_if_missing(
            inspector,
            "facts",
            "idx_facts_case_deleted_updated",
            ["case_id", "is_deleted", sa.text("updated_at DESC")],
        )
    if "draft_sections" in tables:
        _create_index_if_missing(
            inspector,
            "draft_sections",
            "idx_draft_sections_case_deleted_updated",
            ["case_id", "is_deleted", sa.text("updated_at DESC")],
        )
    if "client_tasks" in tables:
        _create_index_if_missing(
            inspector,
            "client_tasks",
            "idx_client_tasks_case_deleted_updated",
            ["case_id", "is_deleted", sa.text("updated_at DESC")],
        )
    if "agent_tasks" in tables:
        _create_index_if_missing(
            inspector,
            "agent_tasks",
            "idx_agent_tasks_case_updated",
            ["case_id", sa.text("updated_at DESC")],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = _tables(inspector)
    drops = {
        "facts": ["idx_facts_case_deleted_updated"],
        "draft_sections": ["idx_draft_sections_case_deleted_updated"],
        "client_tasks": ["idx_client_tasks_case_deleted_updated"],
        "agent_tasks": ["idx_agent_tasks_case_updated"],
    }
    for table_name, index_names in drops.items():
        if table_name not in tables:
            continue
        for index_name in index_names:
            _drop_index_if_exists(inspector, table_name, index_name)
