"""Phase 18 elastic training, islands, reservations, and outer rounds.

Revision ID: 017_phase18_elastic_training
Revises: 016_training_runs
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "017_phase18_elastic_training"
down_revision: str | None = "016_training_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.add_column("training_runs", sa.Column("placement_plan", postgresql.JSONB(), nullable=True))
    op.add_column("training_runs", sa.Column("launch_key", sa.String(64), nullable=True))
    op.add_column(
        "training_runs", sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "training_runs",
        sa.Column("current_outer_round", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_unique_constraint("uq_training_runs_launch_key", "training_runs", ["launch_key"])

    op.create_table(
        "training_islands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        *_timestamps(),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("provider_ids", postgresql.JSONB(), nullable=False),
        sa.Column("gpu_share_ids", postgresql.JSONB(), nullable=False),
        sa.Column("strategy_eligibility", postgresql.JSONB(), nullable=False),
        sa.Column("topology", postgresql.JSONB(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.UniqueConstraint("run_id", "id", name="uq_training_island_run_id"),
    )
    op.create_index("ix_training_islands_run_id", "training_islands", ["run_id"])

    op.add_column(
        "training_workers", sa.Column("island_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("training_workers", sa.Column("global_rank", sa.Integer(), nullable=True))
    op.add_column("training_workers", sa.Column("island_rank", sa.Integer(), nullable=True))
    op.add_column("training_workers", sa.Column("world_size", sa.Integer(), nullable=True))
    op.add_column("training_workers", sa.Column("island_world_size", sa.Integer(), nullable=True))
    op.add_column(
        "training_workers",
        sa.Column(
            "assigned_devices",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "training_workers",
        sa.Column("bootstrap_checkpoint", postgresql.JSONB(), nullable=True),
    )
    op.create_foreign_key(
        "fk_training_workers_island_id",
        "training_workers",
        "training_islands",
        ["island_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "training_gpu_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        *_timestamps(),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_workers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "island_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_islands.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "vpn_network_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vpn_networks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "peer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vpn_peers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "gpu_share_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gpu_shares.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reservation_owner", sa.String(255), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "active",
                "released",
                "expired",
                name="trainingreservationstate",
                native_enum=False,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(255), nullable=True),
    )
    op.create_index("ix_training_gpu_reservations_run_id", "training_gpu_reservations", ["run_id"])
    op.create_index(
        "ix_training_gpu_reservations_vpn_network_id",
        "training_gpu_reservations",
        ["vpn_network_id"],
    )
    op.create_index("ix_training_gpu_reservations_state", "training_gpu_reservations", ["state"])
    op.create_index(
        "ix_training_gpu_reservations_expiry",
        "training_gpu_reservations",
        ["state", "expires_at"],
    )
    op.create_index(
        "uq_training_gpu_reservations_active_share",
        "training_gpu_reservations",
        ["gpu_share_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    op.create_table(
        "training_outer_rounds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        *_timestamps(),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "open",
                "finalized",
                "paused",
                "failed",
                name="trainingouterroundstate",
                native_enum=False,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("expected_workers", sa.Integer(), nullable=False),
        sa.Column("min_k", sa.Integer(), nullable=False),
        sa.Column(
            "accepted_worker_ids",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "rejected_updates",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metrics",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "optimizer_state",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "round_number", name="uq_training_outer_round_run_round"),
    )
    op.create_index("ix_training_outer_rounds_run_id", "training_outer_rounds", ["run_id"])

    op.create_table(
        "training_run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        *_timestamps(),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_training_run_events_run_id", "training_run_events", ["run_id"])
    op.create_index("ix_training_run_events_kind", "training_run_events", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_training_run_events_kind", table_name="training_run_events")
    op.drop_index("ix_training_run_events_run_id", table_name="training_run_events")
    op.drop_table("training_run_events")
    op.drop_index("ix_training_outer_rounds_run_id", table_name="training_outer_rounds")
    op.drop_table("training_outer_rounds")
    op.drop_index(
        "uq_training_gpu_reservations_active_share", table_name="training_gpu_reservations"
    )
    op.drop_index("ix_training_gpu_reservations_expiry", table_name="training_gpu_reservations")
    op.drop_index("ix_training_gpu_reservations_state", table_name="training_gpu_reservations")
    op.drop_index(
        "ix_training_gpu_reservations_vpn_network_id",
        table_name="training_gpu_reservations",
    )
    op.drop_index("ix_training_gpu_reservations_run_id", table_name="training_gpu_reservations")
    op.drop_table("training_gpu_reservations")
    op.drop_constraint("fk_training_workers_island_id", "training_workers", type_="foreignkey")
    op.drop_column("training_workers", "bootstrap_checkpoint")
    op.drop_column("training_workers", "assigned_devices")
    op.drop_column("training_workers", "island_world_size")
    op.drop_column("training_workers", "world_size")
    op.drop_column("training_workers", "island_rank")
    op.drop_column("training_workers", "global_rank")
    op.drop_column("training_workers", "island_id")
    op.drop_index("ix_training_islands_run_id", table_name="training_islands")
    op.drop_table("training_islands")
    op.drop_constraint("uq_training_runs_launch_key", "training_runs", type_="unique")
    op.drop_column("training_runs", "current_outer_round")
    op.drop_column("training_runs", "launched_at")
    op.drop_column("training_runs", "launch_key")
    op.drop_column("training_runs", "placement_plan")
