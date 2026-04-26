"""Harden knowledge item type storage.

Revision ID: 004_harden_knowledge_item_type
Revises: 003_ensure_knowledge_items
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "004_harden_knowledge_item_type"
down_revision = "003_ensure_knowledge_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "knowledge_items" not in inspector.get_table_names():
        op.create_table(
            "knowledge_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("item_type", sa.String(50), nullable=False),
            sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("idx_knowledge_items_org", "knowledge_items", ["org_id"])
        op.create_index("idx_knowledge_items_user", "knowledge_items", ["user_id"])
        op.create_index("idx_knowledge_items_deleted", "knowledge_items", ["is_deleted"])
        return

    columns = {column["name"]: column for column in inspector.get_columns("knowledge_items")}
    item_type = columns.get("item_type")
    if item_type is not None and not isinstance(item_type["type"], sa.String):
        op.alter_column(
            "knowledge_items",
            "item_type",
            existing_type=item_type["type"],
            type_=sa.String(length=50),
            existing_nullable=False,
            postgresql_using="item_type::text",
        )


def downgrade() -> None:
    pass
