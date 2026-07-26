"""Add host_id to vpn_networks and backfill from relay peers.

Revision ID: 007
Revises: 006
Create Date: 2026-07-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007b"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vpn_networks",
        sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_vpn_networks_host_id_users",
        "vpn_networks",
        "users",
        ["host_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_vpn_networks_host_id", "vpn_networks", ["host_id"])

    op.execute("""
        UPDATE vpn_networks AS n
        SET host_id = p.user_id
        FROM vpn_peers AS p
        WHERE p.vpn_network_id = n.id
          AND p.is_relay IS true
          AND n.host_id IS NULL
        """)


def downgrade() -> None:
    op.drop_index("ix_vpn_networks_host_id", table_name="vpn_networks")
    op.drop_constraint("fk_vpn_networks_host_id_users", "vpn_networks", type_="foreignkey")
    op.drop_column("vpn_networks", "host_id")
