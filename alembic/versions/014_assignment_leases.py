"""Add claim/lease and terminal reason fields to node_task_assignments.

Revision ID: 014_assignment_leases
Revises: 013_provider_token_fields
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "014_assignment_leases"
down_revision = "013_provider_token_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "node_task_assignments",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "node_task_assignments",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "node_task_assignments",
        sa.Column(
            "claim_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "node_task_assignments",
        sa.Column("terminal_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "node_task_assignments",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "node_task_assignments",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_node_task_assignments_lease_expires_at",
        "node_task_assignments",
        ["lease_expires_at"],
    )
    op.create_index(
        "ix_node_task_assignments_terminal_reason",
        "node_task_assignments",
        ["terminal_reason"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_node_task_assignments_terminal_reason",
        table_name="node_task_assignments",
    )
    op.drop_index(
        "ix_node_task_assignments_lease_expires_at",
        table_name="node_task_assignments",
    )
    op.drop_column("node_task_assignments", "cancelled_at")
    op.drop_column("node_task_assignments", "cancel_requested_at")
    op.drop_column("node_task_assignments", "terminal_reason")
    op.drop_column("node_task_assignments", "claim_generation")
    op.drop_column("node_task_assignments", "lease_expires_at")
    op.drop_column("node_task_assignments", "claimed_at")
