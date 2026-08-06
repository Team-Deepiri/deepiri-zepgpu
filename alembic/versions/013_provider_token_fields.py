"""Add room-scoped provider token and revoke fields on vpn_peers.

Revision ID: 013_provider_token_fields
Revises: 012_fix_phase4_schema_drift
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "013_provider_token_fields"
down_revision = "012_fix_phase4_schema_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vpn_peers",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("token_revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("token_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("token_last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("agent_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("provider_mode", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("node_name", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_vpn_peers_revoked_at", "vpn_peers", ["revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_vpn_peers_revoked_at", table_name="vpn_peers")
    op.drop_column("vpn_peers", "node_name")
    op.drop_column("vpn_peers", "revoked_at")
    op.drop_column("vpn_peers", "provider_mode")
    op.drop_column("vpn_peers", "agent_version")
    op.drop_column("vpn_peers", "token_last_used_at")
    op.drop_column("vpn_peers", "token_rotated_at")
    op.drop_column("vpn_peers", "token_revoked_at")
    op.drop_column("vpn_peers", "token_expires_at")
