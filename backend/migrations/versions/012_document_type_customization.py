"""Allow customizable document types.

Revision ID: 012_document_type_customization
Revises: 011_add_user_firm_name
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "012_document_type_customization"
down_revision = "011_add_user_firm_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "documents" not in inspector.get_table_names():
        return

    op.alter_column(
        "documents",
        "doc_type",
        existing_nullable=False,
        type_=sa.String(length=100),
        postgresql_using="doc_type::text",
    )
    op.execute("DROP TYPE IF EXISTS doctype")


def downgrade() -> None:
    # Keep doc_type as varchar. Recreating the old enum would break user custom
    # document types and uploaded records that use them.
    pass
