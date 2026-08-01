"""Phase 13 assignment claim/lease/terminal lifecycle tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.node_task_assignment import (
    NodeAssignmentStatus,
    NodeTerminalReason,
)
from deepiri_zepgpu.database.models.task import TaskStatus
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
        self._by_id: dict[str, Any] = {}
        self._tasks: dict[str, Any] = {}

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if hasattr(obj, "id"):
            self._by_id[str(obj.id)] = obj

    async def flush(self) -> None:
        return None

    async def execute(self, _stmt: object) -> FakeResult:
        return FakeResult(None)

    async def get(self, model: type, key: object) -> Any:
        from deepiri_zepgpu.database.models.task import Task
        from deepiri_zepgpu.database.models.vpn_models import GpuShare

        key_s = str(key)
        if model is Task:
            return self._tasks.get(key_s)
        if model is GpuShare:
            return self._by_id.get(key_s)
        return self._by_id.get(key_s)


def _assignment(
    *,
    status: NodeAssignmentStatus = NodeAssignmentStatus.ASSIGNED,
    peer_id: str | None = None,
    lease_expires_at: datetime | None = None,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=str(uuid4()),
        vpn_network_id=str(uuid4()),
        task_id=str(uuid4()),
        peer_id=peer_id or str(uuid4()),
        gpu_share_id=str(uuid4()),
        status=status,
        assigned_at=now,
        accepted_at=None,
        started_at=None,
        completed_at=None,
        failed_at=None,
        cancelled_at=None,
        claimed_at=None,
        lease_expires_at=lease_expires_at,
        claim_generation=0,
        terminal_reason=None,
        cancel_requested_at=None,
        error=None,
        retry_count=0,
        is_terminal=status
        in {
            NodeAssignmentStatus.COMPLETED,
            NodeAssignmentStatus.FAILED,
            NodeAssignmentStatus.CANCELLED,
        },
        cancel_requested=False,
    )


@pytest.mark.asyncio
async def test_claim_sets_lease_and_generation() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    assignment = _assignment()
    peer_id = assignment.peer_id

    async def fake_get_for_peer(**_kwargs: Any) -> object:
        return assignment

    repo.get_for_peer = fake_get_for_peer  # type: ignore[method-assign]

    claimed = await repo.mark_claimed(assignment_id=assignment.id, peer_id=peer_id)
    assert claimed is assignment
    assert assignment.status == NodeAssignmentStatus.ACCEPTED
    assert assignment.claimed_at is not None
    assert assignment.lease_expires_at is not None
    assert assignment.claim_generation == 1


@pytest.mark.asyncio
async def test_first_terminal_wins_on_conflicting_complete() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    assignment = _assignment(status=NodeAssignmentStatus.CANCELLED)
    assignment.terminal_reason = NodeTerminalReason.CANCELLED.value
    assignment.is_terminal = True

    async def fake_get_for_peer(**_kwargs: Any) -> object:
        return assignment

    repo.get_for_peer = fake_get_for_peer  # type: ignore[method-assign]

    result = await repo.mark_completed(
        assignment_id=assignment.id,
        peer_id=assignment.peer_id,
        result_metadata={"ok": True},
    )
    assert result is assignment
    assert assignment.status == NodeAssignmentStatus.CANCELLED
    assert assignment.terminal_reason == NodeTerminalReason.CANCELLED.value


@pytest.mark.asyncio
async def test_expired_lease_cannot_complete() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    assignment = _assignment(
        status=NodeAssignmentStatus.RUNNING,
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    task = SimpleNamespace(
        id=assignment.task_id,
        status=TaskStatus.RUNNING,
        completed_at=None,
        error=None,
        metadata_json={},
        result_ref=None,
        result_size_bytes=None,
    )
    session._tasks[assignment.task_id] = task

    async def fake_get_for_peer(**_kwargs: Any) -> object:
        return assignment

    repo.get_for_peer = fake_get_for_peer  # type: ignore[method-assign]

    result = await repo.mark_completed(
        assignment_id=assignment.id,
        peer_id=assignment.peer_id,
        result_metadata={"ok": True},
    )
    assert result is assignment
    assert assignment.status == NodeAssignmentStatus.FAILED
    assert assignment.terminal_reason == NodeTerminalReason.LEASE_EXPIRED.value


@pytest.mark.asyncio
async def test_cancel_request_flags_running_assignment() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    assignment = _assignment(status=NodeAssignmentStatus.RUNNING)

    async def fake_get(_id: str) -> object:
        return assignment

    repo.get_by_id = fake_get  # type: ignore[method-assign]

    result = await repo.request_cancel(assignment_id=assignment.id, reason="host cancel")
    assert result is assignment
    assert assignment.cancel_requested_at is not None
    assert assignment.status == NodeAssignmentStatus.RUNNING


@pytest.mark.asyncio
async def test_reconcile_fails_expired_lease() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    peer_id = str(uuid4())
    room_id = str(uuid4())
    assignment = _assignment(
        status=NodeAssignmentStatus.ACCEPTED,
        peer_id=peer_id,
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    assignment.vpn_network_id = room_id
    task = SimpleNamespace(
        id=assignment.task_id,
        status=TaskStatus.ASSIGNED,
        completed_at=None,
        error=None,
        metadata_json={},
        result_ref=None,
        result_size_bytes=None,
    )
    session._tasks[assignment.task_id] = task

    async def fake_get_for_peer(*, assignment_id: str, peer_id: str) -> object | None:
        if assignment_id == assignment.id and peer_id == peer_id:
            return assignment
        return None

    async def fake_list_active(*, peer_id: str) -> list[object]:
        return []

    repo.get_for_peer = fake_get_for_peer  # type: ignore[method-assign]
    repo.list_active_for_peer = fake_list_active  # type: ignore[method-assign]

    outcomes = await repo.reconcile_for_peer(
        vpn_network_id=room_id,
        peer_id=peer_id,
        local_assignment_ids=[assignment.id],
    )
    assert outcomes[0]["action"] == "fail_expired"
    assert assignment.terminal_reason == NodeTerminalReason.LEASE_EXPIRED.value


@pytest.mark.asyncio
async def test_reconcile_resumes_valid_lease() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    peer_id = str(uuid4())
    room_id = str(uuid4())
    assignment = _assignment(
        status=NodeAssignmentStatus.RUNNING,
        peer_id=peer_id,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assignment.vpn_network_id = room_id
    assignment.claim_generation = 2

    async def fake_get_for_peer(*, assignment_id: str, peer_id: str) -> object | None:
        return assignment if assignment_id == assignment.id else None

    async def fake_list_active(*, peer_id: str) -> list[object]:
        return []

    repo.get_for_peer = fake_get_for_peer  # type: ignore[method-assign]
    repo.list_active_for_peer = fake_list_active  # type: ignore[method-assign]

    outcomes = await repo.reconcile_for_peer(
        vpn_network_id=room_id,
        peer_id=peer_id,
        local_assignment_ids=[assignment.id],
    )
    assert outcomes[0]["action"] == "resume"
    assert outcomes[0]["claim_generation"] == 2


@pytest.mark.asyncio
async def test_gpu_share_release_skips_cross_task_holder() -> None:
    session = FakeSession()
    repo = NodeTaskRepository(session)
    assignment = _assignment(status=NodeAssignmentStatus.RUNNING)
    other_task = str(uuid4())
    share = SimpleNamespace(
        id=assignment.gpu_share_id,
        state=SimpleNamespace(value="allocated"),
        current_task_id=other_task,
    )
    session._by_id[str(assignment.gpu_share_id)] = share

    await repo._release_gpu_share(assignment)  # type: ignore[arg-type]
    assert share.current_task_id == other_task
