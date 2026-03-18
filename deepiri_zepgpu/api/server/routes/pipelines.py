"""Pipeline API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from deepiri_zepgpu.api.server.dependencies import get_current_user, get_db_session
from deepiri_zepgpu.database.models import Pipeline
from deepiri_zepgpu.database.repositories import PipelineRepository
from deepiri_zepgpu.database.models.pipeline import PipelineStatus as DBPipelineStatus


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


@router.post("", response_model=PipelineResponse, status_code=status.HTTP_201_CREATED)
async def create_pipeline(
    request: PipelineCreateRequest,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
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
    
    return PipelineResponse(
        id=pipeline.id,
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
        user_id=pipeline.user_id,
    )


@router.get("", response_model=PipelineListResponse)
async def list_pipelines(
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> PipelineListResponse:
    """List pipelines."""
    repo = PipelineRepository(db)
    
    pipelines = await repo.list_by_user(
        user_id=current_user.id,
        status=DBPipelineStatus(status_filter) if status_filter else None,
        limit=limit,
        offset=offset,
    )
    
    return PipelineListResponse(
        pipelines=[
            PipelineResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                status=p.status.value,
                stages=p.stages,
                stage_statuses=p.stage_statuses,
                completed_stages=p.completed_stages,
                total_stages=len(p.stages),
                progress_percent=p.progress_percent,
                created_at=p.created_at,
                started_at=p.started_at,
                completed_at=p.completed_at,
                error=p.error,
                user_id=p.user_id,
            )
            for p in pipelines
        ],
        total=len(pipelines),
        limit=limit,
        offset=offset,
    )


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    pipeline_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> PipelineResponse:
    """Get pipeline by ID."""
    repo = PipelineRepository(db)
    pipeline = await repo.get_by_id(pipeline_id)
    
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    
    if current_user and pipeline.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return PipelineResponse(
        id=pipeline.id,
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
        user_id=pipeline.user_id,
    )


@router.post("/{pipeline_id}/run")
async def run_pipeline(
    pipeline_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> dict:
    """Run a pipeline."""
    from deepiri_zepgpu.queue.tasks import execute_pipeline
    
    repo = PipelineRepository(db)
    pipeline = await repo.get_by_id(pipeline_id)
    
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    
    if current_user and pipeline.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    await repo.mark_running(pipeline_id)
    background_tasks.add_task(execute_pipeline.delay, pipeline_id)
    
    return {"message": "Pipeline started", "pipeline_id": pipeline_id}


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(
    pipeline_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> None:
    """Delete a pipeline."""
    repo = PipelineRepository(db)
    pipeline = await repo.get_by_id(pipeline_id)
    
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    
    if current_user and pipeline.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    await repo.delete(pipeline_id)
