"""Normalize indexes against current SQLAlchemy metadata.

Revision ID: 006_normalize_schema_metadata
Revises: 005_reconcile_schema_indexes
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = "006_normalize_schema_metadata"
down_revision = "005_reconcile_schema_indexes"
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

    if "cases" in tables:
        _drop_index_if_exists(inspector, "cases", "idx_cases_is_deleted")
        _create_index_if_missing(inspector, "cases", "idx_cases_deleted_created", ["is_deleted", sa.text("created_at DESC")])

    if "case_members" in tables:
        _create_index_if_missing(inspector, "case_members", "idx_case_members_case", ["case_id"])

    if "document_versions" in tables:
        _create_index_if_missing(inspector, "document_versions", "idx_doc_versions_doc", ["document_id", "version_number"])

    if "fact_collaborations" in tables:
        _create_index_if_missing(inspector, "fact_collaborations", "idx_fact_collaborations_fact", ["fact_id"])

    if "org_members" in tables:
        _create_index_if_missing(inspector, "org_members", "idx_org_members_org", ["org_id"])
        _create_index_if_missing(inspector, "org_members", "idx_org_members_user", ["user_id"])

    if "teams" in tables:
        _create_index_if_missing(inspector, "teams", "idx_teams_org", ["org_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = _tables(inspector)
    drops = {
        "cases": ["idx_cases_deleted_created"],
        "case_members": ["idx_case_members_case"],
        "document_versions": ["idx_doc_versions_doc"],
        "fact_collaborations": ["idx_fact_collaborations_fact"],
        "org_members": ["idx_org_members_org", "idx_org_members_user"],
        "teams": ["idx_teams_org"],
    }
    for table_name, index_names in drops.items():
        if table_name not in tables:
            continue
        for index_name in index_names:
            _drop_index_if_exists(inspector, table_name, index_name)
