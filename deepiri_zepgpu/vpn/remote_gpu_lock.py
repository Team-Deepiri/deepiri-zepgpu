"""Redis-backed locks for remote GPU share allocation (relay)."""

from __future__ import annotations

from typing import Optional

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore

from deepiri_zepgpu.config import settings

_PREFIX = "zepgpu:vpn:gpu_share:"


class RemoteGpuLock:
    """Best-effort distributed lock per gpu_share id."""

    def __init__(self, url: Optional[str] = None):
        self._url = url or settings.redis.url
        self._client: Optional["redis.Redis"] = None

    def _conn(self) -> Optional["redis.Redis"]:
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

    def release(self, share_id: str, task_id: str) -> None:
        c = self._conn()
        if c is None:
            return
        key = f"{_PREFIX}{share_id}"
        val = c.get(key)
        if val == task_id:
            c.delete(key)
