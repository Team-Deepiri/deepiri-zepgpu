"""Add transport_mode and provider health/path/capability observability.

Revision ID: 015_transport_mode_observability
Revises: 014_assignment_leases
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "015_transport_mode_observability"
down_revision = "014_assignment_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vpn_networks",
        sa.Column(
            "transport_mode",
            sa.String(length=32),
            nullable=False,
            server_default="wireguard",
        ),
    )

    op.add_column(
        "vpn_peers",
        sa.Column("capabilities_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("capabilities_reported_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("health_state", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("health_reason", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("path_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("path_class", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("coordinator_rtt_ms", sa.Float(), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("path_freshness_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("path_measurement_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("recent_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("last_claim_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_vpn_peers_health_state", "vpn_peers", ["health_state"])

    op.add_column(
        "gpu_shares",
        sa.Column("temperature_celsius", sa.Float(), nullable=True),
    )
    op.add_column(
        "gpu_shares",
        sa.Column("power_watts", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gpu_shares", "power_watts")
    op.drop_column("gpu_shares", "temperature_celsius")

    op.drop_index("ix_vpn_peers_health_state", table_name="vpn_peers")
    op.drop_column("vpn_peers", "last_claim_at")
    op.drop_column("vpn_peers", "recent_failures")
    op.drop_column("vpn_peers", "path_measurement_kind")
    op.drop_column("vpn_peers", "path_freshness_at")
    op.drop_column("vpn_peers", "coordinator_rtt_ms")
    op.drop_column("vpn_peers", "path_class")
    op.drop_column("vpn_peers", "path_type")
    op.drop_column("vpn_peers", "health_reason")
    op.drop_column("vpn_peers", "health_state")
    op.drop_column("vpn_peers", "capabilities_reported_at")
    op.drop_column("vpn_peers", "capabilities_json")

    op.drop_column("vpn_networks", "transport_mode")
