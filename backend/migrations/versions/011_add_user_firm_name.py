"""Add user firm display name.

Revision ID: 011_add_user_firm_name
Revises: 010_add_system_admin_users
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "011_add_user_firm_name"
down_revision = "010_add_system_admin_users"
branch_labels = None
depends_on = None


def _columns(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(inspector, table_name: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        return

    if "firm_name" not in _columns(inspector, "users"):
        op.add_column("users", sa.Column("firm_name", sa.String(255), nullable=True))

    if {"organizations", "org_members"}.issubset(tables):
        op.execute("""
            UPDATE users
            SET firm_name = organizations.name
            FROM org_members
            JOIN organizations ON organizations.id = org_members.org_id
            WHERE org_members.user_id = users.id
              AND (users.firm_name IS NULL OR users.firm_name = '')
              AND organizations.name IS NOT NULL
              AND organizations.name <> ''
        """)

    if "idx_users_firm_name" not in _indexes(inspector, "users"):
        op.create_index("idx_users_firm_name", "users", ["firm_name"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return

    if "idx_users_firm_name" in _indexes(inspector, "users"):
        op.drop_index("idx_users_firm_name", table_name="users")
    if "firm_name" in _columns(inspector, "users"):
        op.drop_column("users", "firm_name")
