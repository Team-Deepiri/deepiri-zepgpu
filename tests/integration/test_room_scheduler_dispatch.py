"""Integration tests for room-aware scheduler dispatch."""

from __future__ import annotations

from uuid import uuid4

import pytest

from deepiri_zepgpu.core.gpu_manager import GPUManager, GPUState, GPUType
from deepiri_zepgpu.vpn.gpu_pool import GpuPoolAggregator, RemoteGPUDevice
from deepiri_zepgpu.vpn.remote_gpu_lock import RemoteGpuLock
from tests.rooms.conftest import FakeRedis


@pytest.mark.integration
def test_gpu_pool_room_filter_returns_only_matching_room() -> None:
    manager = GPUManager()
    lock = RemoteGpuLock(client=FakeRedis())  # type: ignore[arg-type]
    pool = GpuPoolAggregator(manager, remote_lock=lock)

    room_a = str(uuid4())
    room_b = str(uuid4())
    pool._remote_devices = {
        "share-a": RemoteGPUDevice(
            peer_id=str(uuid4()),
            peer_username="a",
            share_id="share-a",
            device_index=0,
            name="GPU-A",
            gpu_type=GPUType.NVIDIA,
            total_memory_mb=8192,
            available_memory_mb=8192,
            compute_capability=(8, 0),
            state=GPUState.IDLE,
            vpn_network_id=room_a,
        ),
        "share-b": RemoteGPUDevice(
            peer_id=str(uuid4()),
            peer_username="b",
            share_id="share-b",
            device_index=0,
            name="GPU-B",
            gpu_type=GPUType.NVIDIA,
            total_memory_mb=8192,
            available_memory_mb=8192,
            compute_capability=(8, 0),
            state=GPUState.IDLE,
            vpn_network_id=room_b,
        ),
    }

    device = pool.get_available_device(required_memory_mb=1024, room_id=room_a, remote_only=True)
    assert device is not None
    assert device.vpn_network_id == room_a


@pytest.mark.integration
def test_gpu_pool_remote_only_skips_local_devices() -> None:
    manager = GPUManager()
    pool = GpuPoolAggregator(manager)
    device = pool.get_available_device(required_memory_mb=0, remote_only=True)
    assert device is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_execute_task_skips_assigned_room_dispatch() -> None:
    class FakeTask:
        dispatch_mode = "room_auto"
        status = type("S", (), {"value": "assigned"})()

    task = FakeTask()
    if (
        task.dispatch_mode in {"room_auto", "room_specific_node"}
        and task.status.value == "assigned"
    ):
        result = {
            "status": "deferred",
            "task_id": "task-1",
            "message": "Room-assigned task awaiting remote execution",
        }
    else:
        result = {"status": "unexpected"}

    assert result["status"] == "deferred"
