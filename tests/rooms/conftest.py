"""Shared fixtures for room dispatch tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.vpn_models import GpuShareState, PeerOnlineStatus
from deepiri_zepgpu.vpn.remote_gpu_lock import RemoteGpuLock


@pytest.fixture
def room_id() -> str:
    return str(uuid4())


@pytest.fixture
def peer_id() -> str:
    return str(uuid4())


@pytest.fixture
def share_id() -> str:
    return str(uuid4())


@pytest.fixture
def task_id() -> str:
    return str(uuid4())


@pytest.fixture
def user_id() -> str:
    return str(uuid4())


def make_peer(
    *,
    peer_id: str | None = None,
    room_id: str | None = None,
    user_id: str | None = None,
    online: bool = True,
    is_gpu_host: bool = True,
    awol: bool = False,
) -> SimpleNamespace:
    status = PeerOnlineStatus.AWOL if awol else (
        PeerOnlineStatus.ONLINE if online else PeerOnlineStatus.OFFLINE
    )
    return SimpleNamespace(
        id=peer_id or str(uuid4()),
        vpn_network_id=room_id or str(uuid4()),
        user_id=user_id or str(uuid4()),
        online_status=status,
        is_gpu_host=is_gpu_host,
        vpn_ip="10.8.0.2",
        user=SimpleNamespace(username="node-user"),
    )


def make_share(
    *,
    share_id: str | None = None,
    peer_id: str | None = None,
    room_id: str | None = None,
    peer: object | None = None,
    available_memory_mb: int = 8192,
    utilization_percent: float = 5.0,
    active: bool = True,
    idle: bool = True,
    gpu_type: str = "nvidia",
) -> SimpleNamespace:
    pid = peer_id or str(peer.id) if peer else str(uuid4())
    rid = room_id or str(uuid4())
    return SimpleNamespace(
        id=share_id or str(uuid4()),
        peer_id=pid,
        vpn_network_id=rid,
        peer=peer or make_peer(peer_id=pid, room_id=rid),
        device_index=0,
        name="Test GPU",
        total_memory_mb=24576,
        available_memory_mb=available_memory_mb,
        compute_capability="8.9",
        gpu_type=gpu_type,
        state=GpuShareState.IDLE if idle else GpuShareState.ALLOCATED,
        current_task_id=None,
        utilization_percent=utilization_percent,
        is_active=active,
    )


class FakeRedis:
    """Minimal in-memory Redis for lock tests."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, int | None]] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = (value, ex)
        return True

    def get(self, key: str) -> str | None:
        item = self._store.get(key)
        return item[0] if item else None

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def remote_lock(fake_redis: FakeRedis) -> RemoteGpuLock:
    return RemoteGpuLock(client=fake_redis)  # type: ignore[arg-type]
