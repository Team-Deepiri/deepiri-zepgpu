"""Repository for node task assignments."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.node_task_assignment import (
    NodeAssignmentStatus,
    NodeTaskAssignment,
    NodeTaskEvent,
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
            retry_count=0,
        )
        self.session.add(assignment)
        await self.session.flush()
        await self.record_event(
            assignment.id,
            "assignment_created",
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
            )
            .order_by(NodeTaskAssignment.assigned_at.asc())
            .limit(limit)
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

    async def mark_accepted(
        self,
        *,
        assignment_id: str,
        peer_id: str,
    ) -> NodeTaskAssignment | None:
        """Mark an assigned node task as accepted by the peer."""
        assignment = await self.get_for_peer(
            assignment_id=assignment_id,
            peer_id=peer_id,
        )
        if assignment is None:
            return None

        if assignment.status in {
            NodeAssignmentStatus.ACCEPTED,
            NodeAssignmentStatus.RUNNING,
            NodeAssignmentStatus.COMPLETED,
        }:
            return assignment
        if assignment.status in {NodeAssignmentStatus.FAILED, NodeAssignmentStatus.CANCELLED}:
            raise NodeTaskTransitionError(f"Cannot accept a {assignment.status.value} assignment")

        assignment.status = NodeAssignmentStatus.ACCEPTED
        assignment.accepted_at = datetime.now(UTC)

        await self.record_event(
            assignment.id,
            "assignment_accepted",
            {"peer_id": str(peer_id)},
        )
        await self.session.flush()
        return assignment

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

        if assignment.status in {NodeAssignmentStatus.RUNNING, NodeAssignmentStatus.COMPLETED}:
            return assignment
        if assignment.status in {NodeAssignmentStatus.FAILED, NodeAssignmentStatus.CANCELLED}:
            raise NodeTaskTransitionError(f"Cannot start a {assignment.status.value} assignment")

        now = datetime.now(UTC)
        assignment.status = NodeAssignmentStatus.RUNNING
        assignment.started_at = now

        task = await self.session.get(Task, assignment.task_id)
        if task:
            task.status = TaskStatus.RUNNING
            task.started_at = now

        await self.record_event(
            assignment.id,
            "assignment_started",
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

        gpu_share.state = GpuShareState.IDLE
        gpu_share.current_task_id = None

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
        if assignment.status in {NodeAssignmentStatus.FAILED, NodeAssignmentStatus.CANCELLED}:
            raise NodeTaskTransitionError(f"Cannot complete a {assignment.status.value} assignment")

        now = datetime.now(UTC)
        assignment.status = NodeAssignmentStatus.COMPLETED
        assignment.completed_at = now

        task = await self.session.get(Task, assignment.task_id)
        if task:
            metadata = result_metadata or {}
            task.status = TaskStatus.COMPLETED
            task.completed_at = now
            task.metadata_json = dict(task.metadata_json or {})
            task.metadata_json["remote_result"] = metadata

            result_ref = (
                metadata.get("result_ref")
                or metadata.get("result_uri")
                or metadata.get("storage_ref")
            )
            if result_ref:
                task.result_ref = str(result_ref)

            result_size_bytes = metadata.get("result_size_bytes")
            if isinstance(result_size_bytes, int):
                task.result_size_bytes = result_size_bytes

        await self._release_gpu_share(assignment)

        await self.record_event(
            assignment.id,
            "assignment_completed",
            {
                "peer_id": str(peer_id),
                "task_id": str(assignment.task_id),
                "gpu_share_id": str(assignment.gpu_share_id) if assignment.gpu_share_id else None,
                "result_metadata": result_metadata or {},
            },
        )
        await self.session.flush()
        return assignment

    async def mark_failed(
        self,
        *,
        assignment_id: str,
        peer_id: str,
        error: str,
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
        if assignment.status in {NodeAssignmentStatus.COMPLETED, NodeAssignmentStatus.CANCELLED}:
            raise NodeTaskTransitionError(f"Cannot fail a {assignment.status.value} assignment")

        now = datetime.now(UTC)
        assignment.status = NodeAssignmentStatus.FAILED
        assignment.failed_at = now
        assignment.error = error

        task = await self.session.get(Task, assignment.task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = now

        await self._release_gpu_share(assignment)

        await self.record_event(
            assignment.id,
            "assignment_failed",
            {
                "peer_id": str(peer_id),
                "task_id": str(assignment.task_id),
                "gpu_share_id": str(assignment.gpu_share_id) if assignment.gpu_share_id else None,
                "error": error,
            },
        )
        await self.session.flush()
        return assignment
