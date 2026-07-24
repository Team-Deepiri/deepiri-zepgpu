"""Unit tests for Redis-backed room membership cache."""

from __future__ import annotations

from deepiri_zepgpu.api.server.room_membership_cache import RoomMembershipCache
from tests.rooms.conftest import FakeRedis


def test_replace_get_and_contains_roundtrip() -> None:
    cache = RoomMembershipCache(client=FakeRedis())
    cache.replace("u1", {"room-a", "room-b"})
    assert cache.get_rooms("u1") == {"room-a", "room-b"}
    assert cache.contains("u1", "room-a") is True
    assert cache.contains("u1", "room-z") is False


def test_miss_returns_none() -> None:
    cache = RoomMembershipCache(client=FakeRedis())
    assert cache.get_rooms("missing") is None
    assert cache.contains("missing", "room-a") is False


def test_empty_set_is_not_a_miss() -> None:
    cache = RoomMembershipCache(client=FakeRedis())
    cache.replace("u1", set())
    assert cache.get_rooms("u1") == set()


def test_add_and_remove() -> None:
    cache = RoomMembershipCache(client=FakeRedis())
    cache.replace("u1", {"room-a"})
    cache.add("u1", "room-b")
    assert cache.get_rooms("u1") == {"room-a", "room-b"}
    cache.remove("u1", "room-a")
    assert cache.get_rooms("u1") == {"room-b"}


def test_unavailable_client_fails_open() -> None:
    class Boom:
        def get(self, *_a, **_k):
            raise RuntimeError("down")

        def set(self, *_a, **_k):
            raise RuntimeError("down")

    cache = RoomMembershipCache(client=Boom())
    assert cache.get_rooms("u1") is None
    cache.replace("u1", {"room-a"})  # no raise
    cache.add("u1", "room-a")
    assert cache.contains("u1", "room-a") is False
