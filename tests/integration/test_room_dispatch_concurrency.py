"""Concurrency tests for room dispatch locking."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.vpn_models import GpuShareState
from deepiri_zepgpu.rooms.dispatch import (
    NoRoomGpuAvailable,
    RoomGpuLockError,
    select_and_assign_room_gpu,
)
from deepiri_zepgpu.vpn.remote_gpu_lock import RemoteGpuLock
from tests.rooms.conftest import FakeRedis, make_peer, make_share


class FakeGpuRepo:
    def __init__(self, share: SimpleNamespace) -> None:
        self.share = share

    async def list_by_network(self, _room_id: str, active_only: bool = True):
        return [self.share]

    async def get_by_id(self, _share_id: str):
        return self.share

    async def update_state(self, share_id: str, state, current_task_id=None):
        if state == GpuShareState.ALLOCATED and self.share.state == GpuShareState.ALLOCATED:
            return None
        self.share.state = state
        self.share.current_task_id = current_task_id
        return self.share


class FakeNetworkRepo:
    def __init__(self, room_id: str) -> None:
        self.room_id = room_id

    async def get_by_id(self, _room_id: str):
        return SimpleNamespace(id=self.room_id)

    async def list_user_networks(self, _user_id: str):
        return [SimpleNamespace(id=self.room_id)]


class FakeNodeRepo:
    def __init__(self, _session) -> None:
        pass

    async def create_assignment(self, **kwargs):
        return SimpleNamespace(
            id=str(uuid4()),
            status=SimpleNamespace(value="assigned"),
            **kwargs,
        )

    async def record_event(self, *args, **kwargs):
        return SimpleNamespace()


def _patch_dispatch_repositories(monkeypatch: pytest.MonkeyPatch, room_id: str, share) -> None:
    import deepiri_zepgpu.rooms.dispatch as dispatch_module

    monkeypatch.setattr(
        dispatch_module,
        "GpuShareRepository",
        lambda _db: FakeGpuRepo(share),
    )
    monkeypatch.setattr(
        dispatch_module,
        "VpnNetworkRepository",
        lambda _db: FakeNetworkRepo(room_id),
    )
    monkeypatch.setattr(dispatch_module, "NodeTaskRepository", FakeNodeRepo)


async def _attempt_room_dispatch(
    *,
    room_id: str,
    task_id: str,
    remote_lock: RemoteGpuLock,
):
    try:
        return await select_and_assign_room_gpu(
            object(),  # type: ignore[arg-type]
            user_id=str(uuid4()),
            room_id=room_id,
            task_id=task_id,
            required_memory_mb=1024,
            dispatch_mode="room_auto",
            remote_lock=remote_lock,
        )
    except Exception as exc:
        return exc


def _split_dispatch_results(results):
    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, Exception)]
    return successes, failures


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_dispatch_only_one_locks_single_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = str(uuid4())
    peer = make_peer(room_id=room_id)
    share = make_share(peer=peer, room_id=room_id)
    lock = RemoteGpuLock(client=FakeRedis())  # type: ignore[arg-type]

    _patch_dispatch_repositories(monkeypatch, room_id, share)

    results = await asyncio.gather(
        *(
            _attempt_room_dispatch(
                room_id=room_id,
                task_id=f"task-{index}",
                remote_lock=lock,
            )
            for index in range(3)
        )
    )
    successes, failures = _split_dispatch_results(results)

    assert len(successes) == 1
    assert len(failures) == 2
    assert all(isinstance(failure, NoRoomGpuAvailable | RoomGpuLockError) for failure in failures)
