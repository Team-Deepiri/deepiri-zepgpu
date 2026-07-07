"""Tests for room GPU dispatch policy."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.vpn_models import GpuShareState
from deepiri_zepgpu.rooms.dispatch import (
    NoRoomGpuAvailable,
    RoomValidationError,
    rank_eligible_shares,
    select_and_assign_room_gpu,
)
from tests.rooms.conftest import make_peer, make_share


def test_rank_eligible_shares_filters_offline_and_memory(room_id: str, peer_id: str) -> None:
    online_peer = make_peer(peer_id=peer_id, room_id=room_id, online=True)
    offline_peer = make_peer(room_id=room_id, online=False)
    shares = [
        make_share(peer=online_peer, room_id=room_id, available_memory_mb=4096),
        make_share(peer=offline_peer, room_id=room_id, available_memory_mb=8192),
        make_share(peer=online_peer, room_id=room_id, available_memory_mb=1024),
    ]

    ranked = rank_eligible_shares(shares, required_memory_mb=2048)
    assert len(ranked) == 1
    assert ranked[0].available_memory_mb == 4096


def test_rank_eligible_shares_prefers_higher_memory_and_lower_utilization(
    room_id: str,
) -> None:
    peer_a = make_peer(room_id=room_id)
    peer_b = make_peer(room_id=room_id)
    shares = [
        make_share(peer=peer_a, room_id=room_id, available_memory_mb=4096, utilization_percent=20.0),
        make_share(peer=peer_b, room_id=room_id, available_memory_mb=8192, utilization_percent=30.0),
        make_share(peer=peer_b, room_id=room_id, available_memory_mb=8192, utilization_percent=5.0),
    ]

    ranked = rank_eligible_shares(shares, required_memory_mb=1024)
    assert str(ranked[0].utilization_percent) == "5.0"
    assert ranked[0].available_memory_mb == 8192


def test_rank_eligible_shares_excludes_awol(room_id: str) -> None:
    awol_peer = make_peer(room_id=room_id, awol=True)
    shares = [make_share(peer=awol_peer, room_id=room_id)]
    assert rank_eligible_shares(shares, required_memory_mb=512) == []


def test_rank_eligible_shares_target_peer(room_id: str, peer_id: str) -> None:
    target = make_peer(peer_id=peer_id, room_id=room_id)
    other = make_peer(room_id=room_id)
    shares = [
        make_share(peer=target, room_id=room_id),
        make_share(peer=other, room_id=room_id, available_memory_mb=99999),
    ]
    ranked = rank_eligible_shares(
        shares,
        required_memory_mb=512,
        target_peer_id=peer_id,
    )
    assert len(ranked) == 1
    assert str(ranked[0].peer_id) == peer_id


@pytest.mark.asyncio
async def test_select_and_assign_room_gpu_success(
    room_id: str,
    task_id: str,
    user_id: str,
    remote_lock,
) -> None:
    peer = make_peer(room_id=room_id)
    share = make_share(peer=peer, room_id=room_id)

    class FakeGpuRepo:
        async def list_by_network(self, _room_id: str, active_only: bool = True) -> list:
            return [share]

        async def get_by_id(self, _share_id: str):
            return share

        async def update_state(self, share_id: str, state, current_task_id=None):
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

    class FakeDb:
        pass

    db = FakeDb()
    import deepiri_zepgpu.rooms.dispatch as dispatch_module

    original_gpu = dispatch_module.GpuShareRepository
    original_network = dispatch_module.VpnNetworkRepository
    original_node = dispatch_module.NodeTaskRepository
    dispatch_module.GpuShareRepository = lambda _db: FakeGpuRepo()  # type: ignore
    dispatch_module.VpnNetworkRepository = lambda _db: FakeNetworkRepo()  # type: ignore
    dispatch_module.NodeTaskRepository = FakeNodeRepo  # type: ignore

    try:
        result = await select_and_assign_room_gpu(
            db,  # type: ignore[arg-type]
            user_id=user_id,
            room_id=room_id,
            task_id=task_id,
            required_memory_mb=1024,
            dispatch_mode="room_auto",
            remote_lock=remote_lock,
        )
    finally:
        dispatch_module.GpuShareRepository = original_gpu
        dispatch_module.VpnNetworkRepository = original_network
        dispatch_module.NodeTaskRepository = original_node

    assert result.peer_id == str(peer.id)
    assert share.state == GpuShareState.ALLOCATED
    assert remote_lock.is_locked(str(share.id))


@pytest.mark.asyncio
async def test_select_and_assign_no_gpu_raises(room_id: str, task_id: str, user_id: str) -> None:
    class FakeGpuRepo:
        async def list_by_network(self, _room_id: str, active_only: bool = True) -> list:
            return []

    class FakeNetworkRepo:
        async def get_by_id(self, _room_id: str):
            return SimpleNamespace(id=room_id)

        async def list_user_networks(self, _user_id: str):
            return [SimpleNamespace(id=room_id)]

    import deepiri_zepgpu.rooms.dispatch as dispatch_module

    original_gpu = dispatch_module.GpuShareRepository
    original_network = dispatch_module.VpnNetworkRepository
    dispatch_module.GpuShareRepository = lambda _db: FakeGpuRepo()  # type: ignore
    dispatch_module.VpnNetworkRepository = lambda _db: FakeNetworkRepo()  # type: ignore

    try:
        with pytest.raises(NoRoomGpuAvailable):
            await select_and_assign_room_gpu(
                object(),  # type: ignore[arg-type]
                user_id=user_id,
                room_id=room_id,
                task_id=task_id,
                required_memory_mb=1024,
                dispatch_mode="room_auto",
            )
    finally:
        dispatch_module.GpuShareRepository = original_gpu
        dispatch_module.VpnNetworkRepository = original_network


@pytest.mark.asyncio
async def test_room_specific_node_requires_target() -> None:
    with pytest.raises(RoomValidationError):
        await select_and_assign_room_gpu(
            object(),  # type: ignore[arg-type]
            user_id=str(uuid4()),
            room_id=str(uuid4()),
            task_id=str(uuid4()),
            required_memory_mb=1024,
            dispatch_mode="room_specific_node",
        )
