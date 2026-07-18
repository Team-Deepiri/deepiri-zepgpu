"""VPN peer and GPU sharing network tables.

Revision ID: 005
Revises: 004
Create Date: 2026-05-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '005'
down_revision: Union[str, None] = '004_multi_tenant'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vpn_networks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('cidr', sa.String(20), nullable=False, server_default='10.8.0.0/24'),
        sa.Column('listen_port', sa.Integer(), nullable=False, server_default='51820'),
        sa.Column('relay_endpoint', sa.String(255), nullable=True),
        sa.Column('relay_public_key', sa.String(255), nullable=True),
        sa.Column('private_key_encrypted', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
    )

    op.create_table(
        'vpn_peers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('vpn_network_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vpn_networks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('wireguard_public_key', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('wireguard_private_key_encrypted', sa.Text(), nullable=True),
        sa.Column('vpn_ip', sa.String(15), nullable=False),
        sa.Column('endpoint', sa.String(255), nullable=True),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=False),
        sa.Column('online_status', sa.Enum('ONLINE', 'OFFLINE', 'AWOL', name='peeronlinestatus'), nullable=False, server_default='OFFLINE'),
        sa.Column('is_gpu_host', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_relay', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('heartbeat_interval_seconds', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('auth_token_encrypted', sa.Text(), nullable=True),
    )

    op.create_table(
        'gpu_shares',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('peer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vpn_peers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('vpn_network_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vpn_networks.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('device_index', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('total_memory_mb', sa.BigInteger(), nullable=False),
        sa.Column('available_memory_mb', sa.BigInteger(), nullable=False),
        sa.Column('compute_capability', sa.String(20), nullable=True),
        sa.Column('gpu_type', sa.String(50), nullable=False, server_default='nvidia'),
        sa.Column('state', sa.Enum('IDLE', 'ALLOCATED', 'UNAVAILABLE', name='gpusharestate'), nullable=False, server_default='IDLE'),
        sa.Column('current_task_id', sa.String(255), nullable=True),
        sa.Column('utilization_percent', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
    )

    op.create_table(
        'friendships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('friend_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'ACCEPTED', 'BLOCKED', name='friendshipstatus'), nullable=False, server_default='PENDING', index=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'friend_id', name='uq_friendship_pair'),
    )

    op.create_table(
        'vpn_invites',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('code', sa.String(16), nullable=False, unique=True, index=True),
        sa.Column('creator_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('vpn_network_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vpn_networks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('max_uses', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('used_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_revoked', sa.Boolean(), nullable=False, server_default='false'),
    )

    op.create_table(
        'gpu_share_quotas',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('peer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('vpn_peers.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('max_gpu_hours_per_day', sa.Float(), nullable=False, server_default='4.0'),
        sa.Column('max_concurrent_tasks', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('priority_boost', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('current_usage_hours', sa.Float(), nullable=False, server_default='0.0'),
    )


def downgrade() -> None:
    op.drop_table('gpu_share_quotas')
    op.drop_table('vpn_invites')
    op.drop_table('friendships')
    op.drop_table('gpu_shares')
    op.drop_table('vpn_peers')
    op.drop_table('vpn_networks')
    op.execute("DROP TYPE IF EXISTS gpusharestate")
    op.execute("DROP TYPE IF EXISTS peeronlinestatus")
    op.execute("DROP TYPE IF EXISTS friendshipstatus")
