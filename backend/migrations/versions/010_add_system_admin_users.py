"""Add system administrator flag to users.

Revision ID: 010_add_system_admin_users
Revises: 009_add_document_updated_at
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "010_add_system_admin_users"
down_revision = "009_add_document_updated_at"
branch_labels = None
depends_on = None


def _columns(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return

    if "is_system_admin" not in _columns(inspector, "users"):
        op.add_column(
            "users",
            sa.Column(
                "is_system_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if "idx_users_system_admin" not in _indexes(inspector, "users"):
        op.create_index("idx_users_system_admin", "users", ["is_system_admin", "is_active"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return

    if "idx_users_system_admin" in _indexes(inspector, "users"):
        op.drop_index("idx_users_system_admin", table_name="users")
    if "is_system_admin" in _columns(inspector, "users"):
        op.drop_column("users", "is_system_admin")
