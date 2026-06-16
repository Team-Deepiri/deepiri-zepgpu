"""Pipeline API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_current_user, get_db_session
from deepiri_zepgpu.database.models import Pipeline, User
from deepiri_zepgpu.database.models.pipeline import PipelineStatus as DBPipelineStatus
from deepiri_zepgpu.database.repositories import PipelineRepository

router = APIRouter()


class PipelineStageRequest(BaseModel):
    """Pipeline stage request."""

    name: str
    func_name: str | None = None
    args: dict[str, Any] = {}
    depends_on: list[str] = []
    gpu_memory_mb: int = Field(default=1024, ge=0)
    timeout_seconds: int = Field(default=3600, ge=1)
    retry_count: int = Field(default=3, ge=0)


class PipelineCreateRequest(BaseModel):
    """Pipeline creation request."""

    name: str
    description: str | None = None
    stages: list[PipelineStageRequest]


class PipelineResponse(BaseModel):
    """Pipeline response."""

    id: str
    name: str
    description: str | None
    status: str
    stages: list[dict[str, Any]]
    stage_statuses: dict[str, str] | None
    completed_stages: int
    total_stages: int
    progress_percent: float
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    user_id: str | None

    class Config:
        from_attributes = True


class PipelineListResponse(BaseModel):
    """Pipeline list response."""

    pipelines: list[PipelineResponse]
    total: int
    limit: int
    offset: int


def build_pipeline_response(pipeline: Pipeline) -> PipelineResponse:
    """Build a safe pipeline response with UUIDs converted to strings."""

    return PipelineResponse(
        id=str(pipeline.id),
        name=pipeline.name,
        description=pipeline.description,
        status=pipeline.status.value,
        stages=pipeline.stages,
        stage_statuses=pipeline.stage_statuses,
        completed_stages=pipeline.completed_stages,
        total_stages=len(pipeline.stages),
        progress_percent=pipeline.progress_percent,
        created_at=pipeline.created_at,
        started_at=pipeline.started_at,
        completed_at=pipeline.completed_at,
        error=pipeline.error,
        user_id=str(pipeline.user_id) if pipeline.user_id else None,
    )


def user_owns_pipeline(current_user: Any, pipeline: Pipeline) -> bool:
    """Check whether the current user owns the pipeline."""

    if not current_user:
        return True

    return str(pipeline.user_id) == str(current_user.id)


def enqueue_pipeline_to_celery(pipeline_id: str) -> None:
    """Enqueue pipeline execution to Celery."""

    import logging

    from deepiri_zepgpu.queue.tasks import execute_pipeline

    logger = logging.getLogger(__name__)
    async_result = execute_pipeline.apply_async(args=[pipeline_id], queue="celery")
    logger.info(
        "Enqueued pipeline %s to Celery with celery_task_id=%s",
        pipeline_id,
        async_result.id,
    )


@router.post("", response_model=PipelineResponse, status_code=status.HTTP_201_CREATED)
async def create_pipeline(
    request: PipelineCreateRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
) -> PipelineResponse:
    """Create a new pipeline."""

    import uuid

    stages_data = [
        {
            "name": stage.name,
            "func_name": stage.func_name,
            "args": stage.args,
            "depends_on": stage.depends_on,
            "gpu_memory_mb": stage.gpu_memory_mb,
            "timeout_seconds": stage.timeout_seconds,
            "retry_count": stage.retry_count,
        }
        for stage in request.stages
    ]

    pipeline = Pipeline(
        id=str(uuid.uuid4()),
        user_id=current_user.id if current_user else None,
        name=request.name,
        description=request.description,
        stages=stages_data,
        stage_statuses={stage.name: "pending" for stage in request.stages},
        status=DBPipelineStatus.CREATED,
    )

    db.add(pipeline)
    await db.flush()

    return build_pipeline_response(pipeline)


@router.get("", response_model=PipelineListResponse)
async def list_pipelines(
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> PipelineListResponse:
    """List pipelines."""

    repo = PipelineRepository(db)

    assert current_user is not None
    pipelines = await repo.list_by_user(
        user_id=current_user.id,
        status=DBPipelineStatus(status_filter) if status_filter else None,
        limit=limit,
        offset=offset,
    )

    return PipelineListResponse(
        pipelines=[build_pipeline_response(pipeline) for pipeline in pipelines],
        total=len(pipelines),
        limit=limit,
        offset=offset,
    )


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
) -> PipelineResponse:
    """Get pipeline by ID."""

    repo = PipelineRepository(db)
    pipeline = await repo.get_by_id(pipeline_id)

    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    if not user_owns_pipeline(current_user, pipeline):
        raise HTTPException(status_code=403, detail="Access denied")

    return build_pipeline_response(pipeline)


@router.post("/{pipeline_id}/run")
async def run_pipeline(
    pipeline_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
) -> dict[str, str]:
    """Run a pipeline."""

    repo = PipelineRepository(db)
    pipeline = await repo.get_by_id(pipeline_id)

    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    if not user_owns_pipeline(current_user, pipeline):
        raise HTTPException(status_code=403, detail="Access denied")

    await repo.mark_running(pipeline_id)
    background_tasks.add_task(enqueue_pipeline_to_celery, pipeline_id)

    return {
        "message": "Pipeline started",
        "pipeline_id": pipeline_id,
    }


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(
    pipeline_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
) -> None:
    """Delete a pipeline."""

    repo = PipelineRepository(db)
    pipeline = await repo.get_by_id(pipeline_id)

    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    if not user_owns_pipeline(current_user, pipeline):
        raise HTTPException(status_code=403, detail="Access denied")

    await repo.delete(pipeline_id)
