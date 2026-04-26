"""Add agent strategy knowledge and draft revisions.

Revision ID: 002_agent_strategy_revisions
Revises: 001_initial
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "002_agent_strategy_revisions"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "knowledge_items" in inspector.get_table_names():
        op.alter_column(
            "knowledge_items",
            "item_type",
            existing_type=postgresql.ENUM(
                "prompt_template",
                "document_template",
                "sample_document",
                name="knowledgetype",
            ),
            type_=sa.String(length=50),
            existing_nullable=False,
            postgresql_using="item_type::text",
        )
    else:
        op.create_table(
            "knowledge_items",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
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

    op.create_table(
        "draft_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("draft_sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(500), nullable=False),
        sa.Column("content_snapshot", sa.Text(), nullable=False, server_default=""),
        sa.Column("editor_role", sa.String(50), nullable=False),
        sa.Column("editor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("change_summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("revision_metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_draft_revisions_section", "draft_revisions", ["section_id", "revision_number"])
    op.create_index("idx_draft_revisions_case", "draft_revisions", ["case_id"])


def downgrade() -> None:
    op.drop_index("idx_draft_revisions_case", table_name="draft_revisions")
    op.drop_index("idx_draft_revisions_section", table_name="draft_revisions")
    op.drop_table("draft_revisions")
    inspector = sa.inspect(op.get_bind())
    if "knowledge_items" in inspector.get_table_names():
        op.drop_index("idx_knowledge_items_deleted", table_name="knowledge_items")
        op.drop_index("idx_knowledge_items_user", table_name="knowledge_items")
        op.drop_index("idx_knowledge_items_org", table_name="knowledge_items")
        op.drop_table("knowledge_items")
