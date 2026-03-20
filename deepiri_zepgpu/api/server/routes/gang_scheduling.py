"""Gang scheduling API routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from pydantic import BaseModel, Field

from deepiri_zepgpu.api.server.dependencies import get_current_user, get_db_session
from deepiri_zepgpu.database.repositories import GangScheduleRepository, FairShareRepository
from deepiri_zepgpu.queue.tasks import execute_gang_task, check_and_preempt


router = APIRouter()


class GangTaskCreateRequest(BaseModel):
    """Gang task creation request."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    
    num_gpus_required: int = Field(default=2, ge=2, le=16)
    gpu_memory_mb_per_gpu: int = Field(default=1024, ge=0)
    gpu_type: str | None = None
    
    priority: int = Field(default=2, ge=1, le=5)
    allow_partial_allocation: bool = False
    
    func_name: str | None = None
    serialized_func: str | None = None
    args: str | None = None
    kwargs: str | None = None
    
    timeout_seconds: int = Field(default=7200, ge=1)
    
    can_be_preempted: bool = False
    checkpoint_interval_seconds: int | None = None
    
    callback_url: str | None = None
    tags: list[str] = []
    metadata: dict[str, Any] = {}


class GangTaskUpdateRequest(BaseModel):
    """Gang task update request."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    
    priority: int | None = Field(None, ge=1, le=5)
    can_be_preempted: bool | None = None
    
    timeout_seconds: int | None = Field(None, ge=1)


class GangTaskResponse(BaseModel):
    """Gang task response."""
    id: str
    name: str
    description: str | None
    status: str
    num_gpus_required: int
    allocated_gpu_ids: list[int] | None
    gpu_memory_mb_per_gpu: int
    gpu_type: str | None
    priority: int
    allow_partial_allocation: bool
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    can_be_preempted: bool
    child_task_ids: list[str] | None
    user_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class GangTaskListResponse(BaseModel):
    """Gang task list response."""
    tasks: list[GangTaskResponse]
    total: int
    limit: int
    offset: int


class PreemptionResponse(BaseModel):
    """Preemption response."""
    status: str
    preempted_task_id: str | None
    gang_task_id: str | None
    execution_time_ms: int | None


class FairShareResponse(BaseModel):
    """Fair share response."""
    user_id: str
    weight: float
    gpu_seconds_used: float
    gpu_seconds_limit: float | None
    gpu_hours_used: float
    gpu_hours_limit: float | None
    is_over_limit: bool
    is_active: bool


class FairShareUpdateRequest(BaseModel):
    """Fair share update request."""
    weight: float = Field(default=1.0, ge=0.1, le=10.0)
    gpu_seconds_limit: float | None = Field(None, ge=0)


@router.post("/gang", response_model=GangTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_gang_task(
    request: GangTaskCreateRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> GangTaskResponse:
    """Create a new gang scheduled task requiring multiple GPUs."""
    from deepiri_zepgpu.database.models import GangTask, GangStatus
    
    gang_task = GangTask(
        id=str(uuid.uuid4()),
        user_id=current_user.id if current_user else None,
        name=request.name,
        description=request.description,
        status=GangStatus.PENDING,
        num_gpus_required=request.num_gpus_required,
        gpu_memory_mb_per_gpu=request.gpu_memory_mb_per_gpu,
        gpu_type=request.gpu_type,
        priority=request.priority,
        allow_partial_allocation=request.allow_partial_allocation,
        func_name=request.func_name,
        serialized_func=request.serialized_func.encode() if request.serialized_func else None,
        args=request.args.encode() if request.args else None,
        kwargs=request.kwargs.encode() if request.kwargs else None,
        timeout_seconds=request.timeout_seconds,
        can_be_preempted=request.can_be_preempted,
        checkpoint_interval_seconds=request.checkpoint_interval_seconds,
        callback_url=request.callback_url,
        tags=request.tags,
        metadata_json=request.metadata,
    )
    
    db.add(gang_task)
    await db.flush()
    
    background_tasks.add_task(execute_gang_task.delay, gang_task.id)
    
    return GangTaskResponse(
        id=gang_task.id,
        name=gang_task.name,
        description=gang_task.description,
        status=gang_task.status.value,
        num_gpus_required=gang_task.num_gpus_required,
        allocated_gpu_ids=gang_task.allocated_gpu_ids,
        gpu_memory_mb_per_gpu=gang_task.gpu_memory_mb_per_gpu,
        gpu_type=gang_task.gpu_type,
        priority=gang_task.priority,
        allow_partial_allocation=gang_task.allow_partial_allocation,
        started_at=gang_task.started_at,
        completed_at=gang_task.completed_at,
        error=gang_task.error,
        can_be_preempted=gang_task.can_be_preempted,
        child_task_ids=gang_task.child_task_ids,
        user_id=gang_task.user_id,
        created_at=gang_task.created_at,
    )


@router.get("/gang", response_model=GangTaskListResponse)
async def list_gang_tasks(
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> GangTaskListResponse:
    """List gang tasks."""
    from deepiri_zepgpu.database.models import GangStatus as DBGangStatus
    
    repo = GangScheduleRepository(db)
    
    tasks = await repo.list_by_user(
        user_id=current_user.id if current_user else None,
        status=DBGangStatus(status_filter) if status_filter else None,
        limit=limit,
        offset=offset,
    )
    
    return GangTaskListResponse(
        tasks=[
            GangTaskResponse(
                id=t.id,
                name=t.name,
                description=t.description,
                status=t.status.value,
                num_gpus_required=t.num_gpus_required,
                allocated_gpu_ids=t.allocated_gpu_ids,
                gpu_memory_mb_per_gpu=t.gpu_memory_mb_per_gpu,
                gpu_type=t.gpu_type,
                priority=t.priority,
                allow_partial_allocation=t.allow_partial_allocation,
                started_at=t.started_at,
                completed_at=t.completed_at,
                error=t.error,
                can_be_preempted=t.can_be_preempted,
                child_task_ids=t.child_task_ids,
                user_id=t.user_id,
                created_at=t.created_at,
            )
            for t in tasks
        ],
        total=len(tasks),
        limit=limit,
        offset=offset,
    )


@router.get("/gang/{gang_task_id}", response_model=GangTaskResponse)
async def get_gang_task(
    gang_task_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> GangTaskResponse:
    """Get a gang task by ID."""
    repo = GangScheduleRepository(db)
    task = await repo.get_by_id(gang_task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Gang task not found")
    
    if current_user and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return GangTaskResponse(
        id=task.id,
        name=task.name,
        description=task.description,
        status=task.status.value,
        num_gpus_required=task.num_gpus_required,
        allocated_gpu_ids=task.allocated_gpu_ids,
        gpu_memory_mb_per_gpu=task.gpu_memory_mb_per_gpu,
        gpu_type=task.gpu_type,
        priority=task.priority,
        allow_partial_allocation=task.allow_partial_allocation,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error,
        can_be_preempted=task.can_be_preempted,
        child_task_ids=task.child_task_ids,
        user_id=task.user_id,
        created_at=task.created_at,
    )


@router.put("/gang/{gang_task_id}", response_model=GangTaskResponse)
async def update_gang_task(
    gang_task_id: str,
    request: GangTaskUpdateRequest,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> GangTaskResponse:
    """Update a gang task."""
    from deepiri_zepgpu.database.models import GangStatus as DBGangStatus
    
    repo = GangScheduleRepository(db)
    task = await repo.get_by_id(gang_task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Gang task not found")
    
    if current_user and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if task.status not in [DBGangStatus.PENDING, DBGangStatus.SCHEDULING]:
        raise HTTPException(status_code=400, detail="Cannot update task that is already running or completed")
    
    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(task, key):
            setattr(task, key, value)
    
    await db.flush()
    
    return GangTaskResponse(
        id=task.id,
        name=task.name,
        description=task.description,
        status=task.status.value,
        num_gpus_required=task.num_gpus_required,
        allocated_gpu_ids=task.allocated_gpu_ids,
        gpu_memory_mb_per_gpu=task.gpu_memory_mb_per_gpu,
        gpu_type=task.gpu_type,
        priority=task.priority,
        allow_partial_allocation=task.allow_partial_allocation,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error,
        can_be_preempted=task.can_be_preempted,
        child_task_ids=task.child_task_ids,
        user_id=task.user_id,
        created_at=task.created_at,
    )


@router.delete("/gang/{gang_task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_gang_task(
    gang_task_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> None:
    """Cancel a gang task."""
    from deepiri_zepgpu.database.models import GangStatus as DBGangStatus
    from deepiri_zepgpu.database.repositories import GPURepository
    
    repo = GangScheduleRepository(db)
    task = await repo.get_by_id(gang_task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Gang task not found")
    
    if current_user and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if task.status in [DBGangStatus.COMPLETED, DBGangStatus.FAILED, DBGangStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail="Task already terminated")
    
    if task.allocated_gpu_ids:
        gpu_repo = GPURepository(db)
        await gpu_repo.release_gang(gang_task_id)
    
    await repo.mark_cancelled(gang_task_id)


@router.post("/gang/{gang_task_id}/retry", response_model=GangTaskResponse)
async def retry_gang_task(
    gang_task_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> GangTaskResponse:
    """Retry a failed gang task."""
    from deepiri_zepgpu.database.models import GangStatus as DBGangStatus
    
    repo = GangScheduleRepository(db)
    task = await repo.get_by_id(gang_task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Gang task not found")
    
    if current_user and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if task.status not in [DBGangStatus.FAILED, DBGangStatus.CANCELLED, DBGangStatus.PARTIAL_FAILURE]:
        raise HTTPException(status_code=400, detail="Can only retry failed/cancelled/partial tasks")
    
    await repo.update_status(gang_task_id, DBGangStatus.PENDING)
    
    background_tasks.add_task(execute_gang_task.delay, gang_task_id)
    
    task = await repo.get_by_id(gang_task_id)
    
    return GangTaskResponse(
        id=task.id,
        name=task.name,
        description=task.description,
        status=task.status.value,
        num_gpus_required=task.num_gpus_required,
        allocated_gpu_ids=task.allocated_gpu_ids,
        gpu_memory_mb_per_gpu=task.gpu_memory_mb_per_gpu,
        gpu_type=task.gpu_type,
        priority=task.priority,
        allow_partial_allocation=task.allow_partial_allocation,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error,
        can_be_preempted=task.can_be_preempted,
        child_task_ids=task.child_task_ids,
        user_id=task.user_id,
        created_at=task.created_at,
    )


@router.post("/preempt/check")
async def trigger_preemption_check() -> dict[str, str]:
    """Trigger a preemption check manually."""
    check_and_preempt.delay()
    return {"status": "triggered", "message": "Preemption check triggered"}


@router.get("/fair-share/me", response_model=FairShareResponse)
async def get_my_fair_share(
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> FairShareResponse:
    """Get current user's fair share information."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    repo = FairShareRepository(db)
    bucket = await repo.get_or_create_for_user(str(current_user.id))
    
    return FairShareResponse(
        user_id=str(current_user.id),
        weight=bucket.weight,
        gpu_seconds_used=bucket.gpu_seconds_used,
        gpu_seconds_limit=bucket.gpu_seconds_limit,
        gpu_hours_used=bucket.gpu_hours_used,
        gpu_hours_limit=bucket.gpu_hours_limit,
        is_over_limit=bucket.is_over_limit,
        is_active=bucket.is_active,
    )


@router.put("/fair-share/me", response_model=FairShareResponse)
async def update_my_fair_share(
    request: FairShareUpdateRequest,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> FairShareResponse:
    """Update current user's fair share settings."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    repo = FairShareRepository(db)
    
    if request.gpu_seconds_limit is not None:
        await repo.get_or_create_for_user(
            str(current_user.id),
            gpu_seconds_limit=request.gpu_seconds_limit,
        )
    
    bucket = await repo.update_weight(str(current_user.id), request.weight)
    
    if not bucket:
        bucket = await repo.get_or_create_for_user(str(current_user.id))
    
    return FairShareResponse(
        user_id=str(current_user.id),
        weight=bucket.weight,
        gpu_seconds_used=bucket.gpu_seconds_used,
        gpu_seconds_limit=bucket.gpu_seconds_limit,
        gpu_hours_used=bucket.gpu_hours_used,
        gpu_hours_limit=bucket.gpu_hours_limit,
        is_over_limit=bucket.is_over_limit,
        is_active=bucket.is_active,
    )


@router.get("/fair-share/weights")
async def get_all_fair_share_weights() -> dict[str, Any]:
    """Get fair share weights for all users (admin only)."""
    from deepiri_zepgpu.queue.tasks import get_fair_share_weights
    
    result = get_fair_share_weights.delay()
    weights = result.get(timeout=10)
    
    return weights
