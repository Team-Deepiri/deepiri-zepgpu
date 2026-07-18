"""Alembic migration: bridge tx types + bridge receipt index helper table.

Revision ID: 010
Revises: 009
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extend Postgres enum for ledger transaction types
    op.execute("ALTER TYPE ledgertxtype ADD VALUE IF NOT EXISTS 'BRIDGE_BURN'")
    op.execute("ALTER TYPE ledgertxtype ADD VALUE IF NOT EXISTS 'BRIDGE_MINT'")

    op.create_table(
        "ledger_bridge_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("receipt_id", sa.String(64), nullable=False),
        sa.Column("source_chain_id", sa.String(128), nullable=False),
        sa.Column("dest_chain_id", sa.String(128), nullable=False),
        sa.Column("account", sa.String(128), nullable=False),
        sa.Column("amount_seconds", sa.Float(), nullable=False),
        sa.Column("burn_tx_hash", sa.String(64), nullable=False),
        sa.Column("mint_tx_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.UniqueConstraint("dest_chain_id", "receipt_id", name="uq_ledger_bridge_dest_receipt"),
    )
    op.create_index("ix_ledger_bridge_receipts_receipt_id", "ledger_bridge_receipts", ["receipt_id"])
    op.create_index("ix_ledger_bridge_receipts_source_chain_id", "ledger_bridge_receipts", ["source_chain_id"])
    op.create_index("ix_ledger_bridge_receipts_dest_chain_id", "ledger_bridge_receipts", ["dest_chain_id"])


def downgrade() -> None:
    op.drop_table("ledger_bridge_receipts")
    # Postgres cannot easily remove enum values; leave BRIDGE_* in place.
