"""Add namespaces, teams, and multi-tenant support

Revision ID: 004_multi_tenant
Revises: 003_gang_scheduling
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '004_multi_tenant'
down_revision: Union[str, None] = '003_gang_scheduling'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'namespaces',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('settings', postgresql.JSONB(), nullable=True),
        sa.Column('max_users', sa.Integer(), nullable=True),
        sa.Column('max_gpus', sa.Integer(), nullable=True),
        sa.Column('max_storage_gb', sa.Integer(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_namespaces_name', 'namespaces', ['name'])
    op.create_index('idx_namespaces_status', 'namespaces', ['status'])
    op.create_index('idx_namespaces_owner', 'namespaces', ['owner_id'])

    op.create_table(
        'namespace_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('namespace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('namespaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default='member'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_namespace_members_namespace_id', 'namespace_members', ['namespace_id'])
    op.create_index('idx_namespace_members_user_id', 'namespace_members', ['user_id'])
    op.create_index('idx_namespace_members_unique', 'namespace_members', ['namespace_id', 'user_id'], unique=True)

    op.create_table(
        'teams',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('namespace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('namespaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('team_lead_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('settings', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_teams_namespace_id', 'teams', ['namespace_id'])
    op.create_index('idx_teams_unique', 'teams', ['namespace_id', 'name'], unique=True)

    op.create_table(
        'team_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default='member'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_team_members_team_id', 'team_members', ['team_id'])
    op.create_index('idx_team_members_user_id', 'team_members', ['user_id'])
    op.create_index('idx_team_members_unique', 'team_members', ['team_id', 'user_id'], unique=True)

    op.create_table(
        'namespace_quotas',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('namespace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('namespaces.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('max_gpus', sa.Integer(), nullable=True),
        sa.Column('max_gpus_per_user', sa.Integer(), nullable=True),
        sa.Column('max_storage_gb', sa.Integer(), nullable=True),
        sa.Column('max_tasks', sa.Integer(), nullable=True),
        sa.Column('max_scheduled_tasks', sa.Integer(), nullable=True),
        sa.Column('max_gang_tasks', sa.Integer(), nullable=True),
        sa.Column('max_gpu_hours_per_day', sa.BigInteger(), nullable=True),
        sa.Column('max_gpu_hours_per_month', sa.BigInteger(), nullable=True),
        sa.Column('max_concurrent_tasks', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_namespace_quotas_namespace_id', 'namespace_quotas', ['namespace_id'])

    op.create_table(
        'namespace_usage',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('namespace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('namespaces.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('current_gpus', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('current_storage_gb', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_tasks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('running_tasks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('scheduled_tasks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('gang_tasks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('gpu_hours_today', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('gpu_hours_this_month', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_namespace_usage_namespace_id', 'namespace_usage', ['namespace_id'])

    op.add_column('tasks', sa.Column('namespace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('namespaces.id', ondelete='SET NULL'), nullable=True))
    op.create_index('idx_tasks_namespace', 'tasks', ['namespace_id'])

    op.add_column('gpu_devices', sa.Column('namespace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('namespaces.id', ondelete='SET NULL'), nullable=True))
    op.create_index('idx_gpu_devices_namespace', 'gpu_devices', ['namespace_id'])


def downgrade() -> None:
    op.drop_column('gpu_devices', 'namespace_id')
    op.drop_column('tasks', 'namespace_id')
    op.drop_table('namespace_usage')
    op.drop_table('namespace_quotas')
    op.drop_table('team_members')
    op.drop_table('teams')
    op.drop_table('namespace_members')
    op.drop_table('namespaces')
