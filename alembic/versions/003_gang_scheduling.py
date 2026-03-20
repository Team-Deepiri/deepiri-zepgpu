"""Add gang_tasks, preemption_records, and fair_share_buckets tables

Revision ID: 003_gang_scheduling
Revises: 002_scheduled_tasks
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '003_gang_scheduling'
down_revision: Union[str, None] = '002_scheduled_tasks'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'gang_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('num_gpus_required', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('allocated_gpu_ids', postgresql.JSONB(), nullable=True),
        sa.Column('gpu_memory_mb_per_gpu', sa.Integer(), nullable=False, server_default='1024'),
        sa.Column('gpu_type', sa.String(50), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('allow_partial_allocation', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('func_name', sa.String(255), nullable=True),
        sa.Column('serialized_func', postgresql.BYTEA(), nullable=True),
        sa.Column('args', postgresql.BYTEA(), nullable=True),
        sa.Column('kwargs', postgresql.BYTEA(), nullable=True),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='7200'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('callback_url', sa.String(500), nullable=True),
        sa.Column('tags', postgresql.JSONB(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=True),
        sa.Column('can_be_preempted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('checkpoint_interval_seconds', sa.Integer(), nullable=True),
        sa.Column('child_task_ids', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_gang_tasks_user_id', 'gang_tasks', ['user_id'])
    op.create_index('idx_gang_tasks_user_status', 'gang_tasks', ['user_id', 'status'])
    op.create_index('idx_gang_tasks_priority', 'gang_tasks', ['priority'])
    op.create_index('idx_gang_tasks_created_at', 'gang_tasks', ['created_at'])
    op.create_index('idx_gang_tasks_name', 'gang_tasks', ['name'])

    op.create_table(
        'preemption_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('gang_task_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('gang_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('preempted_task_id', sa.String(255), nullable=False),
        sa.Column('preempted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.String(255), nullable=False),
        sa.Column('checkpoint_ref', sa.String(500), nullable=True),
        sa.Column('execution_time_before_preemption_ms', sa.BigInteger(), nullable=True),
        sa.Column('resume_attempted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('resume_successful', sa.Boolean(), nullable=True),
        sa.Column('resume_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_preemption_records_gang_task_id', 'preemption_records', ['gang_task_id'])
    op.create_index('idx_preemption_records_preempted_task_id', 'preemption_records', ['preempted_task_id'])

    op.create_table(
        'fair_share_buckets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('namespace', sa.String(255), nullable=True),
        sa.Column('weight', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('gpu_seconds_used', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('gpu_seconds_limit', sa.BigInteger(), nullable=True),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_hours', sa.Integer(), nullable=False, server_default='24'),
        sa.Column('tasks_completed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tasks_failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tasks_preempted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_fair_share_buckets_user_id', 'fair_share_buckets', ['user_id'])
    op.create_index('idx_fair_share_buckets_namespace', 'fair_share_buckets', ['namespace'])

    op.execute("""
        ALTER TABLE gpu_devices 
        ADD COLUMN IF NOT EXISTS state VARCHAR(50) DEFAULT 'idle';
    """)


def downgrade() -> None:
    op.drop_table('fair_share_buckets')
    op.drop_table('preemption_records')
    op.drop_table('gang_tasks')
