"""Pipeline repository for database operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.pipeline import Pipeline, PipelineStatus


class PipelineRepository:
    """Repository for Pipeline database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: str | None,
        name: str,
        stages: list[dict[str, Any]],
        description: str | None = None,
        **kwargs,
    ) -> Pipeline:
        """Create a new pipeline."""
        pipeline = Pipeline(
            id=str(uuid.uuid4()),
            user_id=user_id,
            name=name,
            description=description,
            stages=stages,
            stage_statuses={stage["name"]: "pending" for stage in stages},
            **kwargs,
        )
        self.session.add(pipeline)
        await self.session.flush()
        return pipeline

    async def get_by_id(self, pipeline_id: str) -> Pipeline | None:
        """Get pipeline by ID."""
        result = await self.session.execute(
            select(Pipeline).where(Pipeline.id == pipeline_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_user(self, pipeline_id: str) -> Pipeline | None:
        """Get pipeline by ID with user loaded."""
        result = await self.session.execute(
            select(Pipeline)
            .where(Pipeline.id == pipeline_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str,
        status: PipelineStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Pipeline]:
        """List pipelines for a user."""
        query = select(Pipeline).where(Pipeline.user_id == user_id)
        
        if status:
            query = query.where(Pipeline.status == status)
        
        query = query.order_by(Pipeline.created_at.desc()).limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return result.scalars().all()

    async def update_status(
        self,
        pipeline_id: str,
        status: PipelineStatus,
        **kwargs,
    ) -> Pipeline | None:
        """Update pipeline status."""
        pipeline = await self.get_by_id(pipeline_id)
        if not pipeline:
            return None
        
        pipeline.status = status
        
        if status == PipelineStatus.RUNNING:
            pipeline.started_at = datetime.utcnow()
        elif status in [PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.CANCELLED]:
            pipeline.completed_at = datetime.utcnow()
        
        for key, value in kwargs.items():
            if hasattr(pipeline, key):
                setattr(pipeline, key, value)
        
        await self.session.flush()
        return pipeline

    async def update_stage_status(
        self,
        pipeline_id: str,
        stage_name: str,
        stage_status: str,
        result: Any = None,
    ) -> Pipeline | None:
        """Update pipeline stage status."""
        pipeline = await self.get_by_id(pipeline_id)
        if not pipeline:
            return None
        
        if pipeline.stage_statuses is None:
            pipeline.stage_statuses = {}
        
        pipeline.stage_statuses[stage_name] = stage_status
        
        if result is not None:
            if pipeline.stage_results is None:
                pipeline.stage_results = {}
            pipeline.stage_results[stage_name] = result
        
        if stage_status == "completed":
            pipeline.completed_stages += 1
        
        pipeline.current_stage = stage_name
        
        await self.session.flush()
        return pipeline

    async def mark_running(self, pipeline_id: str) -> Pipeline | None:
        """Mark pipeline as running."""
        return await self.update_status(pipeline_id, PipelineStatus.RUNNING)

    async def mark_completed(
        self,
        pipeline_id: str,
        total_execution_time_ms: int | None = None,
    ) -> Pipeline | None:
        """Mark pipeline as completed."""
        return await self.update_status(
            pipeline_id,
            PipelineStatus.COMPLETED,
            total_execution_time_ms=total_execution_time_ms,
        )

    async def mark_failed(self, pipeline_id: str, error: str) -> Pipeline | None:
        """Mark pipeline as failed."""
        return await self.update_status(pipeline_id, PipelineStatus.FAILED, error=error)

    async def mark_cancelled(self, pipeline_id: str) -> Pipeline | None:
        """Mark pipeline as cancelled."""
        return await self.update_status(pipeline_id, PipelineStatus.CANCELLED)

    async def delete(self, pipeline_id: str) -> bool:
        """Delete pipeline."""
        pipeline = await self.get_by_id(pipeline_id)
        if not pipeline:
            return False
        
        await self.session.delete(pipeline)
        await self.session.flush()
        return True

    async def count_by_status(self, status: PipelineStatus) -> int:
        """Count pipelines by status."""
        result = await self.session.execute(
            select(func.count(Pipeline.id)).where(Pipeline.status == status)
        )
        return result.scalar() or 0
