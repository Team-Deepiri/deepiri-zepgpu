"""Add scheduled_tasks and scheduled_task_runs tables

Revision ID: 002_scheduled_tasks
Revises: 001_initial
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '002_scheduled_tasks'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scheduled_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('schedule_type', sa.String(50), nullable=False, server_default='cron'),
        sa.Column('cron_expression', sa.String(100), nullable=True),
        sa.Column('interval_seconds', sa.Integer(), nullable=True),
        sa.Column('start_datetime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_datetime', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('last_task_id', sa.String(255), nullable=True),
        sa.Column('func_name', sa.String(255), nullable=True),
        sa.Column('serialized_func', postgresql.BYTEA(), nullable=True),
        sa.Column('args', postgresql.BYTEA(), nullable=True),
        sa.Column('kwargs', postgresql.BYTEA(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('gpu_memory_mb', sa.Integer(), nullable=False, server_default='1024'),
        sa.Column('cpu_cores', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='3600'),
        sa.Column('gpu_type', sa.String(50), nullable=True),
        sa.Column('allow_fallback_cpu', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('tags', postgresql.JSONB(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=True),
        sa.Column('callback_url', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_scheduled_tasks_user_id', 'scheduled_tasks', ['user_id'])
    op.create_index('idx_scheduled_tasks_name', 'scheduled_tasks', ['name'])
    op.create_index('idx_scheduled_tasks_is_enabled', 'scheduled_tasks', ['is_enabled'])
    op.create_index('idx_scheduled_tasks_next_run_at', 'scheduled_tasks', ['next_run_at'])
    op.create_index('idx_scheduled_tasks_status', 'scheduled_tasks', ['status'])
    op.create_index('idx_scheduled_tasks_user_enabled', 'scheduled_tasks', ['user_id', 'is_enabled'])
    op.create_index('idx_scheduled_tasks_next_run_enabled', 'scheduled_tasks', ['next_run_at', 'is_enabled'])

    op.create_table(
        'scheduled_task_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('schedule_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('scheduled_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('task_id', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.BigInteger(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('result_summary', postgresql.JSONB(), nullable=True),
        sa.Column('trigger_type', sa.String(50), nullable=False, server_default='scheduled'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_scheduled_task_runs_schedule_id', 'scheduled_task_runs', ['schedule_id'])
    op.create_index('idx_scheduled_task_runs_user_id', 'scheduled_task_runs', ['user_id'])
    op.create_index('idx_scheduled_task_runs_task_id', 'scheduled_task_runs', ['task_id'])
    op.create_index('idx_scheduled_task_runs_status', 'scheduled_task_runs', ['status'])
    op.create_index('idx_scheduled_task_runs_schedule_created', 'scheduled_task_runs', ['schedule_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('scheduled_task_runs')
    op.drop_table('scheduled_tasks')
