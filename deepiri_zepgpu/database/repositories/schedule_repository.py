"""Scheduled task repository for database operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepiri_zepgpu.database.models.scheduled_task import ScheduledTask, ScheduleStatus, ScheduleType
from deepiri_zepgpu.database.models.scheduled_task_run import ScheduledTaskRun, ScheduleRunStatus


class ScheduleRepository:
    """Repository for ScheduledTask database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> ScheduledTask:
        """Create a new scheduled task."""
        schedule = ScheduledTask(id=str(uuid.uuid4()), **kwargs)
        self.session.add(schedule)
        await self.session.flush()
        return schedule

    async def get_by_id(self, schedule_id: str) -> ScheduledTask | None:
        """Get scheduled task by ID."""
        result = await self.session.execute(
            select(ScheduledTask).where(ScheduledTask.id == schedule_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_user(self, schedule_id: str) -> ScheduledTask | None:
        """Get scheduled task by ID with user loaded."""
        result = await self.session.execute(
            select(ScheduledTask)
            .options(selectinload(ScheduledTask.user))
            .where(ScheduledTask.id == schedule_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str | None = None,
        is_enabled: bool | None = None,
        status: ScheduleStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ScheduledTask]:
        """List scheduled tasks."""
        query = select(ScheduledTask)

        if user_id is not None:
            query = query.where(ScheduledTask.user_id == user_id)
        if is_enabled is not None:
            query = query.where(ScheduledTask.is_enabled == is_enabled)
        if status is not None:
            query = query.where(ScheduledTask.status == status)

        query = query.order_by(ScheduledTask.created_at.desc()).limit(limit).offset(offset)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_enabled_schedules(self) -> Sequence[ScheduledTask]:
        """Get all enabled schedules."""
        result = await self.session.execute(
            select(ScheduledTask)
            .where(
                and_(
                    ScheduledTask.is_enabled == True,
                    ScheduledTask.status == ScheduleStatus.ACTIVE,
                )
            )
            .order_by(ScheduledTask.next_run_at.asc())
        )
        return result.scalars().all()

    async def get_due_schedules(self, before_time: datetime | None = None) -> Sequence[ScheduledTask]:
        """Get schedules that are due to run."""
        if before_time is None:
            before_time = datetime.utcnow()

        result = await self.session.execute(
            select(ScheduledTask)
            .where(
                and_(
                    ScheduledTask.is_enabled == True,
                    ScheduledTask.status == ScheduleStatus.ACTIVE,
                    ScheduledTask.next_run_at <= before_time,
                )
            )
            .order_by(ScheduledTask.next_run_at.asc())
        )
        return result.scalars().all()

    async def update(
        self,
        schedule_id: str,
        **kwargs,
    ) -> ScheduledTask | None:
        """Update a scheduled task."""
        schedule = await self.get_by_id(schedule_id)
        if not schedule:
            return None

        for key, value in kwargs.items():
            if hasattr(schedule, key):
                setattr(schedule, key, value)

        await self.session.flush()
        return schedule

    async def enable(self, schedule_id: str) -> ScheduledTask | None:
        """Enable a scheduled task."""
        return await self.update(schedule_id, is_enabled=True, status=ScheduleStatus.ACTIVE)

    async def disable(self, schedule_id: str) -> ScheduledTask | None:
        """Disable a scheduled task."""
        return await self.update(schedule_id, is_enabled=False, status=ScheduleStatus.PAUSED)

    async def delete(self, schedule_id: str) -> bool:
        """Delete a scheduled task."""
        schedule = await self.get_by_id(schedule_id)
        if not schedule:
            return False

        await self.session.delete(schedule)
        await self.session.flush()
        return True

    async def update_next_run(self, schedule_id: str, next_run_at: datetime) -> ScheduledTask | None:
        """Update the next run time for a schedule."""
        return await self.update(schedule_id, next_run_at=next_run_at)

    async def record_run(
        self,
        schedule_id: str,
        task_id: str | None = None,
        error: str | None = None,
    ) -> ScheduledTask | None:
        """Record a run for a scheduled task."""
        schedule = await self.get_by_id(schedule_id)
        if not schedule:
            return None

        schedule.last_run_at = datetime.utcnow()
        schedule.run_count += 1
        schedule.last_task_id = task_id

        if error:
            schedule.consecutive_failures += 1
            schedule.last_error = error
            if schedule.consecutive_failures >= 5:
                schedule.status = ScheduleStatus.FAILED
                schedule.is_enabled = False
        else:
            schedule.consecutive_failures = 0
            schedule.last_error = None

        await self.session.flush()
        return schedule

    async def calculate_next_run(self, schedule_id: str) -> datetime | None:
        """Calculate and update the next run time for a schedule."""
        from croniter import croniter

        schedule = await self.get_by_id(schedule_id)
        if not schedule:
            return None

        now = datetime.utcnow()
        next_run = None

        if schedule.schedule_type == ScheduleType.CRON and schedule.cron_expression:
            try:
                cron = croniter(schedule.cron_expression, now)
                next_run = cron.get_next(datetime)
            except ValueError:
                pass

        elif schedule.schedule_type == ScheduleType.INTERVAL and schedule.interval_seconds:
            if schedule.last_run_at:
                next_run = schedule.last_run_at + timedelta(seconds=schedule.interval_seconds)
            else:
                next_run = now + timedelta(seconds=schedule.interval_seconds)

        elif schedule.schedule_type == ScheduleType.ONCE:
            next_run = None
            schedule.status = ScheduleStatus.COMPLETED
            schedule.is_enabled = False

        if next_run and schedule.end_datetime and next_run > schedule.end_datetime:
            next_run = None
            schedule.status = ScheduleStatus.COMPLETED
            schedule.is_enabled = False

        schedule.next_run_at = next_run
        await self.session.flush()
        return next_run

    async def count_by_user(self, user_id: str) -> int:
        """Count schedules by user."""
        result = await self.session.execute(
            select(func.count(ScheduledTask.id)).where(ScheduledTask.user_id == user_id)
        )
        return result.scalar() or 0


class ScheduleRunRepository:
    """Repository for ScheduledTaskRun database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> ScheduledTaskRun:
        """Create a new scheduled task run record."""
        run = ScheduledTaskRun(id=str(uuid.uuid4()), **kwargs)
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_by_id(self, run_id: str) -> ScheduledTaskRun | None:
        """Get run by ID."""
        result = await self.session.execute(
            select(ScheduledTaskRun).where(ScheduledTaskRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_by_schedule(
        self,
        schedule_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[ScheduledTaskRun]:
        """List runs for a schedule."""
        result = await self.session.execute(
            select(ScheduledTaskRun)
            .where(ScheduledTaskRun.schedule_id == schedule_id)
            .order_by(ScheduledTaskRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def list_by_user(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[ScheduledTaskRun]:
        """List runs for a user."""
        result = await self.session.execute(
            select(ScheduledTaskRun)
            .where(ScheduledTaskRun.user_id == user_id)
            .order_by(ScheduledTaskRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def update_status(
        self,
        run_id: str,
        status: ScheduleRunStatus,
        error: str | None = None,
        traceback: str | None = None,
        duration_ms: int | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> ScheduledTaskRun | None:
        """Update run status."""
        run = await self.get_by_id(run_id)
        if not run:
            return None

        run.status = status

        if status == ScheduleRunStatus.RUNNING:
            run.started_at = datetime.utcnow()
        elif status in [ScheduleRunStatus.COMPLETED, ScheduleRunStatus.FAILED, ScheduleRunStatus.CANCELLED]:
            run.completed_at = datetime.utcnow()
            if run.started_at:
                run.duration_ms = int((run.completed_at - run.started_at).total_seconds() * 1000)

        if error:
            run.error = error
        if traceback:
            run.traceback = traceback
        if duration_ms is not None:
            run.duration_ms = duration_ms
        if result_summary:
            run.result_summary = result_summary

        await self.session.flush()
        return run

    async def mark_running(self, run_id: str) -> ScheduledTaskRun | None:
        """Mark run as running."""
        return await self.update_status(run_id, ScheduleRunStatus.RUNNING)

    async def mark_completed(
        self,
        run_id: str,
        result_summary: dict[str, Any] | None = None,
    ) -> ScheduledTaskRun | None:
        """Mark run as completed."""
        return await self.update_status(
            run_id,
            ScheduleRunStatus.COMPLETED,
            result_summary=result_summary,
        )

    async def mark_failed(
        self,
        run_id: str,
        error: str,
        traceback: str | None = None,
    ) -> ScheduledTaskRun | None:
        """Mark run as failed."""
        return await self.update_status(
            run_id,
            ScheduleRunStatus.FAILED,
            error=error,
            traceback=traceback,
        )

    async def mark_cancelled(self, run_id: str) -> ScheduledTaskRun | None:
        """Mark run as cancelled."""
        return await self.update_status(run_id, ScheduleRunStatus.CANCELLED)

    async def delete_old_runs(self, days: int = 30) -> int:
        """Delete old run records."""
        cutoff = datetime.utcnow() - timedelta(days=days)

        result = await self.session.execute(
            update(ScheduledTaskRun)
            .where(
                and_(
                    ScheduledTaskRun.created_at < cutoff,
                    ScheduledTaskRun.status.in_([
                        ScheduleRunStatus.COMPLETED,
                        ScheduleRunStatus.FAILED,
                        ScheduleRunStatus.CANCELLED,
                    ])
                )
            )
            .values(result_summary=None)
        )
        await self.session.flush()
        return result.rowcount or 0
