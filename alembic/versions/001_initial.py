"""Initial migration - create all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('username', sa.String(255), nullable=False, unique=True),
        sa.Column('email', sa.String(255), nullable=False, unique=True),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(50), nullable=False, server_default='user'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_users_username', 'users', ['username'])
    op.create_index('idx_users_email', 'users', ['email'])

    # Create tasks table
    op.create_table(
        'tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('func_name', sa.String(255), nullable=True),
        sa.Column('serialized_func', postgresql.BYTEA(), nullable=True),
        sa.Column('args', postgresql.BYTEA(), nullable=True),
        sa.Column('kwargs', postgresql.BYTEA(), nullable=True),
        sa.Column('gpu_memory_mb', sa.Integer(), nullable=False, server_default='1024'),
        sa.Column('cpu_cores', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='3600'),
        sa.Column('gpu_type', sa.String(50), nullable=True),
        sa.Column('allow_fallback_cpu', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('gpu_device_id', sa.Integer(), nullable=True),
        sa.Column('container_id', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('result_ref', sa.String(500), nullable=True),
        sa.Column('result_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('execution_time_ms', sa.BigInteger(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=True, server_default='{}'),
        sa.Column('tags', postgresql.JSONB(), nullable=True),
        sa.Column('callback_url', sa.String(500), nullable=True),
    )
    op.create_index('idx_tasks_user_id', 'tasks', ['user_id'])
    op.create_index('idx_tasks_status', 'tasks', ['status'])
    op.create_index('idx_tasks_created_at', 'tasks', ['created_at'])
    op.create_index('idx_tasks_user_status', 'tasks', ['user_id', 'status'])
    op.create_index('idx_tasks_status_created', 'tasks', ['status', 'created_at'])
    op.create_index('idx_tasks_name', 'tasks', ['name'])

    # Create pipelines table
    op.create_table(
        'pipelines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('stages', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
    )
    op.create_index('idx_pipelines_user_id', 'pipelines', ['user_id'])
    op.create_index('idx_pipelines_status', 'pipelines', ['status'])

    # Create gpu_devices table
    op.create_table(
        'gpu_devices',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('device_index', sa.Integer(), nullable=False, unique=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('gpu_type', sa.String(50), nullable=True),
        sa.Column('total_memory_mb', sa.BigInteger(), nullable=True),
        sa.Column('compute_capability', sa.String(20), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='available'),
        sa.Column('current_task_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('utilization_percent', sa.Numeric(5, 2), nullable=True),
        sa.Column('temperature_celsius', sa.Integer(), nullable=True),
        sa.Column('power_watts', sa.Numeric(7, 2), nullable=True),
        sa.Column('last_seen', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_gpu_devices_status', 'gpu_devices', ['status'])

    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(100), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=True),
        sa.Column('resource_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('details', postgresql.JSONB(), nullable=True),
        sa.Column('ip_address', postgresql.INET(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('idx_audit_logs_created_at', 'audit_logs', ['created_at'])
    op.create_index('idx_audit_logs_action', 'audit_logs', ['action'])

    # Create user_quotas table
    op.create_table(
        'user_quotas',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('max_tasks', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('max_gpu_hours', sa.Numeric(10, 2), nullable=False, server_default='24'),
        sa.Column('max_concurrent_tasks', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('max_gpu_memory_mb', sa.Integer(), nullable=False, server_default='16384'),
        sa.Column('period_hours', sa.Integer(), nullable=False, server_default='24'),
        sa.Column('tasks_submitted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('gpu_seconds_used', sa.Numeric(15, 2), nullable=False, server_default='0'),
        sa.Column('concurrent_tasks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('period_start', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('user_quotas')
    op.drop_table('audit_logs')
    op.drop_table('gpu_devices')
    op.drop_table('pipelines')
    op.drop_table('tasks')
    op.drop_table('users')
