"""First-class training run and worker tables.

Revision ID: 013_training_runs
Revises: 012_fix_phase4_schema_drift
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "013_training_runs"
down_revision: str | None = "012_fix_phase4_schema_drift"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "vpn_network_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vpn_networks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(32), nullable=False, server_default="created"),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "provider_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "artifacts",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("startup_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_training_runs_vpn_network_id", "training_runs", ["vpn_network_id"])
    op.create_index("ix_training_runs_user_id", "training_runs", ["user_id"])
    op.create_index("ix_training_runs_state", "training_runs", ["state"])
    op.create_table(
        "training_workers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "peer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vpn_peers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(32), nullable=False, server_default="created"),
        sa.Column("current_round", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("restart_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "progress",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("credential_id_hash", sa.String(64), nullable=True),
        sa.Column("credential_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credential_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "peer_id", name="uq_training_worker_run_peer"),
    )
    op.create_index("ix_training_workers_run_id", "training_workers", ["run_id"])
    op.create_table(
        "training_worker_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_workers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_training_worker_events_run_id", "training_worker_events", ["run_id"])
    op.create_index("ix_training_worker_events_worker_id", "training_worker_events", ["worker_id"])


def downgrade() -> None:
    op.drop_index("ix_training_worker_events_worker_id", table_name="training_worker_events")
    op.drop_index("ix_training_worker_events_run_id", table_name="training_worker_events")
    op.drop_table("training_worker_events")
    op.drop_index("ix_training_workers_run_id", table_name="training_workers")
    op.drop_table("training_workers")
    op.drop_index("ix_training_runs_state", table_name="training_runs")
    op.drop_index("ix_training_runs_user_id", table_name="training_runs")
    op.drop_index("ix_training_runs_vpn_network_id", table_name="training_runs")
    op.drop_table("training_runs")
