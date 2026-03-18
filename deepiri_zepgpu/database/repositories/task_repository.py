"""Task repository for database operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepiri_zepgpu.database.models.task import Task, TaskPriority, TaskStatus


class TaskRepository:
    """Repository for Task database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> Task:
        """Create a new task."""
        task = Task(id=str(uuid.uuid4()), **kwargs)
        self.session.add(task)
        await self.session.flush()
        return task

    async def get_by_id(self, task_id: str) -> Task | None:
        """Get task by ID."""
        result = await self.session.execute(
            select(Task).where(Task.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_user(self, task_id: str) -> Task | None:
        """Get task by ID with user loaded."""
        result = await self.session.execute(
            select(Task)
            .options(selectinload(Task.user))
            .where(Task.id == task_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Task]:
        """List tasks for a user."""
        query = select(Task).where(Task.user_id == user_id)
        
        if status:
            query = query.where(Task.status == status)
        
        query = query.order_by(Task.created_at.desc()).limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return result.scalars().all()

    async def list_by_status(
        self,
        status: TaskStatus,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Task]:
        """List tasks by status."""
        result = await self.session.execute(
            select(Task)
            .where(Task.status == status)
            .order_by(Task.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def list_pending(self, limit: int = 100) -> Sequence[Task]:
        """List pending tasks ordered by priority."""
        result = await self.session.execute(
            select(Task)
            .where(Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED]))
            .order_by(Task.priority.desc(), Task.created_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        **kwargs,
    ) -> Task | None:
        """Update task status and optional fields."""
        task = await self.get_by_id(task_id)
        if not task:
            return None
        
        task.status = status
        
        if status == TaskStatus.RUNNING:
            task.started_at = datetime.utcnow()
        elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMEOUT]:
            task.completed_at = datetime.utcnow()
        
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        
        await self.session.flush()
        return task

    async def mark_running(
        self,
        task_id: str,
        gpu_device_id: int | None = None,
        container_id: str | None = None,
    ) -> Task | None:
        """Mark task as running."""
        return await self.update_status(
            task_id,
            TaskStatus.RUNNING,
            gpu_device_id=gpu_device_id,
            container_id=container_id,
        )

    async def mark_completed(
        self,
        task_id: str,
        result_ref: str | None = None,
        execution_time_ms: int | None = None,
    ) -> Task | None:
        """Mark task as completed."""
        return await self.update_status(
            task_id,
            TaskStatus.COMPLETED,
            result_ref=result_ref,
            execution_time_ms=execution_time_ms,
        )

    async def mark_failed(
        self,
        task_id: str,
        error: str,
        traceback: str | None = None,
    ) -> Task | None:
        """Mark task as failed."""
        return await self.update_status(
            task_id,
            TaskStatus.FAILED,
            error=error,
            traceback=traceback,
        )

    async def mark_cancelled(self, task_id: str) -> Task | None:
        """Mark task as cancelled."""
        return await self.update_status(task_id, TaskStatus.CANCELLED)

    async def mark_timeout(self, task_id: str) -> Task | None:
        """Mark task as timed out."""
        return await self.update_status(task_id, TaskStatus.TIMEOUT)

    async def count_by_status(self, status: TaskStatus) -> int:
        """Count tasks by status."""
        result = await self.session.execute(
            select(func.count(Task.id)).where(Task.status == status)
        )
        return result.scalar() or 0

    async def count_by_user(self, user_id: str) -> int:
        """Count tasks by user."""
        result = await self.session.execute(
            select(func.count(Task.id)).where(Task.user_id == user_id)
        )
        return result.scalar() or 0

    async def get_user_stats(self, user_id: str) -> dict[str, Any]:
        """Get task statistics for a user."""
        result = await self.session.execute(
            select(
                Task.status,
                func.count(Task.id).label("count"),
            )
            .where(Task.user_id == user_id)
            .group_by(Task.status)
        )
        
        stats = {status.value: 0 for status in TaskStatus}
        for row in result:
            stats[row.status.value] = row.count
        
        return stats

    async def delete_old_completed(self, days: int = 7) -> int:
        """Delete old completed tasks."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        result = await self.session.execute(
            update(Task)
            .where(
                and_(
                    Task.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]),
                    Task.created_at < cutoff,
                )
            )
            .values(metadata_json={"deleted": True})
        )
        await self.session.flush()
        return result.rowcount or 0
