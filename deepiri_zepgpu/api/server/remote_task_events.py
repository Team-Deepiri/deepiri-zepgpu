"""Remote task completion callbacks and WebSocket notifications."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from deepiri_zepgpu.api.server.websocket_manager import manager
from deepiri_zepgpu.database.models.node_task_assignment import NodeTaskAssignment
from deepiri_zepgpu.database.models.task import Task

logger = logging.getLogger(__name__)


def build_remote_task_update_payload(
    *,
    task: Task,
    assignment: NodeTaskAssignment,
) -> dict[str, Any]:
    """Build a WebSocket/callback payload for remote task updates."""
    metadata = dict(task.metadata_json or {})
    return {
        "type": "task_update",
        "source": "remote_node",
        "task_id": str(task.id),
        "assignment_id": str(assignment.id),
        "room_id": str(assignment.vpn_network_id),
        "peer_id": str(assignment.peer_id),
        "gpu_share_id": str(assignment.gpu_share_id) if assignment.gpu_share_id else None,
        "status": task.status.value if hasattr(task.status, "value") else str(task.status),
        "assignment_status": (
            assignment.status.value
            if hasattr(assignment.status, "value")
            else str(assignment.status)
        ),
        "result_ref": task.result_ref,
        "result_size_bytes": task.result_size_bytes,
        "remote_result": metadata.get("remote_result"),
        "error": task.error,
    }


async def emit_remote_task_update(
    *,
    task: Task,
    assignment: NodeTaskAssignment,
) -> None:
    """Broadcast a remote task update over the existing WebSocket manager.

    The current manager implementation is intentionally reused instead of adding
    another connection registry. This helper supports common manager method names
    and falls back to the manager's connection map for MVP compatibility.
    """
    payload = build_remote_task_update_payload(task=task, assignment=assignment)
    user_id = str(task.user_id) if task.user_id else None

    try:
        if user_id and hasattr(manager, "send_personal_message"):
            await manager.send_personal_message(payload, user_id)
            return

        if user_id and hasattr(manager, "broadcast_to_user"):
            await manager.broadcast_to_user(user_id, payload)
            return

        if hasattr(manager, "broadcast"):
            await manager.broadcast(payload)
            return

        connections = getattr(manager, "_connections", {})
        for sockets in connections.values():
            for websocket in list(sockets):
                await websocket.send_json(payload)
    except Exception:
        logger.exception("Failed to emit remote task WebSocket update: %s", task.id)


async def send_remote_task_callback(
    *,
    task: Task,
    assignment: NodeTaskAssignment,
) -> None:
    """Send task callback webhook when a remote task reaches a terminal state."""
    if not task.callback_url:
        return

    payload = build_remote_task_update_payload(task=task, assignment=assignment)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(str(task.callback_url), json=payload)
            response.raise_for_status()
    except Exception:
        logger.exception("Failed to send remote task callback: %s", task.id)


async def notify_remote_task_terminal_state(
    *,
    task: Task | None,
    assignment: NodeTaskAssignment,
) -> None:
    """Send callback and WebSocket notification for completed/failed remote tasks."""
    if task is None:
        return

    await emit_remote_task_update(task=task, assignment=assignment)
    await send_remote_task_callback(task=task, assignment=assignment)
