"""Add indexes for cached list fallbacks and admin search.

Revision ID: 013_database_cache_indexes
Revises: 012_document_type_customization
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "013_database_cache_indexes"
down_revision = "012_document_type_customization"
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

    if "users" in tables:
        _create_index_if_missing(inspector, "users", "idx_users_created_at", [sa.text("created_at DESC")])
        _create_index_if_missing(inspector, "users", "idx_users_active_created", ["is_active", sa.text("created_at DESC")])
        _create_index_if_missing(inspector, "users", "idx_users_admin_active", ["is_system_admin", "is_active"])
        _create_index_if_missing(inspector, "users", "idx_users_lower_email", [sa.text("lower(email)")])
        _create_index_if_missing(inspector, "users", "idx_users_lower_name", [sa.text("lower(name)")])
        _create_index_if_missing(inspector, "users", "idx_users_lower_firm_name", [sa.text("lower(firm_name)")])

    if "cases" in tables:
        _create_index_if_missing(inspector, "cases", "idx_cases_lead_lawyer", ["lead_lawyer_id"])
        _create_index_if_missing(inspector, "cases", "idx_cases_updated_at", [sa.text("updated_at DESC")])
        _create_index_if_missing(inspector, "cases", "idx_cases_lower_title", [sa.text("lower(title)")])

    if "knowledge_items" in tables:
        _create_index_if_missing(
            inspector,
            "knowledge_items",
            "idx_knowledge_items_user_deleted_updated",
            ["user_id", "is_deleted", sa.text("updated_at DESC")],
        )
        _create_index_if_missing(
            inspector,
            "knowledge_items",
            "idx_knowledge_items_user_deleted_type_updated",
            ["user_id", "is_deleted", "item_type", sa.text("updated_at DESC")],
        )

    if "facts" in tables:
        _create_index_if_missing(
            inspector,
            "facts",
            "idx_facts_case_deleted_confidence_updated",
            ["case_id", "is_deleted", sa.text("confidence_score DESC"), sa.text("updated_at DESC")],
        )

    if "agent_tasks" in tables:
        _create_index_if_missing(
            inspector,
            "agent_tasks",
            "idx_agent_tasks_case_type_status_created",
            ["case_id", "task_type", "status", sa.text("created_at DESC")],
        )

    if "client_tasks" in tables:
        _create_index_if_missing(
            inspector,
            "client_tasks",
            "idx_client_tasks_deleted_status",
            ["is_deleted", "status"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    drops = {
        "users": [
            "idx_users_created_at",
            "idx_users_active_created",
            "idx_users_admin_active",
            "idx_users_lower_email",
            "idx_users_lower_name",
            "idx_users_lower_firm_name",
        ],
        "cases": [
            "idx_cases_lead_lawyer",
            "idx_cases_updated_at",
            "idx_cases_lower_title",
        ],
        "knowledge_items": [
            "idx_knowledge_items_user_deleted_updated",
            "idx_knowledge_items_user_deleted_type_updated",
        ],
        "facts": ["idx_facts_case_deleted_confidence_updated"],
        "agent_tasks": ["idx_agent_tasks_case_type_status_created"],
        "client_tasks": ["idx_client_tasks_deleted_status"],
    }
    tables = _tables(inspector)
    for table_name, index_names in drops.items():
        if table_name not in tables:
            continue
        for index_name in index_names:
            _drop_index_if_exists(inspector, table_name, index_name)
