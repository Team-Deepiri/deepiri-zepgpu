"""Tests for node task assignment repository."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.node_task_assignment import NodeAssignmentStatus
from deepiri_zepgpu.database.repositories.node_task_repository import NodeTaskRepository


class FakeResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def scalars(self) -> FakeResult:
        return self

    def first(self) -> object | None:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def all(self) -> list[object]:
        return list(self._value) if isinstance(self._value, list) else []


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.executed: list[object] = []
        self._assignments: dict[str, object] = {}
        self._events: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if hasattr(obj, "id"):
            self._assignments[str(obj.id)] = obj
        self._events.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, stmt: object) -> FakeResult:
        self.executed.append(stmt)
        return FakeResult(None)


@pytest.mark.asyncio
async def test_create_assignment_persists() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    room_id = str(uuid4())
    task_id = str(uuid4())
    peer_id = str(uuid4())
    share_id = str(uuid4())

    assignment = await repo.create_assignment(
        vpn_network_id=room_id,
        task_id=task_id,
        peer_id=peer_id,
        gpu_share_id=share_id,
    )

    assert assignment.vpn_network_id == room_id
    assert assignment.task_id == task_id
    assert assignment.status == NodeAssignmentStatus.ASSIGNED
    assert assignment.retry_count == 0
    assert len(session.added) >= 2


@pytest.mark.asyncio
async def test_update_status_sets_timestamps() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    assignment_id = str(uuid4())
    assignment = SimpleNamespace(
        id=assignment_id,
        status=NodeAssignmentStatus.ASSIGNED,
        assigned_at=datetime.now(UTC),
        accepted_at=None,
        started_at=None,
        completed_at=None,
        failed_at=None,
        error=None,
    )

    async def fake_get(_assignment_id: str) -> object | None:
        return assignment

    repo.get_by_id = fake_get  # type: ignore[method-assign]

    updated = await repo.update_status(assignment_id, NodeAssignmentStatus.RUNNING)
    assert updated is assignment
    assert assignment.status == NodeAssignmentStatus.RUNNING
    assert assignment.started_at is not None


@pytest.mark.asyncio
async def test_record_event_appends_payload() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    event = await repo.record_event("assignment-1", "assignment_created", {"ok": True})
    assert event.event_type == "assignment_created"
    assert event.payload == {"ok": True}
