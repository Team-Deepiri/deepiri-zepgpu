"""Tests for leaving a room through the room-facing API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server.routes import rooms
from deepiri_zepgpu.database.models.vpn_models import PeerOnlineStatus


class FakeNetworkRepository:
    def __init__(self, _db: object, room: object, is_member: bool = True) -> None:
        self.room = room
        self.is_member = is_member

    async def get_by_id(self, _room_id: str) -> object:
        return self.room

    async def list_user_networks(self, _user_id: str) -> list[object]:
        return [self.room] if self.is_member else []


class FakePeerRepository:
    def __init__(self, _db: object, peer: object) -> None:
        self.peer = peer
        self.deleted_peer_ids: list[str] = []

    async def get_by_network(self, _room_id: str) -> list[object]:
        return [self.peer]

    async def delete(self, peer_id: str) -> bool:
        self.deleted_peer_ids.append(peer_id)
        return True


class FakeGpuShareRepository:
    def __init__(self, _db: object) -> None:
        self.deactivated_peer_ids: list[str] = []

    async def deactivate_peer_gpus(self, peer_id: str) -> int:
        self.deactivated_peer_ids.append(peer_id)
        return 1


def _make_peer(*, room_id: object, user_id: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        vpn_network_id=room_id,
        user=SimpleNamespace(username="room-member", email="member@example.com"),
        online_status=PeerOnlineStatus.ONLINE,
        last_seen=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


def test_leave_room_deletes_peer_emits_event_and_unsubscribes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id = uuid4()
    user_id = uuid4()
    host_id = uuid4()
    room = SimpleNamespace(id=room_id, host_id=host_id)
    peer = _make_peer(room_id=room_id, user_id=user_id)
    peer_repo = FakePeerRepository(object(), peer)
    gpu_repo = FakeGpuShareRepository(object())
    emit_event = AsyncMock()
    unsubscribe_user = AsyncMock()

    monkeypatch.setattr(
        rooms,
        "VpnNetworkRepository",
        lambda db: FakeNetworkRepository(db, room),
    )
    monkeypatch.setattr(rooms, "PeerRepository", lambda _db: peer_repo)
    monkeypatch.setattr(rooms, "GpuShareRepository", lambda _db: gpu_repo)
    monkeypatch.setattr(rooms, "emit_room_event", emit_event)
    monkeypatch.setattr(rooms.manager, "unsubscribe_user_from_room", unsubscribe_user)

    response = asyncio.run(
        rooms.leave_room(
            room_id=str(room_id),
            user=SimpleNamespace(id=user_id),
            db=object(),
        )
    )

    assert response.status_code == 204
    assert gpu_repo.deactivated_peer_ids == [str(peer.id)]
    assert peer_repo.deleted_peer_ids == [str(peer.id)]
    emit_event.assert_awaited_once()
    assert emit_event.await_args.args[0] == str(room_id)
    assert emit_event.await_args.args[1] == "room_member_left"
    assert emit_event.await_args.args[2]["id"] == str(peer.id)
    unsubscribe_user.assert_awaited_once_with(str(user_id), str(room_id))


def test_room_host_cannot_leave(monkeypatch: pytest.MonkeyPatch) -> None:
    room_id = uuid4()
    user_id = uuid4()
    room = SimpleNamespace(id=room_id, host_id=user_id)
    peer = _make_peer(room_id=room_id, user_id=user_id)
    peer_repo = FakePeerRepository(object(), peer)
    emit_event = AsyncMock()

    monkeypatch.setattr(
        rooms,
        "VpnNetworkRepository",
        lambda db: FakeNetworkRepository(db, room),
    )
    monkeypatch.setattr(rooms, "PeerRepository", lambda _db: peer_repo)
    monkeypatch.setattr(rooms, "emit_room_event", emit_event)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rooms.leave_room(
                room_id=str(room_id),
                user=SimpleNamespace(id=user_id),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 409
    assert "host cannot leave" in exc_info.value.detail
    assert peer_repo.deleted_peer_ids == []
    emit_event.assert_not_awaited()
