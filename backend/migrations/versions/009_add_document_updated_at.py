"""Add updated_at to documents.

Revision ID: 009_add_document_updated_at
Revises: 008_add_deploy_query_indexes
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa


revision = "009_add_document_updated_at"
down_revision = "008_add_deploy_query_indexes"
branch_labels = None
depends_on = None


def _columns(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "documents" not in inspector.get_table_names():
        return

    if "updated_at" not in _columns(inspector, "documents"):
        op.add_column(
            "documents",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute("UPDATE documents SET updated_at = created_at WHERE updated_at IS NULL")
        op.alter_column("documents", "updated_at", server_default=sa.func.now())

    if "idx_documents_case_deleted_updated" not in _indexes(inspector, "documents"):
        op.create_index(
            "idx_documents_case_deleted_updated",
            "documents",
            ["case_id", "is_deleted", sa.text("updated_at DESC")],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "documents" not in inspector.get_table_names():
        return

    if "idx_documents_case_deleted_updated" in _indexes(inspector, "documents"):
        op.drop_index("idx_documents_case_deleted_updated", table_name="documents")
    if "updated_at" in _columns(inspector, "documents"):
        op.drop_column("documents", "updated_at")
