"""Tests for node-task lifecycle room events and single terminal notify."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepiri_zepgpu.api.server.routes import node_tasks


def _assignment() -> SimpleNamespace:
    return SimpleNamespace(
        id="assignment-1",
        vpn_network_id="room-1",
        task_id="task-1",
        peer_id="peer-1",
        gpu_share_id="gpu-1",
        status=SimpleNamespace(value="assigned"),
        accepted_at=None,
        started_at=None,
        completed_at=None,
        failed_at=None,
        error=None,
    )


class FakeNodeTaskRepository:
    def __init__(self, assignment: SimpleNamespace) -> None:
        self.assignment = assignment

    async def mark_claimed(self, **_kwargs):
        self.assignment.status = SimpleNamespace(value="accepted")
        self.assignment.claimed_at = None
        self.assignment.lease_expires_at = None
        self.assignment.claim_generation = 1
        self.assignment.is_terminal = False
        return self.assignment

    async def mark_accepted(self, **_kwargs):
        return await self.mark_claimed(**_kwargs)

    async def mark_running(self, **_kwargs):
        self.assignment.status = SimpleNamespace(value="running")
        self.assignment.is_terminal = False
        return self.assignment

    async def mark_completed(self, **_kwargs):
        self.assignment.status = SimpleNamespace(value="completed")
        self.assignment.is_terminal = True
        self.assignment.terminal_reason = "completed"
        return self.assignment

    async def mark_failed(self, **kwargs):
        self.assignment.status = SimpleNamespace(value="failed")
        self.assignment.error = kwargs["error"]
        self.assignment.is_terminal = True
        self.assignment.terminal_reason = "failed"
        return self.assignment


class FakeDb:
    def __init__(self, task: SimpleNamespace) -> None:
        self.task = task

    async def commit(self) -> None:
        return None

    async def refresh(self, _assignment) -> None:
        return None

    async def get(self, _model, _task_id):
        return self.task


def _prepare(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SimpleNamespace, FakeDb, SimpleNamespace, AsyncMock, AsyncMock]:
    assignment = _assignment()
    assignment.is_terminal = False
    assignment.terminal_reason = None
    assignment.claimed_at = None
    assignment.lease_expires_at = None
    assignment.claim_generation = 0
    assignment.cancel_requested_at = None
    repo = FakeNodeTaskRepository(assignment)
    task = SimpleNamespace(status=SimpleNamespace(value="running"), error=None)
    db = FakeDb(task)
    peer = SimpleNamespace(id="peer-1")
    emit_event = AsyncMock()
    notify = AsyncMock()

    monkeypatch.setattr(node_tasks, "NodeTaskRepository", lambda _db: repo)
    monkeypatch.setattr(node_tasks, "emit_assignment_room_event", emit_event)
    monkeypatch.setattr(node_tasks, "notify_assignment_terminal", notify)
    return assignment, db, peer, emit_event, notify


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "expected_event"),
    [
        ("claim", "room_task_claimed"),
        ("accept", "room_task_claimed"),
        ("start", "room_task_started"),
        ("complete", "room_task_completed"),
        ("fail", "room_task_failed"),
    ],
)
async def test_node_task_lifecycle_emits_matching_room_event(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    expected_event: str,
) -> None:
    assignment, db, peer, emit_event, notify = _prepare(monkeypatch)

    if operation == "claim":
        await node_tasks.claim_node_task("assignment-1", db=db, peer=peer)
        emit_event.assert_awaited_once()
        assert emit_event.await_args.kwargs["event_type"] == expected_event
        notify.assert_not_awaited()
    elif operation == "accept":
        await node_tasks.accept_node_task("assignment-1", db=db, peer=peer)
        emit_event.assert_awaited_once()
        assert emit_event.await_args.kwargs["event_type"] == expected_event
        notify.assert_not_awaited()
    elif operation == "start":
        await node_tasks.start_node_task("assignment-1", db=db, peer=peer)
        emit_event.assert_awaited_once()
        assert emit_event.await_args.kwargs["event_type"] == expected_event
    elif operation == "complete":
        assignment.is_terminal = True
        await node_tasks.complete_node_task(
            "assignment-1",
            node_tasks.CompleteNodeTaskRequest(result_metadata={"ok": True}),
            db=db,
            peer=peer,
        )
        notify.assert_awaited_once()
        emit_event.assert_not_awaited()
    else:
        assignment.is_terminal = True
        await node_tasks.fail_node_task(
            "assignment-1",
            node_tasks.FailNodeTaskRequest(error="worker failed"),
            db=db,
            peer=peer,
        )
        notify.assert_awaited_once()
        emit_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_and_accept_share_room_event_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, db, peer, emit_event, _notify = _prepare(monkeypatch)
    await node_tasks.claim_node_task("assignment-1", db=db, peer=peer)
    claim_event = emit_event.await_args.kwargs["event_type"]

    emit_event.reset_mock()
    assignment2, db2, peer2, emit_event2, _ = _prepare(monkeypatch)
    del assignment2
    await node_tasks.accept_node_task("assignment-1", db=db2, peer=peer2)
    accept_event = emit_event2.await_args.kwargs["event_type"]

    assert claim_event == accept_event == "room_task_claimed"


@pytest.mark.asyncio
async def test_claim_on_terminal_soft_returns_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deepiri_zepgpu.database.repositories.node_task_repository import mark_lifecycle_noop

    assignment, db, peer, emit_event, notify = _prepare(monkeypatch)
    assignment.status = SimpleNamespace(value="failed")
    assignment.is_terminal = True
    assignment.terminal_reason = "lease_expired"
    assignment.error = "Lease expired"

    class Repo:
        def __init__(self, _db: object) -> None:
            pass

        async def mark_claimed(self, **_kwargs: object):
            return mark_lifecycle_noop(assignment)

    monkeypatch.setattr(node_tasks, "NodeTaskRepository", lambda _db: Repo())
    response = await node_tasks.claim_node_task("assignment-1", db=db, peer=peer)
    assert response.noop is True
    assert response.status == "failed"
    assert response.terminal_reason == "lease_expired"
    emit_event.assert_not_awaited()
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_notifies_assignment_terminal_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment, db, peer, emit_event, notify = _prepare(monkeypatch)
    assignment.is_terminal = True
    await node_tasks.complete_node_task(
        "assignment-1",
        node_tasks.CompleteNodeTaskRequest(result_metadata={"ok": True}),
        db=db,
        peer=peer,
    )
    notify.assert_awaited_once()
    emit_event.assert_not_awaited()
