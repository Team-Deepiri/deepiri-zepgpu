"""Shared fixtures for room dispatch tests."""

from __future__ import annotations

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
    status = (
        PeerOnlineStatus.AWOL
        if awol
        else (PeerOnlineStatus.ONLINE if online else PeerOnlineStatus.OFFLINE)
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
    pid = peer_id or (str(peer.id) if peer else str(uuid4()))
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
    """Minimal in-memory Redis for lock + membership-cache tests."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, int | None]] = {}
        self._sets: dict[str, set[str]] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self._store:
            return False
        self._store[key] = (value, ex)
        return True

    def get(self, key: str) -> str | None:
        item = self._store.get(key)
        return item[0] if item else None

    def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                n += 1
            if key in self._sets:
                del self._sets[key]
                n += 1
        return n

    def exists(self, *keys: str) -> int:
        return sum(1 for k in keys if k in self._store or k in self._sets)

    def expire(self, key: str, _ttl: int) -> bool:
        return key in self._store or key in self._sets

    def sadd(self, key: str, *values: str) -> int:
        s = self._sets.setdefault(key, set())
        before = len(s)
        s.update(str(v) for v in values)
        return len(s) - before

    def srem(self, key: str, *values: str) -> int:
        s = self._sets.get(key)
        if not s:
            return 0
        n = 0
        for v in values:
            if str(v) in s:
                s.discard(str(v))
                n += 1
        if not s:
            del self._sets[key]
        return n

    def smembers(self, key: str) -> set[str]:
        return set(self._sets.get(key, set()))

    def sismember(self, key: str, value: str) -> bool:
        return str(value) in self._sets.get(key, set())

    def pipeline(self) -> "FakeRedisPipeline":
        return FakeRedisPipeline(self)


class FakeRedisPipeline:
    def __init__(self, client: FakeRedis) -> None:
        self._client = client
        self._ops: list[tuple] = []

    def delete(self, *keys: str) -> "FakeRedisPipeline":
        self._ops.append(("delete", keys))
        return self

    def sadd(self, key: str, *values: str) -> "FakeRedisPipeline":
        self._ops.append(("sadd", key, values))
        return self

    def srem(self, key: str, *values: str) -> "FakeRedisPipeline":
        self._ops.append(("srem", key, values))
        return self

    def expire(self, key: str, ttl: int) -> "FakeRedisPipeline":
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self) -> list:
        out: list = []
        for op in self._ops:
            kind = op[0]
            if kind == "delete":
                out.append(self._client.delete(*op[1]))
            elif kind == "sadd":
                out.append(self._client.sadd(op[1], *op[2]))
            elif kind == "srem":
                out.append(self._client.srem(op[1], *op[2]))
            elif kind == "expire":
                out.append(self._client.expire(op[1], op[2]))
        self._ops.clear()
        return out


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def remote_lock(fake_redis: FakeRedis) -> RemoteGpuLock:
    return RemoteGpuLock(client=fake_redis)  # type: ignore[arg-type]
