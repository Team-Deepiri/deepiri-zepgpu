"""Background sweeps for assignment lease expiry and lifecycle timeouts."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.node_task_lifecycle import (
    notify_assignment_terminal,
    push_provider_assignment,
)
from deepiri_zepgpu.database.models.node_task_assignment import (
    NodeAssignmentStatus,
    NodeTerminalReason,
)
from deepiri_zepgpu.database.models.task import Task
from deepiri_zepgpu.database.repositories.node_task_repository import NodeTaskRepository

logger = logging.getLogger(__name__)


async def sweep_assignment_timeouts(db: AsyncSession) -> dict[str, int]:
    """Expire leases, accepted-never-started, and running timeouts.

    Releases GPU capacity and notifies callbacks/WS on every terminal path.
    """
    repo = NodeTaskRepository(db)
    now = datetime.now(UTC)
    counts = {
        "lease_expired": 0,
        "accepted_timeout": 0,
        "running_timeout": 0,
    }

    for assignment in await repo.list_expired_leases(now=now):
        terminal = await repo.mark_terminal(
            assignment,
            status=NodeAssignmentStatus.FAILED,
            terminal_reason=NodeTerminalReason.LEASE_EXPIRED,
            error="Assignment lease expired",
            peer_id=str(assignment.peer_id) if assignment.peer_id else None,
        )
        task = await db.get(Task, terminal.task_id)
        await notify_assignment_terminal(task=task, assignment=terminal)
        if terminal.peer_id:
            await push_provider_assignment(
                peer_id=str(terminal.peer_id),
                assignment=terminal,
                event_type="lease_expired",
            )
        counts["lease_expired"] += 1

    for assignment in await repo.list_accepted_never_started(now=now):
        # Skip if already handled as lease expiry in this sweep.
        if assignment.status in {
            NodeAssignmentStatus.COMPLETED,
            NodeAssignmentStatus.FAILED,
            NodeAssignmentStatus.CANCELLED,
        }:
            continue
        terminal = await repo.mark_terminal(
            assignment,
            status=NodeAssignmentStatus.FAILED,
            terminal_reason=NodeTerminalReason.ACCEPTED_TIMEOUT,
            error="Accepted but never started (timeout)",
            peer_id=str(assignment.peer_id) if assignment.peer_id else None,
        )
        task = await db.get(Task, terminal.task_id)
        await notify_assignment_terminal(task=task, assignment=terminal)
        if terminal.peer_id:
            await push_provider_assignment(
                peer_id=str(terminal.peer_id),
                assignment=terminal,
                event_type="timed_out",
            )
        counts["accepted_timeout"] += 1

    for assignment in await repo.list_running_timed_out(now=now):
        if assignment.status in {
            NodeAssignmentStatus.COMPLETED,
            NodeAssignmentStatus.FAILED,
            NodeAssignmentStatus.CANCELLED,
        }:
            continue
        terminal = await repo.mark_terminal(
            assignment,
            status=NodeAssignmentStatus.FAILED,
            terminal_reason=NodeTerminalReason.RUNNING_TIMEOUT,
            error="Running assignment timed out",
            peer_id=str(assignment.peer_id) if assignment.peer_id else None,
        )
        task = await db.get(Task, terminal.task_id)
        await notify_assignment_terminal(task=task, assignment=terminal)
        if terminal.peer_id:
            await push_provider_assignment(
                peer_id=str(terminal.peer_id),
                assignment=terminal,
                event_type="timed_out",
            )
        counts["running_timeout"] += 1

    total = sum(counts.values())
    if total:
        logger.info("Assignment sweep terminals: %s", counts)
    return counts


async def run_assignment_sweep(db: AsyncSession) -> dict[str, Any]:
    counts = await sweep_assignment_timeouts(db)
    await db.commit()
    return {"status": "ok", **counts}
