"""Redis-backed room membership cache for WebSocket auth.

L2 store shared across API workers so reconnects and cross-worker join/leave
do not require a DB round-trip on every ``/ws/rooms`` connect. Fail-open when
Redis is unavailable (same posture as ``RemoteGpuLock``).
"""

from __future__ import annotations

import json
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore

from deepiri_zepgpu.config import settings

_PREFIX = "zepgpu:ws:user_rooms:"
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

    def _conn(self) -> Any | None:
        if self._client is not None:
            return self._client
        if redis is None:
            return None
        try:
            self._client = redis.Redis.from_url(self._url, decode_responses=True)
            return self._client
        except Exception:
            return None

    @staticmethod
    def _key(user_id: str) -> str:
        return f"{_PREFIX}{user_id}"

    def get_rooms(self, user_id: str) -> set[str] | None:
        """Return cached rooms if the key exists; ``None`` on miss or Redis down."""
        c = self._conn()
        if c is None:
            return None
        try:
            raw = c.get(self._key(user_id))
            if raw is None:
                return None
            data = json.loads(raw)
            if not isinstance(data, list):
                return None
            return {str(v) for v in data}
        except Exception:
            return None

    def contains(self, user_id: str, room_id: str) -> bool:
        rooms = self.get_rooms(user_id)
        if rooms is None:
            return False
        return room_id in rooms

    def replace(self, user_id: str, room_ids: set[str]) -> None:
        """Overwrite the user's membership set (write-through after DB load)."""
        c = self._conn()
        if c is None:
            return
        try:
            payload = json.dumps(sorted(room_ids))
            c.set(self._key(user_id), payload, ex=self._ttl_seconds)
        except Exception:
            return

    def add(self, user_id: str, room_id: str) -> None:
        rooms = self.get_rooms(user_id)
        if rooms is None:
            rooms = set()
        rooms.add(room_id)
        self.replace(user_id, rooms)

    def remove(self, user_id: str, room_id: str) -> None:
        rooms = self.get_rooms(user_id)
        if rooms is None:
            return
        if room_id not in rooms:
            return
        rooms.discard(room_id)
        self.replace(user_id, rooms)
