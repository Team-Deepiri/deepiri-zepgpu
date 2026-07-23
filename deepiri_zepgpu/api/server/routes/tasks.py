"""Task API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_current_user, get_db_session
from deepiri_zepgpu.api.server.room_events import assignment_payload, emit_room_event
from deepiri_zepgpu.database.models import User
from deepiri_zepgpu.database.models.task import TaskPriority as DBTaskPriority
from deepiri_zepgpu.database.models.task import TaskStatus as DBTaskStatus
from deepiri_zepgpu.database.repositories import TaskRepository
from deepiri_zepgpu.database.repositories.node_task_repository import NodeTaskRepository
from deepiri_zepgpu.rooms.dispatch import (
    ROOM_DISPATCH_MODES,
    NoRoomGpuAvailable,
    RoomAccessError,
    RoomDispatchError,
    RoomGpuLockError,
    release_room_assignment,
    select_and_assign_room_gpu,
)

router = APIRouter()

DispatchMode = Literal["local", "room_auto", "room_specific_node"]


def _validate_task_callable(func_name: str | None, serialized_func: str | None) -> None:
    """Validate that a task has an executable function reference."""
    if serialized_func:
        return

    if not func_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task requires either serialized_func or func_name.",
        )

    parts = func_name.split(".")
    if len(parts) < 2 or any(not part.isidentifier() for part in parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="func_name must be a dotted Python path like 'package.module.function'.",
        )


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
    room_id: UUID | None = None
    dispatch_mode: DispatchMode = "local"
    target_peer_id: UUID | None = None
    target_gpu_share_id: UUID | None = None

    @field_validator("dispatch_mode")
    @classmethod
    def validate_dispatch_mode(cls, value: str) -> str:
        allowed = {"local", "room_auto", "room_specific_node"}
        if value not in allowed:
            raise ValueError(f"dispatch_mode must be one of {sorted(allowed)}")
        return value


class TaskAssignmentResponse(BaseModel):
    """Summary of a room GPU assignment."""

    assignment_id: str
    room_id: str
    peer_id: str
    gpu_share_id: str
    status: str


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
    room_id: str | None = None
    dispatch_mode: str = "local"
    target_peer_id: str | None = None
    target_gpu_share_id: str | None = None
    assignment: TaskAssignmentResponse | None = None

    class Config:
        from_attributes = True


async def _load_assignment_summary(
    db: AsyncSession,
    task_id: str,
) -> TaskAssignmentResponse | None:
    assignment_repo = NodeTaskRepository(db)
    assignment = await assignment_repo.get_by_task_id(task_id)
    if not assignment:
        return None
    return TaskAssignmentResponse(
        assignment_id=str(assignment.id),
        room_id=str(assignment.vpn_network_id),
        peer_id=str(assignment.peer_id) if assignment.peer_id else "",
        gpu_share_id=str(assignment.gpu_share_id) if assignment.gpu_share_id else "",
        status=assignment.status.value,
    )


def _task_to_response(task: Any, assignment: TaskAssignmentResponse | None = None) -> TaskResponse:
    return TaskResponse(
        id=str(task.id),
        name=task.name,
        status=task.status.value,
        priority=task.priority.value if hasattr(task.priority, "value") else task.priority,
        gpu_memory_mb=task.gpu_memory_mb,
        timeout_seconds=task.timeout_seconds,
        gpu_type=task.gpu_type,
        gpu_device_id=task.gpu_device_id,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error,
        execution_time_ms=task.execution_time_ms,
        user_id=str(task.user_id) if task.user_id else None,
        room_id=str(task.vpn_network_id) if task.vpn_network_id else None,
        dispatch_mode=task.dispatch_mode or "local",
        target_peer_id=str(task.target_peer_id) if task.target_peer_id else None,
        target_gpu_share_id=str(task.target_gpu_share_id) if task.target_gpu_share_id else None,
        assignment=assignment,
    )


def _validate_room_dispatch_request(request: TaskCreateRequest) -> None:
    if request.dispatch_mode in ROOM_DISPATCH_MODES and not request.room_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="room_id is required for room dispatch modes",
        )
    if request.dispatch_mode == "room_specific_node" and not (
        request.target_peer_id or request.target_gpu_share_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="room_specific_node requires target_peer_id or target_gpu_share_id",
        )


def _map_dispatch_error(exc: RoomDispatchError) -> HTTPException:
    if isinstance(exc, RoomAccessError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, NoRoomGpuAvailable | RoomGpuLockError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


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


def enqueue_task_to_celery(task_id: str) -> None:
    """Enqueue task to Celery for execution."""
    import logging

    from deepiri_zepgpu.queue.tasks import execute_task

    logger = logging.getLogger(__name__)
    async_result = execute_task.apply_async(args=[task_id], queue="celery")
    logger.info("Enqueued task %s to Celery with celery_task_id=%s", task_id, async_result.id)


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
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
) -> TaskResponse:
    """Create a new task and enqueue it for execution."""
    from deepiri_zepgpu.database.models import Task

    _validate_task_callable(request.func_name, request.serialized_func)
    _validate_room_dispatch_request(request)

    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )

    task = Task(
        user_id=current_user.id,
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
        dispatch_mode=request.dispatch_mode,
        vpn_network_id=str(request.room_id) if request.room_id else None,
        target_peer_id=str(request.target_peer_id) if request.target_peer_id else None,
        target_gpu_share_id=(
            str(request.target_gpu_share_id) if request.target_gpu_share_id else None
        ),
        status=DBTaskStatus.PENDING,
    )

    db.add(task)
    await db.flush()

    assignment_summary: TaskAssignmentResponse | None = None

    if request.dispatch_mode in ROOM_DISPATCH_MODES:
        try:
            dispatch_result = await select_and_assign_room_gpu(
                db,
                user_id=str(current_user.id),
                room_id=str(request.room_id),
                task_id=str(task.id),
                required_memory_mb=request.gpu_memory_mb,
                dispatch_mode=request.dispatch_mode,
                gpu_type=request.gpu_type,
                target_peer_id=str(request.target_peer_id) if request.target_peer_id else None,
                target_gpu_share_id=(
                    str(request.target_gpu_share_id) if request.target_gpu_share_id else None
                ),
            )
        except RoomDispatchError as exc:
            await db.rollback()
            raise _map_dispatch_error(exc) from exc

        repo = TaskRepository(db)
        updated_task = await repo.mark_assigned(str(task.id))
        if updated_task is None:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Task not found after room assignment",
            )
        task = updated_task
        assignment_summary = TaskAssignmentResponse(
            assignment_id=str(dispatch_result.assignment.id),
            room_id=dispatch_result.vpn_network_id,
            peer_id=dispatch_result.peer_id,
            gpu_share_id=dispatch_result.gpu_share_id,
            status=dispatch_result.assignment.status.value,
        )
        await emit_room_event(
            dispatch_result.vpn_network_id,
            "room_task_assigned",
            assignment_payload(
                task_id=str(task.id),
                assignment_id=str(dispatch_result.assignment.id),
                peer_id=dispatch_result.peer_id,
                gpu_share_id=dispatch_result.gpu_share_id,
                status=task.status.value,
                assignment_status=dispatch_result.assignment.status.value,
            ),
        )
    else:
        background_tasks.add_task(enqueue_task_to_celery, task.id)

    return _task_to_response(task, assignment_summary)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> TaskListResponse:
    """List tasks."""
    repo = TaskRepository(db)

    assert current_user is not None
    tasks = await repo.list_by_user(
        user_id=current_user.id,
        status=DBTaskStatus(status_filter) if status_filter else None,
        limit=limit,
        offset=offset,
    )

    return TaskListResponse(
        tasks=[
            TaskResponse(
                id=str(t.id),
                name=t.name,
                status=t.status.value,
                priority=t.priority.value if hasattr(t.priority, "value") else t.priority,
                gpu_memory_mb=t.gpu_memory_mb,
                timeout_seconds=t.timeout_seconds,
                gpu_type=t.gpu_type,
                gpu_device_id=t.gpu_device_id,
                created_at=t.created_at,
                started_at=t.started_at,
                completed_at=t.completed_at,
                error=t.error,
                execution_time_ms=t.execution_time_ms,
                user_id=str(t.user_id) if t.user_id else None,
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
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
) -> TaskResponse:
    """Get task by ID."""
    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user and str(task.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    assignment = await _load_assignment_summary(db, task_id)
    return _task_to_response(task, assignment)


async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
) -> None:
    """Cancel a task."""
    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user and str(task.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    if task.status in [DBTaskStatus.COMPLETED, DBTaskStatus.FAILED, DBTaskStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail="Task already terminated")

    if task.dispatch_mode in ROOM_DISPATCH_MODES and task.status == DBTaskStatus.ASSIGNED:
        await release_room_assignment(db, task_id=str(task.id))

    await repo.mark_cancelled(task_id)


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
) -> TaskResponse:
    """Retry a failed task."""
    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user and str(task.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    if task.status not in [DBTaskStatus.FAILED, DBTaskStatus.CANCELLED, DBTaskStatus.TIMEOUT]:
        raise HTTPException(
            status_code=400, detail="Can only retry failed/cancelled/timed out tasks"
        )

    await repo.update_status(task_id, DBTaskStatus.PENDING)
    background_tasks.add_task(enqueue_task_to_celery, task_id)

    task = await repo.get_by_id(task_id)
    assert task is not None

    return TaskResponse(
        id=str(task.id),
        name=task.name,
        status=task.status.value,
        priority=task.priority.value if hasattr(task.priority, "value") else task.priority,
        gpu_memory_mb=task.gpu_memory_mb,
        timeout_seconds=task.timeout_seconds,
        gpu_type=task.gpu_type,
        gpu_device_id=task.gpu_device_id,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error,
        execution_time_ms=task.execution_time_ms,
        user_id=str(task.user_id) if task.user_id else None,
    )


@router.get("/{task_id}/result", response_model=TaskResultResponse)
async def get_task_result(
    task_id: str,
    db: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_user),
) -> TaskResultResponse:
    """Get task result."""
    from deepiri_zepgpu.storage.result_store import ResultStore

    repo = TaskRepository(db)
    task = await repo.get_by_id(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user and str(task.user_id) != str(current_user.id):
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
