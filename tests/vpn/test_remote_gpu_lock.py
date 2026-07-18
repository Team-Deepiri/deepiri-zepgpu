"""Tests for remote GPU lock."""

from __future__ import annotations

import threading
from uuid import uuid4

from deepiri_zepgpu.vpn.remote_gpu_lock import RemoteGpuLock
from tests.rooms.conftest import FakeRedis


def test_acquire_succeeds_on_free_share() -> None:
    redis = FakeRedis()
    lock = RemoteGpuLock(client=redis)  # type: ignore[arg-type]
    assert lock.acquire("share-1", "task-1") is True
    assert lock.get_holder("share-1") == "task-1"


def test_acquire_fails_when_already_locked() -> None:
    redis = FakeRedis()
    lock = RemoteGpuLock(client=redis)  # type: ignore[arg-type]
    assert lock.acquire("share-1", "task-1") is True
    assert lock.acquire("share-1", "task-2") is False


def test_release_only_deletes_matching_holder() -> None:
    redis = FakeRedis()
    lock = RemoteGpuLock(client=redis)  # type: ignore[arg-type]
    lock.acquire("share-1", "task-1")
    assert lock.release("share-1", "task-2") is False
    assert lock.is_locked("share-1") is True
    assert lock.release("share-1", "task-1") is True
    assert lock.is_locked("share-1") is False


def test_acquire_first_available() -> None:
    redis = FakeRedis()
    lock = RemoteGpuLock(client=redis)  # type: ignore[arg-type]
    redis.set("zepgpu:vpn:gpu_share:share-a", "other-task")
    chosen = lock.acquire_first_available(["share-a", "share-b"], "task-1")
    assert chosen == "share-b"


def test_redis_unavailable_returns_true(monkeypatch) -> None:
    lock = RemoteGpuLock(client=None)
    monkeypatch.setattr(lock, "_conn", lambda: None)
    assert lock.acquire(str(uuid4()), "task-1") is True


def test_concurrent_acquire_only_one_succeeds() -> None:
    redis = FakeRedis()
    lock = RemoteGpuLock(client=redis)  # type: ignore[arg-type]
    share_id = "share-concurrent"
    results: list[bool] = []

    def worker(task_id: str) -> None:
        results.append(lock.acquire(share_id, task_id))

    threads = [threading.Thread(target=worker, args=(f"task-{i}",)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1
    assert results.count(False) == 4
