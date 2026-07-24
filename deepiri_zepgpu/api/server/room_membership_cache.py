"""Redis-backed room membership cache for WebSocket auth.

L2 store shared across API workers so reconnects and cross-worker join/leave
do not require a DB round-trip on every ``/ws/rooms`` connect. Fail-open when
Redis is unavailable (same posture as ``RemoteGpuLock``).

Uses Redis SETs (``SADD`` / ``SREM`` / ``SISMEMBER``) for O(1) membership checks
instead of rewriting a JSON blob on every grant/revoke.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore

from deepiri_zepgpu.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "zepgpu:ws:user_rooms:"
_EMPTY_MARKER = "__empty__"
_DEFAULT_TTL_SECONDS = 86_400  # 24h; refreshed on write


class RoomMembershipCache:
    """Distributed room-ID set per user for WebSocket membership checks."""

    def __init__(
        self,
        url: str | None = None,
        client: Any | None = None,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._url = url or settings.redis.url
        self._client = client
        self._ttl_seconds = max(60, int(ttl_seconds))
        self._warned_unavailable = False

    def _conn(self) -> Any | None:
        if self._client is not None:
            return self._client
        if redis is None:
            if not self._warned_unavailable:
                logger.warning("RoomMembershipCache: redis package unavailable; fail-open")
                self._warned_unavailable = True
            return None
        try:
            self._client = redis.Redis.from_url(self._url, decode_responses=True)
            return self._client
        except Exception:
            if not self._warned_unavailable:
                logger.warning(
                    "RoomMembershipCache: Redis connect failed; operating fail-open",
                    exc_info=True,
                )
                self._warned_unavailable = True
            return None

    @staticmethod
    def _key(user_id: str) -> str:
        return f"{_PREFIX}{user_id}"

    def get_rooms(self, user_id: str) -> set[str] | None:
        """Return cached rooms if the key exists; ``None`` on miss or Redis down."""
        c = self._conn()
        if c is None:
            return None
        key = self._key(user_id)
        try:
            if not c.exists(key):
                return None
            members = {str(v) for v in (c.smembers(key) or set())}
            members.discard(_EMPTY_MARKER)
            return members
        except Exception:
            return None

    def contains(self, user_id: str, room_id: str) -> bool:
        c = self._conn()
        if c is None:
            return False
        try:
            return bool(c.sismember(self._key(user_id), room_id))
        except Exception:
            return False

    def replace(self, user_id: str, room_ids: set[str]) -> None:
        """Overwrite the user's membership set (write-through after DB load)."""
        c = self._conn()
        if c is None:
            return
        key = self._key(user_id)
        try:
            pipe = c.pipeline()
            pipe.delete(key)
            if room_ids:
                pipe.sadd(key, *sorted(room_ids))
            else:
                # Distinguish "known empty" from cache miss.
                pipe.sadd(key, _EMPTY_MARKER)
            pipe.expire(key, self._ttl_seconds)
            pipe.execute()
        except Exception:
            return

    def add(self, user_id: str, room_id: str) -> None:
        c = self._conn()
        if c is None:
            return
        key = self._key(user_id)
        try:
            pipe = c.pipeline()
            pipe.sadd(key, room_id)
            pipe.srem(key, _EMPTY_MARKER)
            pipe.expire(key, self._ttl_seconds)
            pipe.execute()
        except Exception:
            return

    def remove(self, user_id: str, room_id: str) -> None:
        c = self._conn()
        if c is None:
            return
        key = self._key(user_id)
        try:
            pipe = c.pipeline()
            pipe.srem(key, room_id)
            pipe.expire(key, self._ttl_seconds)
            pipe.execute()
        except Exception:
            return
