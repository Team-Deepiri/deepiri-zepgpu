"""Repository for node task assignments."""

from __future__ import annotations

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
