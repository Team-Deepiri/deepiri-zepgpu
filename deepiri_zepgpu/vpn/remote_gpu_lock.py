"""Redis-backed locks for remote GPU share allocation (relay)."""

from __future__ import annotations

from collections.abc import Iterable

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore

from deepiri_zepgpu.config import settings

_PREFIX = "zepgpu:vpn:gpu_share:"


class RemoteGpuLock:
    """Best-effort distributed lock per gpu_share id."""

    def __init__(self, url: str | None = None, client: redis.Redis | None = None):
        self._url = url or settings.redis.url
        self._client: redis.Redis | None = client

    def _conn(self) -> redis.Redis | None:
        if redis is None:
            return None
        if self._client is None:
            self._client = redis.Redis.from_url(self._url, decode_responses=True)
        return self._client

    def acquire(self, share_id: str, task_id: str, ttl_seconds: int = 7200) -> bool:
        """Acquire lock for share. Returns False if already held."""
        c = self._conn()
        if c is None:
            return True
        key = f"{_PREFIX}{share_id}"
        return bool(c.set(key, task_id, nx=True, ex=ttl_seconds))

    def acquire_first_available(
        self,
        share_ids: Iterable[str],
        task_id: str,
        ttl_seconds: int = 7200,
    ) -> str | None:
        """Try to acquire lock for the first available share id."""
        for share_id in share_ids:
            if self.acquire(share_id, task_id, ttl_seconds=ttl_seconds):
                return share_id
        return None

    def is_locked(self, share_id: str) -> bool:
        c = self._conn()
        if c is None:
            return False
        return c.get(f"{_PREFIX}{share_id}") is not None

    def get_holder(self, share_id: str) -> str | None:
        c = self._conn()
        if c is None:
            return None
        val = c.get(f"{_PREFIX}{share_id}")
        return str(val) if val is not None else None

    def release(self, share_id: str, task_id: str) -> bool:
        """Release lock if held by task_id. Returns True if released."""
        c = self._conn()
        if c is None:
            return True
        key = f"{_PREFIX}{share_id}"
        val = c.get(key)
        if val == task_id:
            c.delete(key)
            return True
        return False

    def force_release(self, share_id: str) -> None:
        """Force release a lock regardless of holder (timeout cleanup)."""
        c = self._conn()
        if c is None:
            return
        c.delete(f"{_PREFIX}{share_id}")
