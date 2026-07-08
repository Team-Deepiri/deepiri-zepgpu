"""Node task lifecycle endpoints for remote room execution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_db_session
from deepiri_zepgpu.api.server.remote_task_events import notify_remote_task_terminal_state
from deepiri_zepgpu.database.models.node_task_assignment import NodeTaskAssignment
from deepiri_zepgpu.database.models.task import Task
from deepiri_zepgpu.database.repositories.node_task_repository import NodeTaskRepository

router = APIRouter(prefix="/node-tasks", tags=["Node Tasks"])


class NodeTaskResponse(BaseModel):
    assignment_id: str
    room_id: str
    task_id: str
    peer_id: str
    gpu_share_id: str | None = None
    status: str
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error: str | None = None


class CompleteNodeTaskRequest(BaseModel):
    result_metadata: dict[str, Any] = Field(default_factory=dict)


class FailNodeTaskRequest(BaseModel):
    error: str


class NodeTaskLogRequest(BaseModel):
    event_type: str = Field(default="node_task_log", min_length=1, max_length=100)
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class NodeTaskLogResponse(BaseModel):
    assignment_id: str
    event_type: str
    payload: dict[str, Any]


class NodeTaskResultResponse(BaseModel):
    assignment_id: str
    task_id: str
    status: str
    assignment_status: str
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    result_ref: str | None = None
    result_size_bytes: int | None = None
    error: str | None = None


def _assignment_to_response(assignment: NodeTaskAssignment) -> NodeTaskResponse:
    return NodeTaskResponse(
        assignment_id=str(assignment.id),
        room_id=str(assignment.vpn_network_id),
        task_id=str(assignment.task_id),
        peer_id=str(assignment.peer_id),
        gpu_share_id=str(assignment.gpu_share_id) if assignment.gpu_share_id else None,
        status=assignment.status.value,
        accepted_at=assignment.accepted_at,
        started_at=assignment.started_at,
        completed_at=assignment.completed_at,
        failed_at=assignment.failed_at,
        error=assignment.error,
    )


def _task_status(task: Task) -> str:
    return task.status.value if hasattr(task.status, "value") else str(task.status)


async def _task_for_assignment(
    db: AsyncSession,
    assignment: NodeTaskAssignment,
) -> Task | None:
    return await db.get(Task, assignment.task_id)


@router.get(
    "/rooms/{room_id}/nodes/{peer_id}/tasks/pending",
    response_model=list[NodeTaskResponse],
)
async def list_pending_node_tasks(
    room_id: str,
    peer_id: str,
    limit: int = Query(default=1, ge=1, le=10),
    db: AsyncSession = Depends(get_db_session),
) -> list[NodeTaskResponse]:
    repo = NodeTaskRepository(db)
    assignments = await repo.list_pending_for_peer(
        vpn_network_id=room_id,
        peer_id=peer_id,
        limit=limit,
    )
    return [_assignment_to_response(assignment) for assignment in assignments]


@router.get("/{assignment_id}/result", response_model=NodeTaskResultResponse)
async def get_node_task_result(
    assignment_id: str,
    peer_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> NodeTaskResultResponse:
    repo = NodeTaskRepository(db)
    assignment = (
        await repo.get_for_peer(assignment_id=assignment_id, peer_id=peer_id)
        if peer_id
        else await repo.get_by_id(assignment_id)
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    task = await _task_for_assignment(db, assignment)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    metadata = dict(task.metadata_json or {})
    remote_result = metadata.get("remote_result")
    result_metadata = remote_result if isinstance(remote_result, dict) else {}

    return NodeTaskResultResponse(
        assignment_id=str(assignment.id),
        task_id=str(task.id),
        status=_task_status(task),
        assignment_status=assignment.status.value,
        result_metadata=result_metadata,
        result_ref=task.result_ref,
        result_size_bytes=task.result_size_bytes,
        error=task.error or assignment.error,
    )


@router.post("/{assignment_id}/accept", response_model=NodeTaskResponse)
async def accept_node_task(
    assignment_id: str,
    peer_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
) -> NodeTaskResponse:
    repo = NodeTaskRepository(db)
    assignment = await repo.mark_accepted(assignment_id=assignment_id, peer_id=peer_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.commit()
    await db.refresh(assignment)
    return _assignment_to_response(assignment)


@router.post("/{assignment_id}/start", response_model=NodeTaskResponse)
async def start_node_task(
    assignment_id: str,
    peer_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
) -> NodeTaskResponse:
    repo = NodeTaskRepository(db)
    assignment = await repo.mark_running(assignment_id=assignment_id, peer_id=peer_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.commit()
    await db.refresh(assignment)
    return _assignment_to_response(assignment)


@router.post("/{assignment_id}/complete", response_model=NodeTaskResponse)
async def complete_node_task(
    assignment_id: str,
    request: CompleteNodeTaskRequest,
    peer_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
) -> NodeTaskResponse:
    repo = NodeTaskRepository(db)
    assignment = await repo.mark_completed(
        assignment_id=assignment_id,
        peer_id=peer_id,
        result_metadata=request.result_metadata,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    task = await _task_for_assignment(db, assignment)

    await db.commit()
    await db.refresh(assignment)

    await notify_remote_task_terminal_state(task=task, assignment=assignment)
    return _assignment_to_response(assignment)


@router.post("/{assignment_id}/fail", response_model=NodeTaskResponse)
async def fail_node_task(
    assignment_id: str,
    request: FailNodeTaskRequest,
    peer_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
) -> NodeTaskResponse:
    repo = NodeTaskRepository(db)
    assignment = await repo.mark_failed(
        assignment_id=assignment_id,
        peer_id=peer_id,
        error=request.error,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    task = await _task_for_assignment(db, assignment)

    await db.commit()
    await db.refresh(assignment)

    await notify_remote_task_terminal_state(task=task, assignment=assignment)
    return _assignment_to_response(assignment)


@router.post("/{assignment_id}/logs", response_model=NodeTaskLogResponse)
async def log_node_task_event(
    assignment_id: str,
    request: NodeTaskLogRequest,
    peer_id: str = Query(...),
    db: AsyncSession = Depends(get_db_session),
) -> NodeTaskLogResponse:
    repo = NodeTaskRepository(db)
    assignment = await repo.get_for_peer(
        assignment_id=assignment_id,
        peer_id=peer_id,
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    payload = {
        "peer_id": peer_id,
        "task_id": str(assignment.task_id),
        "message": request.message,
        **request.payload,
    }
    await repo.record_event(
        assignment_id=assignment_id,
        event_type=request.event_type,
        payload=payload,
    )
    await db.commit()

    return NodeTaskLogResponse(
        assignment_id=assignment_id,
        event_type=request.event_type,
        payload=payload,
    )
