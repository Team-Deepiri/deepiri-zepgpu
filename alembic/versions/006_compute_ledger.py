"""Alembic migration: permissioned compute ledger tables.

Revision ID: 006
Revises: 005
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ledger_validators",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("public_key", sa.String(128), nullable=False),
        sa.Column("label", sa.String(255), nullable=False, server_default="relay"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("chain_id", sa.String(64), nullable=False),
    )
    op.create_index("ix_ledger_validators_public_key", "ledger_validators", ["public_key"], unique=True)
    op.create_index("ix_ledger_validators_chain_id", "ledger_validators", ["chain_id"])

    op.create_table(
        "ledger_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chain_id", sa.String(64), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("previous_hash", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("transactions_root", sa.String(64), nullable=False),
        sa.Column("state_root", sa.String(64), nullable=False),
        sa.Column("validator_public_key", sa.String(128), nullable=False),
        sa.Column("validator_signature", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("chain_id", "height", name="uq_ledger_blocks_chain_height"),
    )
    op.create_index("ix_ledger_blocks_hash", "ledger_blocks", ["hash"], unique=True)
    op.create_index("ix_ledger_blocks_chain_id", "ledger_blocks", ["chain_id"])
    op.create_index("idx_ledger_blocks_chain_height", "ledger_blocks", ["chain_id", "height"])

    op.create_table(
        "ledger_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("chain_id", sa.String(64), nullable=False),
        sa.Column("tx_hash", sa.String(64), nullable=False),
        sa.Column(
            "tx_type",
            sa.Enum(
                "JOB_SUBMITTED",
                "JOB_ASSIGNED",
                "JOB_COMPLETED",
                "CREDIT_SETTLED",
                "VALIDATOR_REGISTERED",
                name="ledgertxtype",
            ),
            nullable=False,
        ),
        sa.Column("sender", sa.String(128), nullable=False),
        sa.Column("nonce", sa.BigInteger(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_blocks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("chain_id", "sender", "nonce", name="uq_ledger_tx_sender_nonce"),
    )
    op.create_index("ix_ledger_transactions_tx_hash", "ledger_transactions", ["tx_hash"], unique=True)
    op.create_index("ix_ledger_transactions_chain_id", "ledger_transactions", ["chain_id"])
    op.create_index("ix_ledger_transactions_tx_type", "ledger_transactions", ["tx_type"])
    op.create_index("ix_ledger_transactions_sender", "ledger_transactions", ["sender"])
    op.create_index("ix_ledger_transactions_block_id", "ledger_transactions", ["block_id"])
    op.create_index("idx_ledger_tx_pending", "ledger_transactions", ["chain_id", "block_id"])

    op.create_table(
        "ledger_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("chain_id", sa.String(64), nullable=False),
        sa.Column("account", sa.String(128), nullable=False),
        sa.Column("credit_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("debit_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.UniqueConstraint("chain_id", "account", name="uq_ledger_balances_chain_account"),
    )
    op.create_index("ix_ledger_balances_chain_id", "ledger_balances", ["chain_id"])
    op.create_index("ix_ledger_balances_account", "ledger_balances", ["account"])


def downgrade() -> None:
    op.drop_table("ledger_balances")
    op.drop_table("ledger_transactions")
    op.drop_table("ledger_blocks")
    op.drop_table("ledger_validators")
    op.execute("DROP TYPE IF EXISTS ledgertxtype")
