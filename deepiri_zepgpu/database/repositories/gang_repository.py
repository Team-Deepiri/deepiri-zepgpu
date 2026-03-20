"""Gang scheduling repository for database operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.gang_scheduling import (
    GangTask,
    GangStatus,
    PreemptionRecord,
    FairShareBucket,
)


class GangScheduleRepository:
    """Repository for GangTask database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> GangTask:
        """Create a new gang task."""
        gang_task = GangTask(id=str(uuid.uuid4()), **kwargs)
        self.session.add(gang_task)
        await self.session.flush()
        return gang_task

    async def get_by_id(self, gang_task_id: str) -> GangTask | None:
        """Get gang task by ID."""
        result = await self.session.execute(
            select(GangTask).where(GangTask.id == gang_task_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str | None = None,
        status: GangStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[GangTask]:
        """List gang tasks."""
        query = select(GangTask)

        if user_id is not None:
            query = query.where(GangTask.user_id == user_id)
        if status is not None:
            query = query.where(GangTask.status == status)

        query = query.order_by(GangTask.priority.desc(), GangTask.created_at.asc()).limit(limit).offset(offset)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def list_pending(self, limit: int = 100) -> Sequence[GangTask]:
        """List pending gang tasks ordered by priority."""
        result = await self.session.execute(
            select(GangTask)
            .where(GangTask.status == GangStatus.PENDING)
            .order_by(GangTask.priority.desc(), GangTask.created_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def update_status(
        self,
        gang_task_id: str,
        status: GangStatus,
        **kwargs,
    ) -> GangTask | None:
        """Update gang task status."""
        gang_task = await self.get_by_id(gang_task_id)
        if not gang_task:
            return None

        gang_task.status = status

        if status == GangStatus.ALLOCATED:
            gang_task.started_at = datetime.utcnow()
        elif status == GangStatus.RUNNING:
            pass
        elif status in [GangStatus.COMPLETED, GangStatus.FAILED, GangStatus.CANCELLED]:
            gang_task.completed_at = datetime.utcnow()

        for key, value in kwargs.items():
            if hasattr(gang_task, key):
                setattr(gang_task, key, value)

        await self.session.flush()
        return gang_task

    async def mark_allocated(self, gang_task_id: str, gpu_ids: list[int]) -> GangTask | None:
        """Mark gang task as allocated with GPU IDs."""
        return await self.update_status(
            gang_task_id,
            GangStatus.ALLOCATED,
            allocated_gpu_ids=gpu_ids,
        )

    async def mark_running(self, gang_task_id: str) -> GangTask | None:
        """Mark gang task as running."""
        return await self.update_status(gang_task_id, GangStatus.RUNNING)

    async def mark_completed(self, gang_task_id: str) -> GangTask | None:
        """Mark gang task as completed."""
        return await self.update_status(gang_task_id, GangStatus.COMPLETED)

    async def mark_failed(self, gang_task_id: str, error: str, traceback: str | None = None) -> GangTask | None:
        """Mark gang task as failed."""
        return await self.update_status(
            gang_task_id,
            GangStatus.FAILED,
            error=error,
            traceback=traceback,
        )

    async def mark_cancelled(self, gang_task_id: str) -> GangTask | None:
        """Mark gang task as cancelled."""
        return await self.update_status(gang_task_id, GangStatus.CANCELLED)

    async def mark_partial_failure(self, gang_task_id: str, error: str) -> GangTask | None:
        """Mark gang task as partially failed (some GPUs failed)."""
        return await self.update_status(
            gang_task_id,
            GangStatus.PARTIAL_FAILURE,
            error=error,
        )


class PreemptionRepository:
    """Repository for PreemptionRecord database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> PreemptionRecord:
        """Create a new preemption record."""
        record = PreemptionRecord(id=str(uuid.uuid4()), **kwargs)
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_by_id(self, record_id: str) -> PreemptionRecord | None:
        """Get preemption record by ID."""
        result = await self.session.execute(
            select(PreemptionRecord).where(PreemptionRecord.id == record_id)
        )
        return result.scalar_one_or_none()

    async def list_by_gang_task(
        self,
        gang_task_id: str,
        limit: int = 50,
    ) -> Sequence[PreemptionRecord]:
        """List preemption records for a gang task."""
        result = await self.session.execute(
            select(PreemptionRecord)
            .where(PreemptionRecord.gang_task_id == gang_task_id)
            .order_by(PreemptionRecord.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def update_resume_status(
        self,
        record_id: str,
        attempted: bool,
        successful: bool | None = None,
    ) -> PreemptionRecord | None:
        """Update resume status for a preemption record."""
        record = await self.get_by_id(record_id)
        if not record:
            return None

        record.resume_attempted = attempted
        if successful is not None:
            record.resume_successful = successful
        record.resume_at = datetime.utcnow()

        await self.session.flush()
        return record


class FairShareRepository:
    """Repository for FairShareBucket database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> FairShareBucket:
        """Create a new fair share bucket."""
        bucket = FairShareBucket(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            **kwargs,
        )
        self.session.add(bucket)
        await self.session.flush()
        return bucket

    async def get_by_id(self, bucket_id: str) -> FairShareBucket | None:
        """Get fair share bucket by ID."""
        result = await self.session.execute(
            select(FairShareBucket).where(FairShareBucket.id == bucket_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user(self, user_id: str) -> FairShareBucket | None:
        """Get fair share bucket by user ID."""
        result = await self.session.execute(
            select(FairShareBucket).where(FairShareBucket.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create_for_user(
        self,
        user_id: str,
        weight: float = 1.0,
        gpu_seconds_limit: float | None = None,
        period_hours: int = 24,
    ) -> FairShareBucket:
        """Get or create fair share bucket for user."""
        bucket = await self.get_by_user(user_id)
        
        if bucket:
            if self._is_period_expired(bucket):
                bucket.gpu_seconds_used = 0
                bucket.tasks_completed = 0
                bucket.tasks_failed = 0
                bucket.tasks_preempted = 0
                bucket.period_start = datetime.utcnow()
                await self.session.flush()
            return bucket
        
        return await self.create(
            user_id=user_id,
            weight=weight,
            gpu_seconds_limit=gpu_seconds_limit,
            period_hours=period_hours,
            period_start=datetime.utcnow(),
            is_active=True,
        )

    def _is_period_expired(self, bucket: FairShareBucket) -> bool:
        """Check if the fair share period has expired."""
        if bucket.period_start is None:
            return True
        period_end = bucket.period_start + timedelta(hours=bucket.period_hours)
        return datetime.utcnow() > period_end

    async def record_gpu_usage(
        self,
        user_id: str,
        gpu_seconds: float,
        completed: bool = False,
        failed: bool = False,
        preempted: bool = False,
    ) -> FairShareBucket | None:
        """Record GPU usage for a user."""
        bucket = await self.get_by_user(user_id)
        if not bucket:
            return None

        bucket.gpu_seconds_used += gpu_seconds
        bucket.updated_at = datetime.utcnow()

        if completed:
            bucket.tasks_completed += 1
        elif failed:
            bucket.tasks_failed += 1
        elif preempted:
            bucket.tasks_preempted += 1

        await self.session.flush()
        return bucket

    async def update_weight(self, user_id: str, weight: float) -> FairShareBucket | None:
        """Update fair share weight for a user."""
        bucket = await self.get_by_user(user_id)
        if not bucket:
            return None

        bucket.weight = weight
        bucket.updated_at = datetime.utcnow()

        await self.session.flush()
        return bucket

    async def check_quota_available(self, user_id: str, required_gpu_seconds: float) -> bool:
        """Check if user has quota available for given GPU time."""
        bucket = await self.get_by_user(user_id)
        if not bucket:
            return True

        if not bucket.is_active:
            return False

        if bucket.gpu_seconds_limit is None:
            return True

        return (bucket.gpu_seconds_used + required_gpu_seconds) <= bucket.gpu_seconds_limit

    async def get_scheduling_weight(self, user_id: str) -> float:
        """Get the effective scheduling weight for a user.
        
        This considers both the user's base weight and their usage.
        Users over their quota get reduced weight.
        """
        bucket = await self.get_by_user(user_id)
        if not bucket:
            return 1.0

        if not bucket.is_active:
            return 0.0

        if bucket.gpu_seconds_limit is None or bucket.gpu_seconds_limit == 0:
            return bucket.weight

        usage_ratio = bucket.gpu_seconds_used / bucket.gpu_seconds_limit
        
        if usage_ratio >= 1.0:
            return 0.0
        elif usage_ratio >= 0.8:
            return bucket.weight * 0.25
        elif usage_ratio >= 0.6:
            return bucket.weight * 0.5
        elif usage_ratio >= 0.4:
            return bucket.weight * 0.75
        
        return bucket.weight

    async def list_all(self, limit: int = 100) -> Sequence[FairShareBucket]:
        """List all fair share buckets."""
        result = await self.session.execute(
            select(FairShareBucket)
            .where(FairShareBucket.is_active == True)
            .order_by(FairShareBucket.gpu_seconds_used.desc())
            .limit(limit)
        )
        return result.scalars().all()
