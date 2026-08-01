"""Repository for node task assignments."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.models.node_task_assignment import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    NodeAssignmentStatus,
    NodeTaskAssignment,
    NodeTaskEvent,
    NodeTerminalReason,
)
from deepiri_zepgpu.database.models.task import Task, TaskStatus
from deepiri_zepgpu.database.models.vpn_models import GpuShare, GpuShareState

logger = logging.getLogger(__name__)


class NodeTaskTransitionError(ValueError):
    """Raised when a lifecycle request conflicts with terminal state."""


class NodeTaskRepository:
    """Persistence layer for room node task assignments."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_assignment(
        self,
        *,
        vpn_network_id: str,
        task_id: str,
        peer_id: str,
        gpu_share_id: str,
        status: NodeAssignmentStatus = NodeAssignmentStatus.ASSIGNED,
    ) -> NodeTaskAssignment:
        now = datetime.now(UTC)
        assignment = NodeTaskAssignment(
            id=str(uuid.uuid4()),
            vpn_network_id=vpn_network_id,
            task_id=task_id,
            peer_id=peer_id,
            gpu_share_id=gpu_share_id,
            status=status,
            assigned_at=now,
            claim_generation=0,
            retry_count=0,
        )
        self.session.add(assignment)
        await self.session.flush()
        await self.record_event(
            assignment.id,
            "assigned",
            {
                "task_id": task_id,
                "peer_id": peer_id,
                "gpu_share_id": gpu_share_id,
                "status": status.value,
            },
        )
        return assignment

    async def get_by_id(self, assignment_id: str) -> NodeTaskAssignment | None:
        result = await self.session.execute(
            select(NodeTaskAssignment).where(NodeTaskAssignment.id == assignment_id)
        )
        return result.scalar_one_or_none()

    async def get_by_task_id(self, task_id: str) -> NodeTaskAssignment | None:
        result = await self.session.execute(
            select(NodeTaskAssignment)
            .where(NodeTaskAssignment.task_id == task_id)
            .order_by(NodeTaskAssignment.assigned_at.desc())
        )
        return result.scalars().first()

    async def list_by_room(
        self,
        vpn_network_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[NodeTaskAssignment]:
        result = await self.session.execute(
            select(NodeTaskAssignment)
            .where(NodeTaskAssignment.vpn_network_id == vpn_network_id)
            .order_by(NodeTaskAssignment.assigned_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def update_status(
        self,
        assignment_id: str,
        status: NodeAssignmentStatus,
        *,
        error: str | None = None,
    ) -> NodeTaskAssignment | None:
        assignment = await self.get_by_id(assignment_id)
        if not assignment:
            return None

        now = datetime.now(UTC)
        assignment.status = status
        if status == NodeAssignmentStatus.ACCEPTED:
            assignment.accepted_at = now
        elif status == NodeAssignmentStatus.RUNNING:
            assignment.started_at = now
        elif status == NodeAssignmentStatus.COMPLETED:
            assignment.completed_at = now
        elif status == NodeAssignmentStatus.FAILED:
            assignment.failed_at = now
            assignment.error = error
        elif status == NodeAssignmentStatus.CANCELLED:
            assignment.cancelled_at = now

        await self.session.flush()
        return assignment

    async def increment_retry_count(self, assignment_id: str) -> NodeTaskAssignment | None:
        assignment = await self.get_by_id(assignment_id)
        if not assignment:
            return None
        assignment.retry_count += 1
        await self.session.flush()
        return assignment

    async def record_event(
        self,
        assignment_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> NodeTaskEvent:
        event = NodeTaskEvent(
            id=str(uuid.uuid4()),
            assignment_id=assignment_id,
            event_type=event_type,
            payload=payload or {},
            created_at=datetime.now(UTC),
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_pending_for_peer(
        self,
        *,
        vpn_network_id: str,
        peer_id: str,
        limit: int = 1,
    ) -> Sequence[NodeTaskAssignment]:
        """List assigned tasks waiting for a specific room peer."""
        result = await self.session.execute(
            select(NodeTaskAssignment)
            .where(
                NodeTaskAssignment.vpn_network_id == vpn_network_id,
                NodeTaskAssignment.peer_id == peer_id,
                NodeTaskAssignment.status == NodeAssignmentStatus.ASSIGNED,
                NodeTaskAssignment.cancel_requested_at.is_(None),
            )
            .order_by(NodeTaskAssignment.assigned_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_active_for_peer(
        self,
        *,
        peer_id: str,
    ) -> Sequence[NodeTaskAssignment]:
        """List non-terminal assignments for a peer (for revoke cleanup)."""
        result = await self.session.execute(
            select(NodeTaskAssignment).where(
                NodeTaskAssignment.peer_id == peer_id,
                NodeTaskAssignment.status.in_(list(ACTIVE_STATUSES)),
            )
        )
        return result.scalars().all()

    async def list_cancel_requested_for_peer(
        self,
        *,
        vpn_network_id: str,
        peer_id: str,
    ) -> Sequence[NodeTaskAssignment]:
        """Active assignments with cancel propagation pending."""
        result = await self.session.execute(
            select(NodeTaskAssignment).where(
                NodeTaskAssignment.vpn_network_id == vpn_network_id,
                NodeTaskAssignment.peer_id == peer_id,
                NodeTaskAssignment.status.in_(list(ACTIVE_STATUSES)),
                NodeTaskAssignment.cancel_requested_at.is_not(None),
            )
        )
        return result.scalars().all()

    async def get_for_peer(
        self,
        *,
        assignment_id: str,
        peer_id: str,
    ) -> NodeTaskAssignment | None:
        """Get an assignment only if it belongs to the given peer."""
        result = await self.session.execute(
            select(NodeTaskAssignment).where(
                NodeTaskAssignment.id == assignment_id,
                NodeTaskAssignment.peer_id == peer_id,
            )
        )
        return result.scalar_one_or_none()

    def _lease_duration(self) -> timedelta:
        return timedelta(seconds=max(30, int(settings.vpn.assignment_lease_seconds)))

    async def _ignore_terminal_conflict(
        self,
        assignment: NodeTaskAssignment,
        *,
        attempted: str,
        peer_id: str | None = None,
    ) -> NodeTaskAssignment:
        logger.info(
            "Ignoring %s on terminal assignment %s (status=%s reason=%s)",
            attempted,
            assignment.id,
            assignment.status.value,
            assignment.terminal_reason,
        )
        await self.record_event(
            assignment.id,
            "lifecycle_conflict_ignored",
            {
                "attempted": attempted,
                "status": assignment.status.value,
                "terminal_reason": assignment.terminal_reason,
                "peer_id": peer_id,
            },
        )
        return assignment

    async def mark_claimed(
        self,
        *,
        assignment_id: str,
        peer_id: str,
        lease_seconds: int | None = None,
    ) -> NodeTaskAssignment | None:
        """Claim an assigned task: set lease + ACCEPTED. Idempotent for same peer."""
        assignment = await self.get_for_peer(
            assignment_id=assignment_id,
            peer_id=peer_id,
        )
        if assignment is None:
            return None

        if assignment.status in TERMINAL_STATUSES:
            return await self._ignore_terminal_conflict(
                assignment, attempted="claim", peer_id=peer_id
            )

        if assignment.cancel_requested_at is not None:
            return await self.mark_cancelled(
                assignment_id=assignment_id,
                peer_id=peer_id,
                reason="Cancel requested before claim",
            )

        now = datetime.now(UTC)
        lease = timedelta(
            seconds=max(30, int(lease_seconds or settings.vpn.assignment_lease_seconds))
        )

        # Idempotent re-claim while already accepted/running: refresh lease, bump generation.
        if assignment.status in {
            NodeAssignmentStatus.ACCEPTED,
            NodeAssignmentStatus.RUNNING,
        }:
            assignment.lease_expires_at = now + lease
            assignment.claim_generation = int(assignment.claim_generation or 0) + 1
            if assignment.claimed_at is None:
                assignment.claimed_at = now
            await self.record_event(
                assignment.id,
                "claimed",
                {
                    "peer_id": str(peer_id),
                    "claim_generation": assignment.claim_generation,
                    "lease_expires_at": assignment.lease_expires_at.isoformat(),
                    "idempotent": True,
                },
            )
            await self.session.flush()
            return assignment

        assignment.status = NodeAssignmentStatus.ACCEPTED
        assignment.accepted_at = now
        assignment.claimed_at = now
        assignment.claim_generation = int(assignment.claim_generation or 0) + 1
        assignment.lease_expires_at = now + lease

        await self.record_event(
            assignment.id,
            "claimed",
            {
                "peer_id": str(peer_id),
                "claim_generation": assignment.claim_generation,
                "lease_expires_at": assignment.lease_expires_at.isoformat(),
            },
        )
        await self.session.flush()
        return assignment

    async def mark_accepted(
        self,
        *,
        assignment_id: str,
        peer_id: str,
    ) -> NodeTaskAssignment | None:
        """Backwards-compatible accept = claim with default lease."""
        return await self.mark_claimed(assignment_id=assignment_id, peer_id=peer_id)

    async def mark_running(
        self,
        *,
        assignment_id: str,
        peer_id: str,
    ) -> NodeTaskAssignment | None:
        """Mark a node task and parent task as running."""
        assignment = await self.get_for_peer(
            assignment_id=assignment_id,
            peer_id=peer_id,
        )
        if assignment is None:
            return None

        if assignment.status == NodeAssignmentStatus.RUNNING:
            return assignment
        if assignment.status == NodeAssignmentStatus.COMPLETED:
            return assignment
        if assignment.status in {
            NodeAssignmentStatus.FAILED,
            NodeAssignmentStatus.CANCELLED,
        }:
            return await self._ignore_terminal_conflict(
                assignment, attempted="start", peer_id=peer_id
            )

        if assignment.cancel_requested_at is not None:
            return await self.mark_cancelled(
                assignment_id=assignment_id,
                peer_id=peer_id,
                reason="Cancel requested before start",
            )

        if self._lease_expired(assignment):
            return await self.mark_terminal(
                assignment,
                status=NodeAssignmentStatus.FAILED,
                terminal_reason=NodeTerminalReason.LEASE_EXPIRED,
                error="Lease expired before start",
                peer_id=peer_id,
            )

        now = datetime.now(UTC)
        assignment.status = NodeAssignmentStatus.RUNNING
        assignment.started_at = now
        # Refresh lease for the running window.
        assignment.lease_expires_at = now + self._lease_duration()

        task = await self.session.get(Task, assignment.task_id)
        if task:
            task.status = TaskStatus.RUNNING
            task.started_at = now

        await self.record_event(
            assignment.id,
            "started",
            {"peer_id": str(peer_id), "task_id": str(assignment.task_id)},
        )
        await self.session.flush()
        return assignment

    async def _release_gpu_share(self, assignment: NodeTaskAssignment) -> None:
        """Release the GPU share associated with a completed or failed assignment."""
        if not assignment.gpu_share_id:
            return

        gpu_share = await self.session.get(GpuShare, assignment.gpu_share_id)
        if not gpu_share:
            logger.debug(
                "GPU share %s not found for release (assignment %s); it may "
                "already have been deactivated or deleted.",
                assignment.gpu_share_id,
                assignment.id,
            )
            return

        # Only clear if this assignment still owns the share (prevent cross-task release).
        if gpu_share.current_task_id is not None and str(gpu_share.current_task_id) != str(
            assignment.task_id
        ):
            logger.warning(
                "Skipping GPU share release for assignment %s; share %s held by task %s",
                assignment.id,
                assignment.gpu_share_id,
                gpu_share.current_task_id,
            )
            return

        gpu_share.state = GpuShareState.IDLE
        gpu_share.current_task_id = None

    def _lease_expired(self, assignment: NodeTaskAssignment, *, now: datetime | None = None) -> bool:
        if assignment.lease_expires_at is None:
            return False
        current = now or datetime.now(UTC)
        expires = assignment.lease_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return current > expires

    async def mark_terminal(
        self,
        assignment: NodeTaskAssignment,
        *,
        status: NodeAssignmentStatus,
        terminal_reason: NodeTerminalReason | str,
        error: str | None = None,
        peer_id: str | None = None,
        result_metadata: dict[str, Any] | None = None,
        task_status: TaskStatus | None = None,
    ) -> NodeTaskAssignment:
        """Apply first-wins terminal transition and release GPU share."""
        if assignment.status in TERMINAL_STATUSES:
            return await self._ignore_terminal_conflict(
                assignment,
                attempted=f"terminal:{terminal_reason}",
                peer_id=peer_id,
            )

        reason = (
            terminal_reason.value
            if isinstance(terminal_reason, NodeTerminalReason)
            else str(terminal_reason)
        )
        now = datetime.now(UTC)
        assignment.status = status
        assignment.terminal_reason = reason
        assignment.error = error

        if status == NodeAssignmentStatus.COMPLETED:
            assignment.completed_at = now
        elif status == NodeAssignmentStatus.CANCELLED:
            assignment.cancelled_at = now
            if assignment.cancel_requested_at is None:
                assignment.cancel_requested_at = now
        else:
            assignment.failed_at = now

        task = await self.session.get(Task, assignment.task_id)
        if task and task.status not in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMEOUT,
        }:
            mapped = task_status
            if mapped is None:
                if status == NodeAssignmentStatus.COMPLETED:
                    mapped = TaskStatus.COMPLETED
                elif status == NodeAssignmentStatus.CANCELLED:
                    mapped = TaskStatus.CANCELLED
                elif reason in {
                    NodeTerminalReason.ACCEPTED_TIMEOUT.value,
                    NodeTerminalReason.RUNNING_TIMEOUT.value,
                    NodeTerminalReason.LEASE_EXPIRED.value,
                }:
                    mapped = TaskStatus.TIMEOUT
                else:
                    mapped = TaskStatus.FAILED
            task.status = mapped
            task.completed_at = now
            if error:
                task.error = error
            if result_metadata is not None:
                task.metadata_json = dict(task.metadata_json or {})
                task.metadata_json["remote_result"] = result_metadata
                result_ref = (
                    result_metadata.get("result_ref")
                    or result_metadata.get("result_uri")
                    or result_metadata.get("storage_ref")
                )
                if result_ref:
                    task.result_ref = str(result_ref)
                result_size_bytes = result_metadata.get("result_size_bytes")
                if isinstance(result_size_bytes, int):
                    task.result_size_bytes = result_size_bytes

        await self._release_gpu_share(assignment)

        event_type = {
            NodeAssignmentStatus.COMPLETED: "completed",
            NodeAssignmentStatus.CANCELLED: "cancelled",
            NodeAssignmentStatus.FAILED: reason,
        }.get(status, reason)

        await self.record_event(
            assignment.id,
            event_type,
            {
                "peer_id": peer_id or (str(assignment.peer_id) if assignment.peer_id else None),
                "task_id": str(assignment.task_id),
                "gpu_share_id": str(assignment.gpu_share_id) if assignment.gpu_share_id else None,
                "terminal_reason": reason,
                "error": error,
                "result_metadata": result_metadata or {},
            },
        )
        await self.session.flush()
        return assignment

    async def mark_completed(
        self,
        *,
        assignment_id: str,
        peer_id: str,
        result_metadata: dict[str, Any] | None = None,
    ) -> NodeTaskAssignment | None:
        """Mark a node task as completed and release its GPU share."""
        assignment = await self.get_for_peer(
            assignment_id=assignment_id,
            peer_id=peer_id,
        )
        if assignment is None:
            return None

        if assignment.status == NodeAssignmentStatus.COMPLETED:
            return assignment
        if assignment.status in TERMINAL_STATUSES:
            return await self._ignore_terminal_conflict(
                assignment, attempted="complete", peer_id=peer_id
            )
        if assignment.cancel_requested_at is not None:
            return await self.mark_cancelled(
                assignment_id=assignment_id,
                peer_id=peer_id,
                reason="Cancel requested; cannot complete",
            )
        if self._lease_expired(assignment):
            return await self.mark_terminal(
                assignment,
                status=NodeAssignmentStatus.FAILED,
                terminal_reason=NodeTerminalReason.LEASE_EXPIRED,
                error="Lease expired; cannot complete",
                peer_id=peer_id,
            )

        return await self.mark_terminal(
            assignment,
            status=NodeAssignmentStatus.COMPLETED,
            terminal_reason=NodeTerminalReason.COMPLETED,
            peer_id=peer_id,
            result_metadata=result_metadata or {},
        )

    async def mark_failed(
        self,
        *,
        assignment_id: str,
        peer_id: str,
        error: str,
        terminal_reason: NodeTerminalReason | str = NodeTerminalReason.FAILED,
    ) -> NodeTaskAssignment | None:
        """Mark a node task as failed and release its GPU share."""
        assignment = await self.get_for_peer(
            assignment_id=assignment_id,
            peer_id=peer_id,
        )
        if assignment is None:
            return None

        if assignment.status == NodeAssignmentStatus.FAILED:
            return assignment
        if assignment.status in TERMINAL_STATUSES:
            return await self._ignore_terminal_conflict(
                assignment, attempted="fail", peer_id=peer_id
            )

        return await self.mark_terminal(
            assignment,
            status=NodeAssignmentStatus.FAILED,
            terminal_reason=terminal_reason,
            error=error,
            peer_id=peer_id,
        )

    async def request_cancel(
        self,
        *,
        assignment_id: str,
        reason: str = "Cancelled by host",
    ) -> NodeTaskAssignment | None:
        """Flag cancel for an active assignment and finalize if still assigned."""
        assignment = await self.get_by_id(assignment_id)
        if assignment is None:
            return None
        if assignment.status in TERMINAL_STATUSES:
            return assignment

        now = datetime.now(UTC)
        if assignment.cancel_requested_at is None:
            assignment.cancel_requested_at = now
            await self.record_event(
                assignment.id,
                "cancel_requested",
                {"reason": reason},
            )

        # ASSIGNED work that was never claimed can terminate immediately.
        if assignment.status == NodeAssignmentStatus.ASSIGNED:
            return await self.mark_cancelled(
                assignment_id=assignment_id,
                peer_id=str(assignment.peer_id) if assignment.peer_id else None,
                reason=reason,
            )

        await self.session.flush()
        return assignment

    async def mark_cancelled(
        self,
        *,
        assignment_id: str,
        peer_id: str | None = None,
        reason: str = "Cancelled",
    ) -> NodeTaskAssignment | None:
        assignment = await self.get_by_id(assignment_id)
        if assignment is None:
            return None
        if peer_id is not None and str(assignment.peer_id) != str(peer_id):
            return None
        if assignment.status == NodeAssignmentStatus.CANCELLED:
            return assignment
        if assignment.status in TERMINAL_STATUSES:
            return await self._ignore_terminal_conflict(
                assignment, attempted="cancel", peer_id=peer_id
            )

        return await self.mark_terminal(
            assignment,
            status=NodeAssignmentStatus.CANCELLED,
            terminal_reason=NodeTerminalReason.CANCELLED,
            error=reason,
            peer_id=peer_id,
            task_status=TaskStatus.CANCELLED,
        )

    async def list_expired_leases(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[NodeTaskAssignment]:
        current = now or datetime.now(UTC)
        result = await self.session.execute(
            select(NodeTaskAssignment)
            .where(
                NodeTaskAssignment.status.in_(
                    [NodeAssignmentStatus.ACCEPTED, NodeAssignmentStatus.RUNNING]
                ),
                NodeTaskAssignment.lease_expires_at.is_not(None),
                NodeTaskAssignment.lease_expires_at < current,
            )
            .order_by(NodeTaskAssignment.lease_expires_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_accepted_never_started(
        self,
        *,
        timeout_seconds: int | None = None,
        now: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[NodeTaskAssignment]:
        current = now or datetime.now(UTC)
        timeout = timeout_seconds or settings.vpn.accepted_start_timeout_seconds
        threshold = current - timedelta(seconds=max(10, int(timeout)))
        result = await self.session.execute(
            select(NodeTaskAssignment)
            .where(
                NodeTaskAssignment.status == NodeAssignmentStatus.ACCEPTED,
                NodeTaskAssignment.accepted_at.is_not(None),
                NodeTaskAssignment.accepted_at < threshold,
            )
            .order_by(NodeTaskAssignment.accepted_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_running_timed_out(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> Sequence[NodeTaskAssignment]:
        """Running assignments past task timeout or configured running timeout."""
        current = now or datetime.now(UTC)
        override = settings.vpn.running_timeout_seconds

        result = await self.session.execute(
            select(NodeTaskAssignment)
            .where(NodeTaskAssignment.status == NodeAssignmentStatus.RUNNING)
            .order_by(NodeTaskAssignment.started_at.asc())
            .limit(limit * 4)
        )
        candidates = list(result.scalars().all())
        timed_out: list[NodeTaskAssignment] = []
        for assignment in candidates:
            if assignment.started_at is None:
                continue
            started = assignment.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            timeout_seconds = override
            if timeout_seconds is None:
                task = await self.session.get(Task, assignment.task_id)
                timeout_seconds = int(task.timeout_seconds) if task else 3600
            if current > started + timedelta(seconds=max(10, int(timeout_seconds))):
                timed_out.append(assignment)
            if len(timed_out) >= limit:
                break
        return timed_out

    async def reconcile_for_peer(
        self,
        *,
        vpn_network_id: str,
        peer_id: str,
        local_assignment_ids: Sequence[str],
    ) -> list[dict[str, Any]]:
        """Reconcile agent local in-flight IDs with coordinator state.

        Actions:
        - resume: assignment still active with valid lease
        - fail_expired: lease expired → terminal fail
        - abandon: local ID unknown / wrong peer / already terminal
        - cancel: cancel was requested
        """
        outcomes: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        seen: set[str] = set()

        for raw_id in local_assignment_ids:
            assignment_id = str(raw_id)
            if assignment_id in seen:
                continue
            seen.add(assignment_id)

            assignment = await self.get_for_peer(
                assignment_id=assignment_id,
                peer_id=peer_id,
            )
            if assignment is None:
                outcomes.append(
                    {
                        "assignment_id": assignment_id,
                        "action": "abandon",
                        "reason": "not_found_or_wrong_peer",
                    }
                )
                continue

            if str(assignment.vpn_network_id) != str(vpn_network_id):
                outcomes.append(
                    {
                        "assignment_id": assignment_id,
                        "action": "abandon",
                        "reason": "cross_room",
                        "status": assignment.status.value,
                    }
                )
                continue

            if assignment.status in TERMINAL_STATUSES:
                outcomes.append(
                    {
                        "assignment_id": assignment_id,
                        "action": "abandon",
                        "reason": "already_terminal",
                        "status": assignment.status.value,
                        "terminal_reason": assignment.terminal_reason,
                    }
                )
                continue

            if assignment.cancel_requested_at is not None:
                cancelled = await self.mark_cancelled(
                    assignment_id=assignment_id,
                    peer_id=peer_id,
                    reason="Reconcile: cancel requested",
                )
                outcomes.append(
                    {
                        "assignment_id": assignment_id,
                        "action": "cancel",
                        "status": cancelled.status.value if cancelled else "cancelled",
                        "terminal_reason": cancelled.terminal_reason if cancelled else "cancelled",
                    }
                )
                continue

            if self._lease_expired(assignment, now=now):
                failed = await self.mark_terminal(
                    assignment,
                    status=NodeAssignmentStatus.FAILED,
                    terminal_reason=NodeTerminalReason.LEASE_EXPIRED,
                    error="Lease expired during reconcile",
                    peer_id=peer_id,
                )
                outcomes.append(
                    {
                        "assignment_id": assignment_id,
                        "action": "fail_expired",
                        "status": failed.status.value,
                        "terminal_reason": failed.terminal_reason,
                    }
                )
                continue

            outcomes.append(
                {
                    "assignment_id": assignment_id,
                    "action": "resume",
                    "status": assignment.status.value,
                    "claim_generation": assignment.claim_generation,
                    "lease_expires_at": (
                        assignment.lease_expires_at.isoformat()
                        if assignment.lease_expires_at
                        else None
                    ),
                    "cancel_requested": assignment.cancel_requested,
                }
            )

        # Also surface active assignments the agent may have lost locally.
        active = await self.list_active_for_peer(peer_id=peer_id)
        for assignment in active:
            if str(assignment.id) in seen:
                continue
            if str(assignment.vpn_network_id) != str(vpn_network_id):
                continue
            outcomes.append(
                {
                    "assignment_id": str(assignment.id),
                    "action": "resume",
                    "status": assignment.status.value,
                    "claim_generation": assignment.claim_generation,
                    "lease_expires_at": (
                        assignment.lease_expires_at.isoformat()
                        if assignment.lease_expires_at
                        else None
                    ),
                    "cancel_requested": assignment.cancel_requested,
                    "recovered": True,
                }
            )

        return outcomes
