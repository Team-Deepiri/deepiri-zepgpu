"""Shared helpers for node-task terminal cleanup and provider notifications."""

from __future__ import annotations

import logging
from typing import Any

from deepiri_zepgpu.api.server.remote_task_events import notify_remote_task_terminal_state
from deepiri_zepgpu.api.server.room_events import assignment_payload, emit_room_event
from deepiri_zepgpu.api.server.websocket_manager import manager
from deepiri_zepgpu.database.models.node_task_assignment import NodeTaskAssignment
from deepiri_zepgpu.database.models.task import Task
from deepiri_zepgpu.vpn.remote_gpu_lock import RemoteGpuLock

logger = logging.getLogger(__name__)


def release_assignment_lock(assignment: NodeTaskAssignment) -> None:
    """Best-effort Redis GPU lock release after a terminal DB commit.

    Only releases when the lock holder matches this assignment's task_id.
    """
    if not assignment.gpu_share_id:
        return
    try:
        RemoteGpuLock().release(str(assignment.gpu_share_id), str(assignment.task_id))
    except Exception:
        logger.exception("Failed to release GPU lock for assignment %s", assignment.id)


def _task_status(task: Task | None) -> str:
    if task is None:
        return "assigned"
    return task.status.value if hasattr(task.status, "value") else str(task.status)


def _isoformat_or_none(value: Any) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        result = iso()
        return str(result) if result is not None else None
    return str(value)


def room_event_type_for_assignment(assignment: NodeTaskAssignment) -> str:
    """Map assignment terminal/active status to a room dashboard event type."""
    status = (
        assignment.status.value if hasattr(assignment.status, "value") else str(assignment.status)
    )
    reason = assignment.terminal_reason or ""
    if status == "completed":
        return "room_task_completed"
    if status == "cancelled":
        return "room_task_cancelled"
    if status == "failed":
        if reason == "lease_expired":
            return "room_task_lease_expired"
        if reason in {"accepted_timeout", "running_timeout"}:
            return "room_task_timed_out"
        return "room_task_failed"
    if status == "running":
        return "room_task_started"
    if status == "accepted":
        return "room_task_claimed"
    return "room_task_assigned"


async def emit_assignment_room_event(
    *,
    task: Task | None,
    assignment: NodeTaskAssignment,
    event_type: str | None = None,
) -> None:
    await emit_room_event(
        str(assignment.vpn_network_id),
        event_type or room_event_type_for_assignment(assignment),
        assignment_payload(
            task_id=str(assignment.task_id),
            assignment_id=str(assignment.id),
            peer_id=str(assignment.peer_id) if assignment.peer_id else None,
            gpu_share_id=str(assignment.gpu_share_id) if assignment.gpu_share_id else None,
            status=_task_status(task),
            assignment_status=(
                assignment.status.value
                if hasattr(assignment.status, "value")
                else str(assignment.status)
            ),
            error=assignment.error or (task.error if task is not None else None),
            terminal_reason=getattr(assignment, "terminal_reason", None),
            claim_generation=getattr(assignment, "claim_generation", None),
            lease_expires_at=_isoformat_or_none(getattr(assignment, "lease_expires_at", None)),
            cancel_requested=(
                bool(getattr(assignment, "cancel_requested_at", None))
                if hasattr(assignment, "cancel_requested_at")
                else bool(getattr(assignment, "cancel_requested", False))
            ),
        ),
    )


async def notify_assignment_terminal(
    *,
    task: Task | None,
    assignment: NodeTaskAssignment,
) -> None:
    """GPU lock release + callback + dashboard WS + room event for terminals."""
    release_assignment_lock(assignment)
    if task is not None:
        await notify_remote_task_terminal_state(task=task, assignment=assignment)
    await emit_assignment_room_event(task=task, assignment=assignment)


async def push_provider_assignment(
    *,
    peer_id: str,
    assignment: NodeTaskAssignment,
    event_type: str = "assignment",
    extra: dict[str, Any] | None = None,
) -> bool:
    """Push an assignment/cancel event to a connected provider agent over WSS."""
    payload: dict[str, Any] = {
        "type": event_type,
        "assignment_id": str(assignment.id),
        "room_id": str(assignment.vpn_network_id),
        "task_id": str(assignment.task_id),
        "peer_id": str(peer_id),
        "gpu_share_id": str(assignment.gpu_share_id) if assignment.gpu_share_id else None,
        "status": assignment.status.value,
        "claim_generation": assignment.claim_generation,
        "lease_expires_at": (
            assignment.lease_expires_at.isoformat() if assignment.lease_expires_at else None
        ),
        "cancel_requested": assignment.cancel_requested,
        "terminal_reason": assignment.terminal_reason,
    }
    if extra:
        payload.update(extra)
    try:
        return await manager.send_provider_message(str(peer_id), payload)
    except Exception:
        logger.exception("Failed to push provider event to peer %s", peer_id)
        return False
