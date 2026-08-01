"""Node task lifecycle endpoints for remote room execution."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_db_session, get_required_user
from deepiri_zepgpu.api.server.node_task_lifecycle import (
    notify_assignment_terminal,
    release_assignment_lock,
)
from deepiri_zepgpu.api.server.provider_auth import (
    get_verified_provider,
    verify_provider_credentials,
)
from deepiri_zepgpu.api.server.room_events import assignment_payload, emit_room_event
from deepiri_zepgpu.database.models import User
from deepiri_zepgpu.database.models.node_task_assignment import NodeTaskAssignment
from deepiri_zepgpu.database.models.task import Task
from deepiri_zepgpu.database.models.vpn_models import Peer
from deepiri_zepgpu.database.repositories.node_task_repository import (
    NodeTaskRepository,
    NodeTaskTransitionError,
)
from deepiri_zepgpu.vpn.repositories import VpnNetworkRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/node-tasks", tags=["Node Tasks"])


# Evolve get_verified_peer → shared provider verification (Phase 12).
get_verified_peer = get_verified_provider

# Backwards-compatible alias used by Phase 10 tests.
_release_assignment_lock = release_assignment_lock


async def _require_room_member_for_result(
    assignment: NodeTaskAssignment,
    authorization: str | None,
    db: AsyncSession,
) -> None:
    """Authorize a human dashboard caller to view a task result."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user: User = await get_required_user(credentials=credentials, db=db)

    network_repo = VpnNetworkRepository(db)
    room_id = str(assignment.vpn_network_id)
    user_networks = await network_repo.list_user_networks(str(user.id))
    if not any(str(network.id) == room_id for network in user_networks):
        raise HTTPException(status_code=403, detail="Not a member of this room")


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
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    claim_generation: int = 0
    terminal_reason: str | None = None
    cancel_requested: bool = False
    cancel_requested_at: datetime | None = None
    error: str | None = None


class CompleteNodeTaskRequest(BaseModel):
    result_metadata: dict[str, Any] = Field(default_factory=dict)


class FailNodeTaskRequest(BaseModel):
    error: str


class NodeTaskLogRequest(BaseModel):
    event_type: str = Field(default="node_task_log", min_length=1, max_length=100)
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class NodeTaskLogBatchRequest(BaseModel):
    logs: list[NodeTaskLogRequest] = Field(default_factory=list, min_length=1, max_length=100)


class NodeTaskLogResponse(BaseModel):
    assignment_id: str
    event_type: str
    payload: dict[str, Any]


class NodeTaskLogBatchResponse(BaseModel):
    assignment_id: str
    accepted: int


class NodeTaskResultResponse(BaseModel):
    assignment_id: str
    task_id: str
    status: str
    assignment_status: str
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    result_ref: str | None = None
    result_size_bytes: int | None = None
    error: str | None = None
    terminal_reason: str | None = None


class ReconcileRequest(BaseModel):
    assignment_ids: list[str] = Field(default_factory=list, max_length=100)


class ReconcileItem(BaseModel):
    assignment_id: str
    action: str
    status: str | None = None
    terminal_reason: str | None = None
    reason: str | None = None
    claim_generation: int | None = None
    lease_expires_at: str | None = None
    cancel_requested: bool | None = None
    recovered: bool | None = None


class ReconcileResponse(BaseModel):
    room_id: str
    peer_id: str
    outcomes: list[ReconcileItem]


class PendingTasksResponse(BaseModel):
    """Pending assignments plus cancel flags for poll fallback."""

    assignments: list[NodeTaskResponse]
    cancel_requested: list[NodeTaskResponse] = Field(default_factory=list)


def _assignment_to_response(assignment: NodeTaskAssignment) -> NodeTaskResponse:
    return NodeTaskResponse(
        assignment_id=str(assignment.id),
        room_id=str(assignment.vpn_network_id),
        task_id=str(assignment.task_id),
        peer_id=str(assignment.peer_id) if assignment.peer_id else "",
        gpu_share_id=str(assignment.gpu_share_id) if assignment.gpu_share_id else None,
        status=assignment.status.value,
        accepted_at=assignment.accepted_at,
        started_at=assignment.started_at,
        completed_at=assignment.completed_at,
        failed_at=assignment.failed_at,
        claimed_at=getattr(assignment, "claimed_at", None),
        lease_expires_at=getattr(assignment, "lease_expires_at", None),
        claim_generation=int(getattr(assignment, "claim_generation", 0) or 0),
        terminal_reason=getattr(assignment, "terminal_reason", None),
        cancel_requested=bool(getattr(assignment, "cancel_requested_at", None)),
        cancel_requested_at=getattr(assignment, "cancel_requested_at", None),
        error=assignment.error,
    )


def _task_status(task: Task) -> str:
    return task.status.value if hasattr(task.status, "value") else str(task.status)


async def _task_for_assignment(
    db: AsyncSession,
    assignment: NodeTaskAssignment,
) -> Task | None:
    return await db.get(Task, assignment.task_id)


async def _emit_room_task_event(
    *,
    event_type: str,
    task: Task | None,
    assignment: NodeTaskAssignment,
) -> None:
    # Keep emit_room_event/assignment_payload on this module for test patching.
    status = _task_status(task) if task is not None else "assigned"
    await emit_room_event(
        str(assignment.vpn_network_id),
        event_type,
        assignment_payload(
            task_id=str(assignment.task_id),
            assignment_id=str(assignment.id),
            peer_id=str(assignment.peer_id) if assignment.peer_id else None,
            gpu_share_id=str(assignment.gpu_share_id) if assignment.gpu_share_id else None,
            status=status,
            assignment_status=(
                assignment.status.value
                if hasattr(assignment.status, "value")
                else str(assignment.status)
            ),
            error=assignment.error or (task.error if task is not None else None),
            terminal_reason=getattr(assignment, "terminal_reason", None),
            claim_generation=getattr(assignment, "claim_generation", None),
            lease_expires_at=(
                assignment.lease_expires_at.isoformat()
                if getattr(assignment, "lease_expires_at", None) is not None
                else None
            ),
            cancel_requested=bool(getattr(assignment, "cancel_requested_at", None)),
        ),
    )


async def _notify_if_task_exists(
    *,
    task: Task | None,
    assignment: NodeTaskAssignment,
) -> None:
    await notify_assignment_terminal(task=task, assignment=assignment)


@router.get(
    "/rooms/{room_id}/nodes/{peer_id}/tasks/pending",
    response_model=list[NodeTaskResponse],
)
async def list_pending_node_tasks(
    room_id: str,
    peer_id: str,
    limit: int = Query(default=1, ge=1, le=10),
    include_cancels: bool = Query(default=True),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> list[NodeTaskResponse]:
    peer = await verify_provider_credentials(
        peer_id=peer_id,
        authorization=authorization,
        db=db,
        room_id=room_id,
    )
    repo = NodeTaskRepository(db)
    assignments = await repo.list_pending_for_peer(
        vpn_network_id=room_id,
        peer_id=str(peer.id),
        limit=limit,
    )
    responses = [_assignment_to_response(assignment) for assignment in assignments]
    if include_cancels:
        cancels = await repo.list_cancel_requested_for_peer(
            vpn_network_id=room_id,
            peer_id=str(peer.id),
        )
        # Surface cancel flags via status annotations on responses already returned;
        # agents also poll cancel_requested via the dedicated field on responses.
        for cancel_assignment in cancels:
            responses.append(_assignment_to_response(cancel_assignment))
    return responses


@router.get(
    "/rooms/{room_id}/nodes/{peer_id}/tasks/poll",
    response_model=PendingTasksResponse,
)
async def poll_node_tasks(
    room_id: str,
    peer_id: str,
    limit: int = Query(default=1, ge=1, le=10),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> PendingTasksResponse:
    """HTTPS poll fallback: pending assignments + cancel propagation flags."""
    peer = await verify_provider_credentials(
        peer_id=peer_id,
        authorization=authorization,
        db=db,
        room_id=room_id,
    )
    repo = NodeTaskRepository(db)
    assignments = await repo.list_pending_for_peer(
        vpn_network_id=room_id,
        peer_id=str(peer.id),
        limit=limit,
    )
    cancels = await repo.list_cancel_requested_for_peer(
        vpn_network_id=room_id,
        peer_id=str(peer.id),
    )
    return PendingTasksResponse(
        assignments=[_assignment_to_response(a) for a in assignments],
        cancel_requested=[_assignment_to_response(a) for a in cancels],
    )


@router.post(
    "/rooms/{room_id}/nodes/{peer_id}/reconcile",
    response_model=ReconcileResponse,
)
async def reconcile_node_tasks(
    room_id: str,
    peer_id: str,
    request: ReconcileRequest,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> ReconcileResponse:
    """Provider restart recovery: resume valid leases, fail expired, abandon stale."""
    peer = await verify_provider_credentials(
        peer_id=peer_id,
        authorization=authorization,
        db=db,
        room_id=room_id,
    )
    repo = NodeTaskRepository(db)
    outcomes = await repo.reconcile_for_peer(
        vpn_network_id=room_id,
        peer_id=str(peer.id),
        local_assignment_ids=request.assignment_ids,
    )

    # Notify + release GPU for any newly terminal outcomes from reconcile.
    for item in outcomes:
        if item.get("action") not in {"fail_expired", "cancel"}:
            continue
        assignment = await repo.get_by_id(str(item["assignment_id"]))
        if assignment is None:
            continue
        task = await _task_for_assignment(db, assignment)
        await notify_assignment_terminal(task=task, assignment=assignment)

    await db.commit()
    return ReconcileResponse(
        room_id=room_id,
        peer_id=str(peer.id),
        outcomes=[
            ReconcileItem(**{k: v for k, v in item.items() if k in ReconcileItem.model_fields})
            for item in outcomes
        ],
    )


@router.get("/{assignment_id}/result", response_model=NodeTaskResultResponse)
async def get_node_task_result(
    assignment_id: str,
    peer_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> NodeTaskResultResponse:
    repo = NodeTaskRepository(db)

    if peer_id:
        peer = await get_verified_peer(peer_id, authorization, db)
        assignment = await repo.get_for_peer(assignment_id=assignment_id, peer_id=str(peer.id))
        if assignment is None:
            raise HTTPException(status_code=404, detail="Assignment not found")
    else:
        assignment = await repo.get_by_id(assignment_id)
        if assignment is None:
            raise HTTPException(status_code=404, detail="Assignment not found")
        await _require_room_member_for_result(assignment, authorization, db)

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
        terminal_reason=assignment.terminal_reason,
    )


@router.post("/{assignment_id}/claim", response_model=NodeTaskResponse)
async def claim_node_task(
    assignment_id: str,
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_peer),
) -> NodeTaskResponse:
    repo = NodeTaskRepository(db)
    try:
        assignment = await repo.mark_claimed(assignment_id=assignment_id, peer_id=str(peer.id))
    except NodeTaskTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.commit()
    await db.refresh(assignment)
    task = await _task_for_assignment(db, assignment)
    if assignment.is_terminal:
        await notify_assignment_terminal(task=task, assignment=assignment)
    else:
        await _emit_room_task_event(
            event_type="room_task_claimed",
            task=task,
            assignment=assignment,
        )
    return _assignment_to_response(assignment)


@router.post("/{assignment_id}/accept", response_model=NodeTaskResponse)
async def accept_node_task(
    assignment_id: str,
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_peer),
) -> NodeTaskResponse:
    """Backwards-compatible accept (= claim)."""
    return await claim_node_task(assignment_id=assignment_id, db=db, peer=peer)


@router.post("/{assignment_id}/start", response_model=NodeTaskResponse)
async def start_node_task(
    assignment_id: str,
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_peer),
) -> NodeTaskResponse:
    repo = NodeTaskRepository(db)
    try:
        assignment = await repo.mark_running(assignment_id=assignment_id, peer_id=str(peer.id))
    except NodeTaskTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.commit()
    await db.refresh(assignment)
    task = await _task_for_assignment(db, assignment)
    if assignment.is_terminal:
        await notify_assignment_terminal(task=task, assignment=assignment)
    else:
        await _emit_room_task_event(
            event_type="room_task_started",
            task=task,
            assignment=assignment,
        )
    return _assignment_to_response(assignment)


@router.post("/{assignment_id}/complete", response_model=NodeTaskResponse)
async def complete_node_task(
    assignment_id: str,
    request: CompleteNodeTaskRequest,
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_peer),
) -> NodeTaskResponse:
    repo = NodeTaskRepository(db)
    try:
        assignment = await repo.mark_completed(
            assignment_id=assignment_id,
            peer_id=str(peer.id),
            result_metadata=request.result_metadata,
        )
    except NodeTaskTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    task = await _task_for_assignment(db, assignment)

    await db.commit()
    await db.refresh(assignment)
    await notify_assignment_terminal(task=task, assignment=assignment)
    return _assignment_to_response(assignment)


@router.post("/{assignment_id}/fail", response_model=NodeTaskResponse)
async def fail_node_task(
    assignment_id: str,
    request: FailNodeTaskRequest,
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_peer),
) -> NodeTaskResponse:
    repo = NodeTaskRepository(db)
    try:
        assignment = await repo.mark_failed(
            assignment_id=assignment_id,
            peer_id=str(peer.id),
            error=request.error,
        )
    except NodeTaskTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    task = await _task_for_assignment(db, assignment)

    await db.commit()
    await db.refresh(assignment)
    await notify_assignment_terminal(task=task, assignment=assignment)
    return _assignment_to_response(assignment)


@router.post("/{assignment_id}/logs", response_model=NodeTaskLogResponse)
async def log_node_task_event(
    assignment_id: str,
    request: NodeTaskLogRequest,
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_peer),
) -> NodeTaskLogResponse:
    repo = NodeTaskRepository(db)
    assignment = await repo.get_for_peer(
        assignment_id=assignment_id,
        peer_id=str(peer.id),
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    payload = {
        "peer_id": str(peer.id),
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


@router.post("/{assignment_id}/logs/batch", response_model=NodeTaskLogBatchResponse)
async def log_node_task_events_batch(
    assignment_id: str,
    request: NodeTaskLogBatchRequest,
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_peer),
) -> NodeTaskLogBatchResponse:
    """Batched/chunked log submission after short disconnects."""
    repo = NodeTaskRepository(db)
    assignment = await repo.get_for_peer(
        assignment_id=assignment_id,
        peer_id=str(peer.id),
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")

    accepted = 0
    for entry in request.logs:
        payload = {
            "peer_id": str(peer.id),
            "task_id": str(assignment.task_id),
            "message": entry.message,
            **entry.payload,
        }
        await repo.record_event(
            assignment_id=assignment_id,
            event_type=entry.event_type,
            payload=payload,
        )
        accepted += 1
    await db.commit()
    return NodeTaskLogBatchResponse(assignment_id=assignment_id, accepted=accepted)
