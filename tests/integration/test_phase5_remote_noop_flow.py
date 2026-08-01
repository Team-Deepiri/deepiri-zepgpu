"""Integration test for Phase 5 remote no-op node execution flow."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.node_task_assignment import (
    NodeAssignmentStatus,
    NodeTaskAssignment,
    NodeTaskEvent,
)
from deepiri_zepgpu.database.models.task import TaskStatus
from deepiri_zepgpu.database.models.vpn_models import GpuShareState
from deepiri_zepgpu.database.repositories.node_task_repository import NodeTaskRepository
from deepiri_zepgpu.node_agent.task_worker import NodeTaskWorker


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items

    def first(self) -> Any | None:
        return self.items[0] if self.items else None


class FakeExecuteResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def scalars(self) -> FakeScalarResult:
        return FakeScalarResult(self.items)

    def scalar_one_or_none(self) -> Any | None:
        if not self.items:
            return None
        return self.items[0]


class FakeSession:
    """Minimal async session for NodeTaskRepository lifecycle testing."""

    def __init__(self, *, task: Any, gpu_share: Any) -> None:
        self.assignments: list[NodeTaskAssignment] = []
        self.events: list[NodeTaskEvent] = []
        self.objects: dict[str, Any] = {
            str(task.id): task,
            str(gpu_share.id): gpu_share,
        }

    def add(self, obj: Any) -> None:
        if isinstance(obj, NodeTaskAssignment):
            self.assignments.append(obj)
        elif isinstance(obj, NodeTaskEvent):
            self.events.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, _statement: Any) -> FakeExecuteResult:
        return FakeExecuteResult(self.assignments)

    async def get(self, _model: Any, object_id: Any) -> Any | None:
        return self.objects.get(str(object_id))


class FakeTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id
        self.status = TaskStatus.ASSIGNED
        self.started_at = None
        self.completed_at = None
        self.error = None
        self.metadata_json: dict[str, Any] = {}


class FakeGpuShare:
    def __init__(self, gpu_share_id: str, task_id: str) -> None:
        self.id = gpu_share_id
        self.state = GpuShareState.ALLOCATED
        self.current_task_id = task_id


class FakeNodeTaskClient:
    """In-process node task client that talks directly to the repository."""

    def __init__(
        self,
        *,
        repo: NodeTaskRepository,
        room_id: str,
        peer_id: str,
    ) -> None:
        self.repo = repo
        self.room_id = room_id
        self.peer_id = peer_id

    async def poll_pending(self, *, limit: int = 1) -> list[dict[str, str]]:
        assignments = await self.repo.list_pending_for_peer(
            vpn_network_id=self.room_id,
            peer_id=self.peer_id,
            limit=limit,
        )
        return [
            {
                "assignment_id": str(assignment.id),
                "task_id": str(assignment.task_id),
            }
            for assignment in assignments
        ]

    async def poll(self, *, limit: int = 1) -> dict[str, Any]:
        return {
            "assignments": await self.poll_pending(limit=limit),
            "cancel_requested": [],
        }

    async def claim(self, assignment_id: str) -> dict[str, str]:
        return await self.accept(assignment_id)

    async def accept(self, assignment_id: str) -> dict[str, str]:
        assignment = await self.repo.mark_accepted(
            assignment_id=assignment_id,
            peer_id=self.peer_id,
        )
        assert assignment is not None
        return {
            "assignment_id": str(assignment.id),
            "task_id": str(assignment.task_id),
            "status": assignment.status.value,
        }

    async def start(self, assignment_id: str) -> dict[str, str]:
        assignment = await self.repo.mark_running(
            assignment_id=assignment_id,
            peer_id=self.peer_id,
        )
        assert assignment is not None
        return {
            "assignment_id": str(assignment.id),
            "task_id": str(assignment.task_id),
            "status": assignment.status.value,
        }

    async def complete(
        self,
        assignment_id: str,
        *,
        result_metadata: dict[str, Any],
    ) -> dict[str, str]:
        assignment = await self.repo.mark_completed(
            assignment_id=assignment_id,
            peer_id=self.peer_id,
            result_metadata=result_metadata,
        )
        assert assignment is not None
        return {
            "assignment_id": str(assignment.id),
            "task_id": str(assignment.task_id),
            "status": assignment.status.value,
        }

    async def fail(self, assignment_id: str, *, error: str) -> dict[str, str]:
        assignment = await self.repo.mark_failed(
            assignment_id=assignment_id,
            peer_id=self.peer_id,
            error=error,
        )
        assert assignment is not None
        return {
            "assignment_id": str(assignment.id),
            "task_id": str(assignment.task_id),
            "status": assignment.status.value,
        }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_phase5_remote_noop_flow_completes_task_and_releases_gpu() -> None:
    room_id = str(uuid4())
    peer_id = str(uuid4())
    gpu_share_id = str(uuid4())
    task_id = str(uuid4())

    task = FakeTask(task_id)
    gpu_share = FakeGpuShare(gpu_share_id, task_id)
    session = FakeSession(task=task, gpu_share=gpu_share)

    repo = NodeTaskRepository(session)  # type: ignore[arg-type]
    assignment = await repo.create_assignment(
        vpn_network_id=room_id,
        task_id=task_id,
        peer_id=peer_id,
        gpu_share_id=gpu_share_id,
    )

    client = FakeNodeTaskClient(
        repo=repo,
        room_id=room_id,
        peer_id=peer_id,
    )
    worker = NodeTaskWorker(client=client)  # type: ignore[arg-type]

    processed = await worker.run_once()
    completed_assignment = await repo.get_by_id(str(assignment.id))

    assert processed == 1
    assert completed_assignment is not None
    assert completed_assignment.status == NodeAssignmentStatus.COMPLETED
    assert completed_assignment.accepted_at is not None
    assert completed_assignment.started_at is not None
    assert completed_assignment.completed_at is not None

    assert task.status == TaskStatus.COMPLETED
    assert task.started_at is not None
    assert task.completed_at is not None
    assert task.metadata_json["remote_result"]["status"] == "ok"
    assert task.metadata_json["remote_result"]["kind"] == "noop"

    assert gpu_share.state == GpuShareState.IDLE
    assert gpu_share.current_task_id is None

    assert [event.event_type for event in session.events] == [
        "assigned",
        "claimed",
        "started",
        "completed",
    ]
