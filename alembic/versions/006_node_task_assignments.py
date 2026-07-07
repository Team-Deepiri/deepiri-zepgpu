"""Node task assignment tables and task dispatch fields.

Revision ID: 006
Revises: 005
Create Date: 2026-07-07

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "node_task_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "vpn_network_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vpn_networks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "peer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vpn_peers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "gpu_share_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gpu_shares.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "assigned",
                "accepted",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="nodeassignmentstatus",
            ),
            nullable=False,
            server_default="assigned",
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "idx_node_task_assignments_room", "node_task_assignments", ["vpn_network_id"]
    )
    op.create_index("idx_node_task_assignments_task", "node_task_assignments", ["task_id"])
    op.create_index("idx_node_task_assignments_status", "node_task_assignments", ["status"])

    op.create_table(
        "node_task_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("node_task_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_node_task_events_assignment", "node_task_events", ["assignment_id"])

    op.add_column(
        "tasks",
        sa.Column(
            "vpn_network_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vpn_networks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("dispatch_mode", sa.String(50), nullable=False, server_default="local"),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "target_peer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vpn_peers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "target_gpu_share_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gpu_shares.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_tasks_vpn_network", "tasks", ["vpn_network_id"])


def downgrade() -> None:
    op.drop_index("idx_tasks_vpn_network", table_name="tasks")
    op.drop_column("tasks", "target_gpu_share_id")
    op.drop_column("tasks", "target_peer_id")
    op.drop_column("tasks", "dispatch_mode")
    op.drop_column("tasks", "vpn_network_id")

    op.drop_index("idx_node_task_events_assignment", table_name="node_task_events")
    op.drop_table("node_task_events")

    op.drop_index("idx_node_task_assignments_status", table_name="node_task_assignments")
    op.drop_index("idx_node_task_assignments_task", table_name="node_task_assignments")
    op.drop_index("idx_node_task_assignments_room", table_name="node_task_assignments")
    op.drop_table("node_task_assignments")
    op.execute("DROP TYPE IF EXISTS nodeassignmentstatus")
