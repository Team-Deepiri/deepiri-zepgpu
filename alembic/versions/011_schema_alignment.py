"""Align pipeline columns with ORM models used by API regression.

Revision ID: 011_schema_alignment
Revises: 010
Create Date: 2026-07-18

User/quota columns previously in this migration are covered by 007.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "011_schema_alignment"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns(table)}
    if column.name not in cols:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing("pipelines", sa.Column("description", sa.Text(), nullable=True))
    _add_column_if_missing(
        "pipelines", sa.Column("stage_results", postgresql.JSONB(), nullable=True)
    )
    _add_column_if_missing(
        "pipelines", sa.Column("stage_statuses", postgresql.JSONB(), nullable=True)
    )
    _add_column_if_missing(
        "pipelines", sa.Column("current_stage", sa.String(255), nullable=True)
    )
    _add_column_if_missing(
        "pipelines",
        sa.Column("completed_stages", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "pipelines",
        sa.Column("total_execution_time_ms", sa.BigInteger(), nullable=True),
    )
    _add_column_if_missing(
        "pipelines", sa.Column("metadata_json", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("pipelines")}
    for name in (
        "metadata_json",
        "total_execution_time_ms",
        "completed_stages",
        "current_stage",
        "stage_statuses",
        "stage_results",
        "description",
    ):
        if name in cols:
            op.drop_column("pipelines", name)
