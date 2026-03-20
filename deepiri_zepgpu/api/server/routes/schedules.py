"""Schedule API routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from pydantic import BaseModel, Field, field_validator

from deepiri_zepgpu.api.server.dependencies import get_current_user, get_db_session
from deepiri_zepgpu.database.models.task import TaskPriority as DBTaskPriority
from deepiri_zepgpu.database.repositories import ScheduleRepository, ScheduleRunRepository
from deepiri_zepgpu.queue.tasks import execute_scheduled_task, execute_delayed_task, sync_schedules_to_beat
from deepiri_zepgpu.queue.beat_sync import beat_scheduler_sync


router = APIRouter()


class ScheduleCreateRequest(BaseModel):
    """Schedule creation request."""
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    
    schedule_type: str = Field(..., pattern="^(cron|interval|once)$")
    cron_expression: str | None = Field(None, max_length=100)
    interval_seconds: int | None = Field(None, ge=60)
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    
    func_name: str | None = None
    serialized_func: str | None = None
    args: str | None = None
    kwargs: str | None = None
    
    priority: int = Field(default=2, ge=1, le=5)
    gpu_memory_mb: int = Field(default=1024, ge=0)
    cpu_cores: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=3600, ge=1)
    gpu_type: str | None = None
    allow_fallback_cpu: bool = True
    
    tags: list[str] = []
    metadata: dict[str, Any] = {}
    callback_url: str | None = None
    
    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                croniter(v)
            except ValueError:
                raise ValueError(f"Invalid cron expression: {v}")
        return v
    
    @field_validator("interval_seconds")
    @classmethod
    def validate_interval(cls, v: int | None) -> int | None:
        if v is not None and v < 60:
            raise ValueError("Interval must be at least 60 seconds")
        return v


class ScheduleUpdateRequest(BaseModel):
    """Schedule update request."""
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    
    cron_expression: str | None = Field(None, max_length=100)
    interval_seconds: int | None = Field(None, ge=60)
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    
    priority: int | None = Field(None, ge=1, le=5)
    gpu_memory_mb: int | None = Field(None, ge=0)
    cpu_cores: int | None = Field(None, ge=1)
    timeout_seconds: int | None = Field(None, ge=1)
    gpu_type: str | None = None
    allow_fallback_cpu: bool | None = None
    
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    callback_url: str | None = None
    
    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                croniter(v)
            except ValueError:
                raise ValueError(f"Invalid cron expression: {v}")
        return v


class ScheduleResponse(BaseModel):
    """Schedule response."""
    id: str
    name: str
    description: str | None
    schedule_type: str
    cron_expression: str | None
    interval_seconds: int | None
    start_datetime: datetime | None
    end_datetime: datetime | None
    is_enabled: bool
    status: str
    last_run_at: datetime | None
    next_run_at: datetime | None
    run_count: int
    consecutive_failures: int
    last_error: str | None
    priority: int
    gpu_memory_mb: int
    timeout_seconds: int
    created_at: datetime
    user_id: str | None

    class Config:
        from_attributes = True


class ScheduleListResponse(BaseModel):
    """Schedule list response."""
    schedules: list[ScheduleResponse]
    total: int
    limit: int
    offset: int


class ScheduleRunResponse(BaseModel):
    """Schedule run response."""
    id: str
    schedule_id: str
    task_id: str | None
    status: str
    scheduled_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error: str | None
    trigger_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class ScheduleRunListResponse(BaseModel):
    """Schedule run list response."""
    runs: list[ScheduleRunResponse]
    total: int
    limit: int
    offset: int


class DelayedTaskRequest(BaseModel):
    """Delayed task request."""
    name: str | None = None
    func_name: str | None = None
    serialized_func: str | None = None
    args: str | None = None
    kwargs: str | None = None
    
    priority: int = Field(default=2, ge=1, le=5)
    gpu_memory_mb: int = Field(default=1024, ge=0)
    cpu_cores: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=3600, ge=1)
    gpu_type: str | None = None
    allow_fallback_cpu: bool = True
    
    execute_at: datetime = Field(..., description="When to execute the task")
    tags: list[str] = []
    metadata: dict[str, Any] = {}
    callback_url: str | None = None


class DelayedTaskResponse(BaseModel):
    """Delayed task response."""
    task_id: str
    execute_at: datetime
    status: str


async def _sync_schedule_to_beat(schedule_id: str) -> None:
    """Sync a schedule to Celery Beat (background task)."""
    from deepiri_zepgpu.database.session import get_db_context
    from deepiri_zepgpu.database.repositories import ScheduleRepository
    from deepiri_zepgpu.database.models.scheduled_task import ScheduleType
    
    async with get_db_context() as db:
        repo = ScheduleRepository(db)
        schedule = await repo.get_by_id(schedule_id)
        
        if not schedule:
            return
        
        if schedule.schedule_type == ScheduleType.CRON and schedule.cron_expression:
            beat_scheduler_sync.sync_schedule(
                schedule_id=schedule.id,
                task_name="deepiri_zepgpu.queue.tasks.execute_scheduled_task",
                args=(schedule.id,),
                schedule_type="cron",
                cron_expr=schedule.cron_expression,
            )
        elif schedule.schedule_type == ScheduleType.INTERVAL and schedule.interval_seconds:
            beat_scheduler_sync.sync_schedule(
                schedule_id=schedule.id,
                task_name="deepiri_zepgpu.queue.tasks.execute_scheduled_task",
                args=(schedule.id,),
                schedule_type="interval",
                interval_seconds=schedule.interval_seconds,
            )
        elif schedule.schedule_type == ScheduleType.ONCE and schedule.start_datetime:
            beat_scheduler_sync.sync_schedule(
                schedule_id=schedule.id,
                task_name="deepiri_zepgpu.queue.tasks.execute_scheduled_task",
                args=(schedule.id,),
                schedule_type="once",
                run_at=schedule.start_datetime,
            )


def _calculate_next_run(
    schedule_type: str,
    cron_expression: str | None = None,
    interval_seconds: int | None = None,
    start_datetime: datetime | None = None,
) -> datetime | None:
    """Calculate the next run time for a schedule."""
    now = datetime.utcnow()
    
    if schedule_type == "cron" and cron_expression:
        try:
            cron = croniter(cron_expression, now)
            return cron.get_next(datetime)
        except ValueError:
            return None
    
    elif schedule_type == "interval" and interval_seconds:
        return now + timedelta(seconds=interval_seconds)
    
    elif schedule_type == "once" and start_datetime:
        if start_datetime > now:
            return start_datetime
        return None
    
    return None


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    request: ScheduleCreateRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> ScheduleResponse:
    """Create a new scheduled task."""
    from deepiri_zepgpu.database.models import ScheduledTask, ScheduleType as DBScheduleType
    
    if request.schedule_type == "cron" and not request.cron_expression:
        raise HTTPException(status_code=400, detail="Cron expression required for cron schedule")
    if request.schedule_type == "interval" and not request.interval_seconds:
        raise HTTPException(status_code=400, detail="Interval required for interval schedule")
    
    next_run_at = _calculate_next_run(
        request.schedule_type,
        request.cron_expression,
        request.interval_seconds,
        request.start_datetime,
    )
    
    schedule = ScheduledTask(
        id=str(uuid.uuid4()),
        user_id=current_user.id if current_user else None,
        name=request.name,
        description=request.description,
        schedule_type=DBScheduleType(request.schedule_type),
        cron_expression=request.cron_expression,
        interval_seconds=request.interval_seconds,
        start_datetime=request.start_datetime,
        end_datetime=request.end_datetime,
        is_enabled=True,
        func_name=request.func_name,
        serialized_func=request.serialized_func.encode() if request.serialized_func else None,
        args=request.args.encode() if request.args else None,
        kwargs=request.kwargs.encode() if request.kwargs else None,
        priority=request.priority,
        gpu_memory_mb=request.gpu_memory_mb,
        cpu_cores=request.cpu_cores,
        timeout_seconds=request.timeout_seconds,
        gpu_type=request.gpu_type,
        allow_fallback_cpu=request.allow_fallback_cpu,
        tags=request.tags,
        metadata_json=request.metadata,
        callback_url=request.callback_url,
        next_run_at=next_run_at,
    )
    
    db.add(schedule)
    await db.flush()
    
    background_tasks.add_task(_sync_schedule_to_beat, schedule.id)
    
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        description=schedule.description,
        schedule_type=schedule.schedule_type.value,
        cron_expression=schedule.cron_expression,
        interval_seconds=schedule.interval_seconds,
        start_datetime=schedule.start_datetime,
        end_datetime=schedule.end_datetime,
        is_enabled=schedule.is_enabled,
        status=schedule.status.value,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        run_count=schedule.run_count,
        consecutive_failures=schedule.consecutive_failures,
        last_error=schedule.last_error,
        priority=schedule.priority,
        gpu_memory_mb=schedule.gpu_memory_mb,
        timeout_seconds=schedule.timeout_seconds,
        created_at=schedule.created_at,
        user_id=schedule.user_id,
    )


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
    is_enabled: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> ScheduleListResponse:
    """List scheduled tasks."""
    repo = ScheduleRepository(db)
    
    schedules = await repo.list_by_user(
        user_id=current_user.id if current_user else None,
        is_enabled=is_enabled,
        limit=limit,
        offset=offset,
    )
    
    return ScheduleListResponse(
        schedules=[
            ScheduleResponse(
                id=s.id,
                name=s.name,
                description=s.description,
                schedule_type=s.schedule_type.value,
                cron_expression=s.cron_expression,
                interval_seconds=s.interval_seconds,
                start_datetime=s.start_datetime,
                end_datetime=s.end_datetime,
                is_enabled=s.is_enabled,
                status=s.status.value,
                last_run_at=s.last_run_at,
                next_run_at=s.next_run_at,
                run_count=s.run_count,
                consecutive_failures=s.consecutive_failures,
                last_error=s.last_error,
                priority=s.priority,
                gpu_memory_mb=s.gpu_memory_mb,
                timeout_seconds=s.timeout_seconds,
                created_at=s.created_at,
                user_id=s.user_id,
            )
            for s in schedules
        ],
        total=len(schedules),
        limit=limit,
        offset=offset,
    )


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> ScheduleResponse:
    """Get a scheduled task by ID."""
    repo = ScheduleRepository(db)
    schedule = await repo.get_by_id(schedule_id)
    
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    if current_user and schedule.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        description=schedule.description,
        schedule_type=schedule.schedule_type.value,
        cron_expression=schedule.cron_expression,
        interval_seconds=schedule.interval_seconds,
        start_datetime=schedule.start_datetime,
        end_datetime=schedule.end_datetime,
        is_enabled=schedule.is_enabled,
        status=schedule.status.value,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        run_count=schedule.run_count,
        consecutive_failures=schedule.consecutive_failures,
        last_error=schedule.last_error,
        priority=schedule.priority,
        gpu_memory_mb=schedule.gpu_memory_mb,
        timeout_seconds=schedule.timeout_seconds,
        created_at=schedule.created_at,
        user_id=schedule.user_id,
    )


@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: str,
    request: ScheduleUpdateRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> ScheduleResponse:
    """Update a scheduled task."""
    from deepiri_zepgpu.database.models import ScheduledTask
    
    repo = ScheduleRepository(db)
    schedule = await repo.get_by_id(schedule_id)
    
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    if current_user and schedule.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    update_data = request.model_dump(exclude_unset=True)
    
    if "cron_expression" in update_data and update_data["cron_expression"]:
        try:
            croniter(update_data["cron_expression"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cron expression")
    
    for key, value in update_data.items():
        if hasattr(schedule, key):
            setattr(schedule, key, value)
    
    next_run_at = _calculate_next_run(
        schedule.schedule_type.value,
        schedule.cron_expression,
        schedule.interval_seconds,
        schedule.start_datetime,
    )
    schedule.next_run_at = next_run_at
    
    await db.flush()
    
    background_tasks.add_task(_sync_schedule_to_beat, schedule.id)
    
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        description=schedule.description,
        schedule_type=schedule.schedule_type.value,
        cron_expression=schedule.cron_expression,
        interval_seconds=schedule.interval_seconds,
        start_datetime=schedule.start_datetime,
        end_datetime=schedule.end_datetime,
        is_enabled=schedule.is_enabled,
        status=schedule.status.value,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        run_count=schedule.run_count,
        consecutive_failures=schedule.consecutive_failures,
        last_error=schedule.last_error,
        priority=schedule.priority,
        gpu_memory_mb=schedule.gpu_memory_mb,
        timeout_seconds=schedule.timeout_seconds,
        created_at=schedule.created_at,
        user_id=schedule.user_id,
    )


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> None:
    """Delete a scheduled task."""
    repo = ScheduleRepository(db)
    schedule = await repo.get_by_id(schedule_id)
    
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    if current_user and schedule.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    beat_scheduler_sync.remove_schedule(schedule_id)
    await repo.delete(schedule_id)


@router.post("/{schedule_id}/enable", response_model=ScheduleResponse)
async def enable_schedule(
    schedule_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> ScheduleResponse:
    """Enable a scheduled task."""
    repo = ScheduleRepository(db)
    schedule = await repo.get_by_id(schedule_id)
    
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    if current_user and schedule.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    await repo.enable(schedule_id)
    background_tasks.add_task(_sync_schedule_to_beat, schedule_id)
    
    schedule = await repo.get_by_id(schedule_id)
    
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        description=schedule.description,
        schedule_type=schedule.schedule_type.value,
        cron_expression=schedule.cron_expression,
        interval_seconds=schedule.interval_seconds,
        start_datetime=schedule.start_datetime,
        end_datetime=schedule.end_datetime,
        is_enabled=schedule.is_enabled,
        status=schedule.status.value,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        run_count=schedule.run_count,
        consecutive_failures=schedule.consecutive_failures,
        last_error=schedule.last_error,
        priority=schedule.priority,
        gpu_memory_mb=schedule.gpu_memory_mb,
        timeout_seconds=schedule.timeout_seconds,
        created_at=schedule.created_at,
        user_id=schedule.user_id,
    )


@router.post("/{schedule_id}/disable", response_model=ScheduleResponse)
async def disable_schedule(
    schedule_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> ScheduleResponse:
    """Disable a scheduled task."""
    repo = ScheduleRepository(db)
    schedule = await repo.get_by_id(schedule_id)
    
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    if current_user and schedule.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    await repo.disable(schedule_id)
    beat_scheduler_sync.remove_schedule(schedule_id)
    
    schedule = await repo.get_by_id(schedule_id)
    
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        description=schedule.description,
        schedule_type=schedule.schedule_type.value,
        cron_expression=schedule.cron_expression,
        interval_seconds=schedule.interval_seconds,
        start_datetime=schedule.start_datetime,
        end_datetime=schedule.end_datetime,
        is_enabled=schedule.is_enabled,
        status=schedule.status.value,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        run_count=schedule.run_count,
        consecutive_failures=schedule.consecutive_failures,
        last_error=schedule.last_error,
        priority=schedule.priority,
        gpu_memory_mb=schedule.gpu_memory_mb,
        timeout_seconds=schedule.timeout_seconds,
        created_at=schedule.created_at,
        user_id=schedule.user_id,
    )


@router.post("/{schedule_id}/trigger", response_model=ScheduleResponse)
async def trigger_schedule(
    schedule_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> ScheduleResponse:
    """Trigger a scheduled task to run immediately."""
    repo = ScheduleRepository(db)
    schedule = await repo.get_by_id(schedule_id)
    
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    if current_user and schedule.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    execute_scheduled_task.delay(schedule_id)
    
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        description=schedule.description,
        schedule_type=schedule.schedule_type.value,
        cron_expression=schedule.cron_expression,
        interval_seconds=schedule.interval_seconds,
        start_datetime=schedule.start_datetime,
        end_datetime=schedule.end_datetime,
        is_enabled=schedule.is_enabled,
        status=schedule.status.value,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        run_count=schedule.run_count,
        consecutive_failures=schedule.consecutive_failures,
        last_error=schedule.last_error,
        priority=schedule.priority,
        gpu_memory_mb=schedule.gpu_memory_mb,
        timeout_seconds=schedule.timeout_seconds,
        created_at=schedule.created_at,
        user_id=schedule.user_id,
    )


@router.get("/{schedule_id}/runs", response_model=ScheduleRunListResponse)
async def list_schedule_runs(
    schedule_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ScheduleRunListResponse:
    """List runs for a scheduled task."""
    from deepiri_zepgpu.database.repositories import ScheduleRepository
    
    schedule_repo = ScheduleRepository(db)
    schedule = await schedule_repo.get_by_id(schedule_id)
    
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    if current_user and schedule.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    run_repo = ScheduleRunRepository(db)
    runs = await run_repo.list_by_schedule(schedule_id, limit, offset)
    
    return ScheduleRunListResponse(
        runs=[
            ScheduleRunResponse(
                id=r.id,
                schedule_id=r.schedule_id,
                task_id=r.task_id,
                status=r.status.value,
                scheduled_at=r.scheduled_at,
                started_at=r.started_at,
                completed_at=r.completed_at,
                duration_ms=r.duration_ms,
                error=r.error,
                trigger_type=r.trigger_type,
                created_at=r.created_at,
            )
            for r in runs
        ],
        total=len(runs),
        limit=limit,
        offset=offset,
    )


@router.post("/delayed", response_model=DelayedTaskResponse, status_code=status.HTTP_201_CREATED)
async def create_delayed_task(
    request: DelayedTaskRequest,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> DelayedTaskResponse:
    """Create a task that executes at a specified time."""
    from deepiri_zepgpu.database.models import Task, TaskStatus as DBTaskStatus
    
    if request.execute_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="execute_at must be in the future")
    
    task = Task(
        id=str(uuid.uuid4()),
        user_id=current_user.id if current_user else None,
        name=request.name,
        func_name=request.func_name,
        serialized_func=request.serialized_func.encode() if request.serialized_func else None,
        args=request.args.encode() if request.args else None,
        kwargs=request.kwargs.encode() if request.kwargs else None,
        priority=DBTaskPriority(request.priority),
        gpu_memory_mb=request.gpu_memory_mb,
        cpu_cores=request.cpu_cores,
        timeout_seconds=request.timeout_seconds,
        gpu_type=request.gpu_type,
        allow_fallback_cpu=request.allow_fallback_cpu,
        tags=request.tags,
        metadata_json={**request.metadata, "delayed": True, "execute_at": request.execute_at.isoformat()},
        callback_url=request.callback_url,
        status=DBTaskStatus.SCHEDULED,
    )
    
    db.add(task)
    await db.flush()
    
    delay_seconds = (request.execute_at - datetime.utcnow()).total_seconds()
    execute_delayed_task.apply_async(args=[task.id], countdown=delay_seconds)
    
    return DelayedTaskResponse(
        task_id=task.id,
        execute_at=request.execute_at,
        status="scheduled",
    )
