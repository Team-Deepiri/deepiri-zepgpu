"""Task API routes."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from pydantic import BaseModel, Field

from deepiri_zepgpu.api.server.dependencies import get_current_user, get_db_session
from deepiri_zepgpu.database.models.task import TaskStatus as DBTaskStatus, TaskPriority as DBTaskPriority
from deepiri_zepgpu.database.repositories import TaskRepository


router = APIRouter()


class TaskCreateRequest(BaseModel):
    """Task creation request."""
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
    tags: list[str] = []
    metadata: dict[str, Any] = {}
    callback_url: str | None = None


class TaskResponse(BaseModel):
    """Task response."""
    id: str
    name: str | None
    status: str
    priority: int
    gpu_memory_mb: int
    timeout_seconds: int
    gpu_type: str | None
    gpu_device_id: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    execution_time_ms: int | None
    user_id: str | None

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """Task list response."""
    tasks: list[TaskResponse]
    total: int
    limit: int
    offset: int


class TaskResultResponse(BaseModel):
    """Task result response."""
    task_id: str
    status: str
    result: Any | None
    presigned_url: str | None = None


async def enqueue_task_to_celery(task_id: str) -> None:
    """Enqueue task to Celery for execution."""
    from deepiri_zepgpu.queue.tasks import execute_task
    
    execute_task.delay(task_id)


async def send_callback(callback_url: str, task_id: str, status: str, result: Any = None) -> None:
    """Send callback webhook notification."""
    import httpx
    
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                callback_url,
                json={
                    "task_id": task_id,
                    "status": status,
                    "result": result,
                },
                timeout=10.0,
            )
    except Exception:
        pass


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    request: TaskCreateRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> TaskResponse:
    """Create a new task and enqueue it for execution."""
    from deepiri_zepgpu.database.models import Task
    
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
        metadata_json=request.metadata,
        callback_url=request.callback_url,
        status=DBTaskStatus.PENDING,
    )
    
    db.add(task)
    await db.flush()
    
    background_tasks.add_task(enqueue_task_to_celery, task.id)
    
    return TaskResponse(
        id=task.id,
        name=task.name,
        status=task.status.value,
        priority=task.priority.value,
        gpu_memory_mb=task.gpu_memory_mb,
        timeout_seconds=task.timeout_seconds,
        gpu_type=task.gpu_type,
        gpu_device_id=task.gpu_device_id,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error,
        execution_time_ms=task.execution_time_ms,
        user_id=task.user_id,
    )


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> TaskListResponse:
    """List tasks."""
    repo = TaskRepository(db)
    
    tasks = await repo.list_by_user(
        user_id=current_user.id,
        status=DBTaskStatus(status_filter) if status_filter else None,
        limit=limit,
        offset=offset,
    )
    
    return TaskListResponse(
        tasks=[
            TaskResponse(
                id=t.id,
                name=t.name,
                status=t.status.value,
                priority=t.priority.value,
                gpu_memory_mb=t.gpu_memory_mb,
                timeout_seconds=t.timeout_seconds,
                gpu_type=t.gpu_type,
                gpu_device_id=t.gpu_device_id,
                created_at=t.created_at,
                started_at=t.started_at,
                completed_at=t.completed_at,
                error=t.error,
                execution_time_ms=t.execution_time_ms,
                user_id=t.user_id,
            )
            for t in tasks
        ],
        total=len(tasks),
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> TaskResponse:
    """Get task by ID."""
    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if current_user and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return TaskResponse(
        id=task.id,
        name=task.name,
        status=task.status.value,
        priority=task.priority.value,
        gpu_memory_mb=task.gpu_memory_mb,
        timeout_seconds=task.timeout_seconds,
        gpu_type=task.gpu_type,
        gpu_device_id=task.gpu_device_id,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error,
        execution_time_ms=task.execution_time_ms,
        user_id=task.user_id,
    )


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_task(
    task_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> None:
    """Cancel a task."""
    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if current_user and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if task.status in [DBTaskStatus.COMPLETED, DBTaskStatus.FAILED, DBTaskStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail="Task already terminated")
    
    await repo.mark_cancelled(task_id)


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> TaskResponse:
    """Retry a failed task."""
    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if current_user and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if task.status not in [DBTaskStatus.FAILED, DBTaskStatus.CANCELLED, DBTaskStatus.TIMEOUT]:
        raise HTTPException(status_code=400, detail="Can only retry failed/cancelled/timed out tasks")
    
    await repo.update_status(task_id, DBTaskStatus.PENDING)
    background_tasks.add_task(enqueue_task_to_celery, task_id)
    
    task = await repo.get_by_id(task_id)
    
    return TaskResponse(
        id=task.id,
        name=task.name,
        status=task.status.value,
        priority=task.priority.value,
        gpu_memory_mb=task.gpu_memory_mb,
        timeout_seconds=task.timeout_seconds,
        gpu_type=task.gpu_type,
        gpu_device_id=task.gpu_device_id,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error,
        execution_time_ms=task.execution_time_ms,
        user_id=task.user_id,
    )


@router.get("/{task_id}/result", response_model=TaskResultResponse)
async def get_task_result(
    task_id: str,
    db=Depends(get_db_session),
    current_user=Depends(get_current_user),
) -> TaskResultResponse:
    """Get task result."""
    from deepiri_zepgpu.storage.result_store import ResultStore
    
    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if current_user and task.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    result_data = None
    presigned_url = None
    
    if task.result_ref:
        result_store = ResultStore()
        result_bytes = await result_store.retrieve_result(task_id, "redis", task.result_ref)
        if result_bytes:
            import pickle
            result_data = pickle.loads(result_bytes)
        presigned_url = await result_store.get_presigned_url(task_id)
    
    return TaskResultResponse(
        task_id=task_id,
        status=task.status.value,
        result=result_data,
        presigned_url=presigned_url,
    )
