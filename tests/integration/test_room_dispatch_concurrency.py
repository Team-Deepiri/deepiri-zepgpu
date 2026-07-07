"""Concurrency tests for room dispatch locking."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.vpn_models import GpuShareState
from deepiri_zepgpu.rooms.dispatch import NoRoomGpuAvailable, select_and_assign_room_gpu
from tests.rooms.conftest import FakeRedis, make_peer, make_share


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_dispatch_only_one_locks_single_gpu() -> None:
    room_id = str(uuid4())
    peer = make_peer(room_id=room_id)
    share = make_share(peer=peer, room_id=room_id)
    lock = __import__("deepiri_zepgpu.vpn.remote_gpu_lock", fromlist=["RemoteGpuLock"]).RemoteGpuLock(
        client=FakeRedis()  # type: ignore[arg-type]
    )

    class FakeGpuRepo:
        async def list_by_network(self, _room_id: str, active_only: bool = True):
            return [share]

        async def get_by_id(self, _share_id: str):
            return share

        async def update_state(self, share_id: str, state, current_task_id=None):
            if state == GpuShareState.ALLOCATED and share.state == GpuShareState.ALLOCATED:
                return None
            share.state = state
            share.current_task_id = current_task_id
            return share

    class FakeNetworkRepo:
        async def get_by_id(self, _room_id: str):
            return SimpleNamespace(id=room_id)

        async def list_user_networks(self, _user_id: str):
            return [SimpleNamespace(id=room_id)]

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

    import deepiri_zepgpu.rooms.dispatch as dispatch_module

    dispatch_module.GpuShareRepository = lambda _db: FakeGpuRepo()  # type: ignore
    dispatch_module.VpnNetworkRepository = lambda _db: FakeNetworkRepo()  # type: ignore
    dispatch_module.NodeTaskRepository = FakeNodeRepo  # type: ignore

    async def attempt(task_id: str):
        try:
            return await select_and_assign_room_gpu(
                object(),  # type: ignore[arg-type]
                user_id=str(uuid4()),
                room_id=room_id,
                task_id=task_id,
                required_memory_mb=1024,
                dispatch_mode="room_auto",
                remote_lock=lock,
            )
        except Exception as exc:
            return exc

    results = await asyncio.gather(*(attempt(f"task-{i}") for i in range(3)))
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1
    assert len(failures) == 2
    assert all(isinstance(f, (NoRoomGpuAvailable, __import__("deepiri_zepgpu.rooms.dispatch", fromlist=["RoomGpuLockError"]).RoomGpuLockError)) for f in failures)
