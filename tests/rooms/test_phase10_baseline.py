"""Phase 10 baseline access, lifecycle, and heartbeat regression tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from deepiri_zepgpu.api.server.routes import node_tasks
from deepiri_zepgpu.config import APISettings
from deepiri_zepgpu.database.models.node_task_assignment import NodeAssignmentStatus
from deepiri_zepgpu.database.repositories.node_task_repository import NodeTaskRepository
from deepiri_zepgpu.rooms import dispatch
from deepiri_zepgpu.rooms.dispatch import RoomAccessError, RoomValidationError
from deepiri_zepgpu.vpn import peer_manager


def test_api_settings_ignore_generic_debug_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEBUG", "release")
    api_settings = APISettings()

    assert api_settings.debug is False


@pytest.mark.asyncio
async def test_room_access_denies_non_member(monkeypatch: pytest.MonkeyPatch) -> None:
    room = SimpleNamespace(id="room-a")

    class FakeNetworkRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _room_id: str) -> object:
            return room

        async def list_user_networks(self, _user_id: str) -> list[object]:
            return [SimpleNamespace(id="room-b")]

    monkeypatch.setattr(dispatch, "VpnNetworkRepository", FakeNetworkRepository)
    with pytest.raises(RoomAccessError):
        await dispatch.ensure_room_access(object(), "user-a", "room-a")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cross_room_target_peer_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePeerRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _peer_id: str) -> object:
            return SimpleNamespace(id="peer-a", vpn_network_id="room-b")

    monkeypatch.setattr(dispatch, "PeerRepository", FakePeerRepository)
    with pytest.raises(RoomValidationError, match="does not belong"):
        await dispatch._validate_dispatch_targets(
            object(),  # type: ignore[arg-type]
            "room-a",
            target_peer_id="peer-a",
            target_gpu_share_id=None,
        )


@pytest.mark.asyncio
async def test_completed_lifecycle_retry_does_not_duplicate_event() -> None:
    assignment = SimpleNamespace(
        id="assignment-a",
        task_id="task-a",
        peer_id="peer-a",
        gpu_share_id=None,
        status=NodeAssignmentStatus.COMPLETED,
    )
    session = SimpleNamespace()
    repo = NodeTaskRepository(session)  # type: ignore[arg-type]
    repo.get_for_peer = AsyncMock(return_value=assignment)  # type: ignore[method-assign]
    repo.record_event = AsyncMock()  # type: ignore[method-assign]

    result = await repo.mark_completed(
        assignment_id="assignment-a",
        peer_id="peer-a",
        result_metadata={"kind": "noop"},
    )

    assert result is assignment
    repo.record_event.assert_not_awaited()


def test_terminal_assignment_releases_remote_gpu_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    release = Mock()

    class FakeLock:
        def release(self, share_id: str, task_id: str) -> bool:
            release(share_id, task_id)
            return True

    monkeypatch.setattr(node_tasks, "RemoteGpuLock", FakeLock)
    node_tasks._release_assignment_lock(
        SimpleNamespace(id="assignment-a", gpu_share_id="gpu-a", task_id="task-a")
    )
    release.assert_called_once_with("gpu-a", "task-a")


@pytest.mark.asyncio
async def test_stale_provider_becomes_awol_and_emits_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_peer = SimpleNamespace(
        id="peer-a",
        vpn_network_id="room-a",
        user_id="user-a",
        last_seen=None,
    )

    class FakePeerRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def mark_awol_peers(self, _timeout: int) -> list[object]:
            return [stale_peer]

    emit = AsyncMock()
    monkeypatch.setattr(peer_manager, "PeerRepository", FakePeerRepository)
    monkeypatch.setattr(peer_manager, "emit_room_event", emit)

    count = await peer_manager.mark_stale_peers_offline(object())  # type: ignore[arg-type]

    assert count == 1
    emit.assert_awaited_once()
    assert emit.await_args.args[1] == "room_node_offline"
    assert emit.await_args.args[2]["status"] == "awol"
