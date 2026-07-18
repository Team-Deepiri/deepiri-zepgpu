"""Align core tables with ORM models used by API regression.

Revision ID: 009_schema_alignment
Revises: 008_ledger_bridge
Create Date: 2026-07-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_schema_alignment"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("users", sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(100), nullable=True))
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("pipelines", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("pipelines", sa.Column("stage_results", postgresql.JSONB(), nullable=True))
    op.add_column("pipelines", sa.Column("stage_statuses", postgresql.JSONB(), nullable=True))
    op.add_column("pipelines", sa.Column("current_stage", sa.String(255), nullable=True))
    op.add_column(
        "pipelines",
        sa.Column("completed_stages", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pipelines",
        sa.Column("total_execution_time_ms", sa.BigInteger(), nullable=True),
    )
    op.add_column("pipelines", sa.Column("metadata_json", postgresql.JSONB(), nullable=True))

    op.add_column(
        "user_quotas",
        sa.Column("max_storage_gb", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "user_quotas",
        sa.Column(
            "storage_used_gb",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_quotas", "storage_used_gb")
    op.drop_column("user_quotas", "max_storage_gb")
    op.drop_column("pipelines", "metadata_json")
    op.drop_column("pipelines", "total_execution_time_ms")
    op.drop_column("pipelines", "completed_stages")
    op.drop_column("pipelines", "current_stage")
    op.drop_column("pipelines", "stage_statuses")
    op.drop_column("pipelines", "stage_results")
    op.drop_column("pipelines", "description")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
    op.drop_column("users", "is_verified")
