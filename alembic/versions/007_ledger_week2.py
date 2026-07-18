"""Alembic migration: Week-2 ledger quorum, network scope, peer keys.

Revision ID: 007
Revises: 006
Create Date: 2026-07-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Quorum / finality on blocks
    op.add_column(
        "ledger_blocks",
        sa.Column(
            "approvals",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "ledger_blocks",
        sa.Column(
            "finalized",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    op.add_column(
        "ledger_blocks",
        sa.Column("vpn_network_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_ledger_blocks_vpn_network_id", "ledger_blocks", ["vpn_network_id"])
    op.create_index("ix_ledger_blocks_finalized", "ledger_blocks", ["finalized"])

    # Network scope on related tables
    op.add_column(
        "ledger_transactions",
        sa.Column("vpn_network_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "ledger_balances",
        sa.Column("vpn_network_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "ledger_validators",
        sa.Column("vpn_network_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Allow same pubkey on multiple chains: drop global unique, add composite unique
    op.drop_index("ix_ledger_validators_public_key", table_name="ledger_validators")
    op.create_index("ix_ledger_validators_public_key", "ledger_validators", ["public_key"], unique=False)
    op.create_unique_constraint(
        "uq_ledger_validators_chain_pubkey",
        "ledger_validators",
        ["chain_id", "public_key"],
    )

    # Peer attestation keys on VPN peers
    op.add_column(
        "vpn_peers",
        sa.Column("ledger_public_key", sa.String(128), nullable=True),
    )
    op.add_column(
        "vpn_peers",
        sa.Column("ledger_private_key_encrypted", sa.Text(), nullable=True),
    )
    op.create_index("ix_vpn_peers_ledger_public_key", "vpn_peers", ["ledger_public_key"])


def downgrade() -> None:
    op.drop_index("ix_vpn_peers_ledger_public_key", table_name="vpn_peers")
    op.drop_column("vpn_peers", "ledger_private_key_encrypted")
    op.drop_column("vpn_peers", "ledger_public_key")

    op.drop_constraint("uq_ledger_validators_chain_pubkey", "ledger_validators", type_="unique")
    op.drop_index("ix_ledger_validators_public_key", table_name="ledger_validators")
    op.create_index("ix_ledger_validators_public_key", "ledger_validators", ["public_key"], unique=True)

    op.drop_column("ledger_validators", "vpn_network_id")
    op.drop_column("ledger_balances", "vpn_network_id")
    op.drop_column("ledger_transactions", "vpn_network_id")

    op.drop_index("ix_ledger_blocks_finalized", table_name="ledger_blocks")
    op.drop_index("ix_ledger_blocks_vpn_network_id", table_name="ledger_blocks")
    op.drop_column("ledger_blocks", "vpn_network_id")
    op.drop_column("ledger_blocks", "finalized")
    op.drop_column("ledger_blocks", "approvals")
