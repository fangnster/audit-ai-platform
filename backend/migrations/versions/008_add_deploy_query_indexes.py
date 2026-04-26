"""Add deployment query indexes for cached list fallbacks.

Revision ID: 008_add_deploy_query_indexes
Revises: 007_add_updated_at_sort_indexes
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa


revision = "008_add_deploy_query_indexes"
down_revision = "007_add_updated_at_sort_indexes"
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

    if "documents" in tables:
        _create_index_if_missing(
            inspector,
            "documents",
            "idx_documents_case_deleted_type_created",
            ["case_id", "is_deleted", "doc_type", sa.text("created_at DESC")],
        )
        _create_index_if_missing(
            inspector,
            "documents",
            "idx_documents_case_deleted_uploader_created",
            ["case_id", "is_deleted", "uploader_role", sa.text("created_at DESC")],
        )
    if "facts" in tables:
        _create_index_if_missing(
            inspector,
            "facts",
            "idx_facts_source_document_deleted_created",
            ["source_document_id", "is_deleted", sa.text("created_at DESC")],
        )
    if "cases" in tables:
        _create_index_if_missing(
            inspector,
            "cases",
            "idx_cases_deleted_updated",
            ["is_deleted", sa.text("updated_at DESC")],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = _tables(inspector)
    drops = {
        "documents": [
            "idx_documents_case_deleted_type_created",
            "idx_documents_case_deleted_uploader_created",
        ],
        "facts": ["idx_facts_source_document_deleted_created"],
        "cases": ["idx_cases_deleted_updated"],
    }
    for table_name, index_names in drops.items():
        if table_name not in tables:
            continue
        for index_name in index_names:
            _drop_index_if_exists(inspector, table_name, index_name)
