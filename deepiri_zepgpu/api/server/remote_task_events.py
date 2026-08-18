"""Remote task completion callbacks and WebSocket notifications."""

from __future__ import annotations

import logging
from typing import Any

from deepiri_zepgpu.api.server.websocket_manager import manager
from deepiri_zepgpu.database.models.node_task_assignment import NodeTaskAssignment
from deepiri_zepgpu.database.models.task import Task
from deepiri_zepgpu.security.callbacks import deliver_callback

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
        "terminal_reason": getattr(assignment, "terminal_reason", None),
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

    Talks to the manager's actual, concrete interface directly instead of
    runtime-probing with hasattr() for method names: `send_personal_message`
    when the task has an owning user, `broadcast` otherwise. The previous
    version also probed for `broadcast_to_user`, but ConnectionManager has
    never had that method -- that branch was dead code masking the fact
    that the fallback chain didn't match the real manager's interface.
    """
    payload = build_remote_task_update_payload(task=task, assignment=assignment)
    user_id = str(task.user_id) if task.user_id else None
    try:
        if user_id:
            await manager.send_personal_message(payload, user_id)
        else:
            await manager.broadcast(payload)
    except Exception:
        logger.exception("Failed to emit remote task WebSocket update: %s", task.id)


async def send_remote_task_callback(
    *,
    task: Task,
    assignment: NodeTaskAssignment,
) -> None:
    """Send a terminal-state callback through the centralized safe delivery path."""
    if not task.callback_url:
        return

    payload = build_remote_task_update_payload(task=task, assignment=assignment)

    try:
        await deliver_callback(str(task.callback_url), payload)
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
