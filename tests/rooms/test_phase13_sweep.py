"""Phase 13 sweep + terminal notification / GPU release tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from deepiri_zepgpu.api.server import node_task_lifecycle
from deepiri_zepgpu.database.models.node_task_assignment import (
    NodeAssignmentStatus,
    NodeTerminalReason,
)
from deepiri_zepgpu.rooms import assignment_sweep


@pytest.mark.asyncio
async def test_release_assignment_lock_uses_task_holder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = Mock(return_value=True)

    class FakeLock:
        def release(self, share_id: str, task_id: str) -> bool:
            return release(share_id, task_id)

    monkeypatch.setattr(node_task_lifecycle, "RemoteGpuLock", FakeLock)
    assignment = SimpleNamespace(id="a1", gpu_share_id="gpu-a", task_id="task-a")
    node_task_lifecycle.release_assignment_lock(assignment)  # type: ignore[arg-type]
    release.assert_called_once_with("gpu-a", "task-a")


@pytest.mark.asyncio
async def test_sweep_marks_lease_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    assignment = SimpleNamespace(
        id=str(uuid4()),
        task_id=str(uuid4()),
        peer_id=str(uuid4()),
        status=NodeAssignmentStatus.ACCEPTED,
        lease_expires_at=now - timedelta(seconds=10),
        terminal_reason=None,
        error=None,
    )

    class FakeRepo:
        def __init__(self, _db: object) -> None:
            pass

        async def list_expired_leases(self, **_kwargs: Any) -> list[object]:
            return [assignment]

        async def list_accepted_never_started(self, **_kwargs: Any) -> list[object]:
            return []

        async def list_running_timed_out(self, **_kwargs: Any) -> list[object]:
            return []

        async def mark_terminal(self, asn: Any, **kwargs: Any) -> Any:
            asn.status = kwargs["status"]
            asn.terminal_reason = kwargs["terminal_reason"].value
            asn.error = kwargs.get("error")
            return asn

    notify = AsyncMock()
    push = AsyncMock()
    monkeypatch.setattr(assignment_sweep, "NodeTaskRepository", FakeRepo)
    monkeypatch.setattr(assignment_sweep, "notify_assignment_terminal", notify)
    monkeypatch.setattr(assignment_sweep, "push_provider_assignment", push)

    class FakeDb:
        async def get(self, _model: object, _key: object) -> None:
            return None

        async def commit(self) -> None:
            return None

    counts = await assignment_sweep.sweep_assignment_timeouts(FakeDb())  # type: ignore[arg-type]
    assert counts["lease_expired"] == 1
    assert assignment.terminal_reason == NodeTerminalReason.LEASE_EXPIRED.value
    notify.assert_awaited()
    push.assert_awaited()


@pytest.mark.asyncio
async def test_notify_terminal_emits_callback_and_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = Mock()
    notify_remote = AsyncMock()
    emit_room = AsyncMock()
    monkeypatch.setattr(node_task_lifecycle, "release_assignment_lock", release)
    monkeypatch.setattr(node_task_lifecycle, "notify_remote_task_terminal_state", notify_remote)
    monkeypatch.setattr(node_task_lifecycle, "emit_assignment_room_event", emit_room)

    task = SimpleNamespace(id="t1", error=None)
    assignment = SimpleNamespace(
        id="a1",
        status=SimpleNamespace(value="completed"),
        terminal_reason="completed",
        error=None,
        peer_id="p1",
        gpu_share_id="g1",
        task_id="t1",
        vpn_network_id="r1",
        claim_generation=1,
        lease_expires_at=None,
        cancel_requested=False,
    )
    await node_task_lifecycle.notify_assignment_terminal(
        task=task,  # type: ignore[arg-type]
        assignment=assignment,  # type: ignore[arg-type]
    )
    release.assert_called_once()
    notify_remote.assert_awaited_once()
    emit_room.assert_awaited_once()
