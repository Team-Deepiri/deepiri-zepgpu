"""Node task lifecycle endpoints for remote room execution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_db_session
from deepiri_zepgpu.database.models.node_task_assignment import NodeTaskAssignment
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
    await db.commit()
    await db.refresh(assignment)
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
    await db.commit()
    await db.refresh(assignment)
    return _assignment_to_response(assignment)
