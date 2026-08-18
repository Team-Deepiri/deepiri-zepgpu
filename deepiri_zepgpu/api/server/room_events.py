"""Room-scoped WebSocket event helpers (Phase 7)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from deepiri_zepgpu.api.server.websocket_manager import manager

logger = logging.getLogger(__name__)


async def emit_room_event(
    room_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Broadcast a room event. Never raises into request handlers."""
    message = {
        "type": event_type,
        "room_id": str(room_id),
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }
    try:
        await manager.broadcast_to_room(str(room_id), message)
    except Exception:
        logger.exception("Failed to emit room event %s for room %s", event_type, room_id)


def assignment_payload(
    *,
    task_id: str,
    assignment_id: str,
    peer_id: str | None,
    gpu_share_id: str | None,
    status: str,
    assignment_status: str,
    error: str | None = None,
    terminal_reason: str | None = None,
    claim_generation: int | None = None,
    lease_expires_at: str | None = None,
    cancel_requested: bool | None = None,
) -> dict[str, Any]:
    """Build a consistent room task lifecycle payload."""
    payload: dict[str, Any] = {
        "task_id": str(task_id),
        "assignment_id": str(assignment_id),
        "peer_id": str(peer_id) if peer_id else None,
        "gpu_share_id": str(gpu_share_id) if gpu_share_id else None,
        "status": status,
        "assignment_status": assignment_status,
        "error": error,
    }
    if terminal_reason is not None:
        payload["terminal_reason"] = terminal_reason
    if claim_generation is not None:
        payload["claim_generation"] = claim_generation
    if lease_expires_at is not None:
        payload["lease_expires_at"] = lease_expires_at
    if cancel_requested is not None:
        payload["cancel_requested"] = cancel_requested
    return payload
