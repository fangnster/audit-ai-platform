"""Add database fallback for uploaded document bytes.

Revision ID: 014_document_blob_fallback
Revises: 013_database_cache_indexes
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "014_document_blob_fallback"
down_revision = "013_database_cache_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "document_blobs" in inspector.get_table_names():
        return

    op.create_table(
        "document_blobs",
        sa.Column("storage_path", sa.String(length=1000), primary_key=True, nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "document_blobs" in inspector.get_table_names():
        op.drop_table("document_blobs")
