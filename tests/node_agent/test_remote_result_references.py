"""Tests for remote result reference persistence."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.node_task_assignment import NodeAssignmentStatus
from deepiri_zepgpu.database.models.task import TaskStatus
from deepiri_zepgpu.database.models.vpn_models import GpuShareState
from deepiri_zepgpu.database.repositories.node_task_repository import NodeTaskRepository


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


class FakeTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id
        self.status = TaskStatus.RUNNING
        self.started_at = None
        self.completed_at = None
        self.error = None
        self.metadata_json: dict[str, Any] = {}
        self.result_ref = None
        self.result_size_bytes = None


class FakeGpuShare:
    def __init__(self, gpu_share_id: str, task_id: str) -> None:
        self.id = gpu_share_id
        self.state = GpuShareState.ALLOCATED
        self.current_task_id = task_id


class FakeSession:
    def __init__(self, *, task: FakeTask, gpu_share: FakeGpuShare) -> None:
        self.assignments: list[Any] = []
        self.events: list[Any] = []
        self.objects: dict[str, Any] = {
            str(task.id): task,
            str(gpu_share.id): gpu_share,
        }

    def add(self, obj: Any) -> None:
        if obj.__class__.__name__ == "NodeTaskAssignment":
            self.assignments.append(obj)
        elif obj.__class__.__name__ == "NodeTaskEvent":
            self.events.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, _statement: Any) -> FakeExecuteResult:
        return FakeExecuteResult(self.assignments)

    async def get(self, _model: Any, object_id: Any) -> Any | None:
        return self.objects.get(str(object_id))


@pytest.mark.asyncio
async def test_mark_completed_persists_remote_result_reference() -> None:
    room_id = str(uuid4())
    peer_id = str(uuid4())
    task_id = str(uuid4())
    gpu_share_id = str(uuid4())

    task = FakeTask(task_id)
    gpu_share = FakeGpuShare(gpu_share_id, task_id)
    session = FakeSession(task=task, gpu_share=gpu_share)

    repo = NodeTaskRepository(session)  # type: ignore[arg-type]
    assignment = await repo.create_assignment(
        vpn_network_id=room_id,
        task_id=task_id,
        peer_id=peer_id,
        gpu_share_id=gpu_share_id,
        status=NodeAssignmentStatus.RUNNING,
    )

    await repo.mark_completed(
        assignment_id=str(assignment.id),
        peer_id=peer_id,
        result_metadata={
            "status": "ok",
            "kind": "large_result",
            "result_ref": "s3://bucket/path/result.json",
            "result_size_bytes": 4096,
        },
    )

    assert task.status == TaskStatus.COMPLETED
    assert task.metadata_json["remote_result"]["status"] == "ok"
    assert task.result_ref == "s3://bucket/path/result.json"
    assert task.result_size_bytes == 4096
    assert gpu_share.state == GpuShareState.IDLE
    assert gpu_share.current_task_id is None
