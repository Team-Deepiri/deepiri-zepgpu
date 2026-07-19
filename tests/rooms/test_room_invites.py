"""Tests for room invite and join behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server.routes import rooms
from deepiri_zepgpu.rooms.models import RoomJoinRequest


class FakeInviteRepository:
    last_instance: FakeInviteRepository | None = None

    def __init__(self, _db: object, invite: object | None = None) -> None:
        self.invite = invite
        self.used_invite = None
        FakeInviteRepository.last_instance = self

    async def get_by_code(self, _code: str) -> object | None:
        return self.invite

    async def use(self, invite: object) -> None:
        self.used_invite = invite


class FakeNetworkRepository:
    def __init__(self, _db: object, room: object | None = None) -> None:
        self.room = room

    async def get_by_id(self, _room_id: str) -> object | None:
        return self.room


class FakePeerRepository:
    last_instance: FakePeerRepository | None = None

    def __init__(self, _db: object, existing_peer: object | None = None) -> None:
        self.existing_peer = existing_peer
        self.created_peer = None
        FakePeerRepository.last_instance = self

    async def get_by_network(self, _room_id: str) -> list[object]:
        if self.existing_peer is None:
            return []
        return [self.existing_peer]

    async def create(
        self,
        user_id: str,
        vpn_network_id: str,
        wireguard_public_key: str,
        vpn_ip: str,
        private_key_encrypted: str,
        is_gpu_host: bool,
    ) -> object:
        self.created_peer = SimpleNamespace(
            id=uuid4(),
            user_id=user_id,
            vpn_network_id=vpn_network_id,
            wireguard_public_key=wireguard_public_key,
            vpn_ip=vpn_ip,
            private_key_encrypted=private_key_encrypted,
            is_gpu_host=is_gpu_host,
            online_status=SimpleNamespace(value="offline"),
            created_at=datetime.now(UTC),
            last_seen=None,
            user=None,
        )
        return self.created_peer


def _make_invite(**overrides: object) -> SimpleNamespace:
    invite = SimpleNamespace(
        id=uuid4(),
        vpn_network_id=uuid4(),
        code="ABC123",
        creator_id=uuid4(),
        is_revoked=False,
        used_count=0,
        max_uses=1,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        created_at=datetime.now(UTC),
    )

    for key, value in overrides.items():
        setattr(invite, key, value)

    return invite


def _make_room(room_id: object, host_id: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=room_id,
        name="Test Room",
        cidr="10.42.0.0/24",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=None,
        relay_public_key="relay-public-key",
        relay_endpoint="127.0.0.1",
        listen_port=51820,
        host_id=host_id,
    )


def test_join_room_returns_404_when_invite_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rooms,
        "VpnInviteRepository",
        lambda db: FakeInviteRepository(db, invite=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rooms.join_room(
                data=RoomJoinRequest(invite_code="missing"),
                user=SimpleNamespace(id=uuid4()),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Invite not found"


def test_join_room_rejects_revoked_invite(monkeypatch: pytest.MonkeyPatch) -> None:
    invite = _make_invite(is_revoked=True)
    monkeypatch.setattr(
        rooms,
        "VpnInviteRepository",
        lambda db: FakeInviteRepository(db, invite=invite),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rooms.join_room(
                data=RoomJoinRequest(invite_code="ABC123"),
                user=SimpleNamespace(id=uuid4()),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == "Invite has been revoked"


def test_join_room_rejects_maxed_out_invite(monkeypatch: pytest.MonkeyPatch) -> None:
    invite = _make_invite(used_count=1, max_uses=1)
    monkeypatch.setattr(
        rooms,
        "VpnInviteRepository",
        lambda db: FakeInviteRepository(db, invite=invite),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rooms.join_room(
                data=RoomJoinRequest(invite_code="ABC123"),
                user=SimpleNamespace(id=uuid4()),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == "Invite usage limit reached"


def test_join_room_rejects_expired_invite(monkeypatch: pytest.MonkeyPatch) -> None:
    invite = _make_invite(expires_at=datetime.now(UTC) - timedelta(days=1))
    monkeypatch.setattr(
        rooms,
        "VpnInviteRepository",
        lambda db: FakeInviteRepository(db, invite=invite),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rooms.join_room(
                data=RoomJoinRequest(invite_code="ABC123"),
                user=SimpleNamespace(id=uuid4()),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail == "Invite has expired"


def test_join_room_rejects_duplicate_join(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid4()
    room_id = uuid4()
    invite = _make_invite(vpn_network_id=room_id)
    room = _make_room(room_id)
    existing_peer = SimpleNamespace(user_id=user_id)

    monkeypatch.setattr(
        rooms,
        "VpnInviteRepository",
        lambda db: FakeInviteRepository(db, invite=invite),
    )
    monkeypatch.setattr(
        rooms,
        "VpnNetworkRepository",
        lambda db: FakeNetworkRepository(db, room=room),
    )
    monkeypatch.setattr(
        rooms,
        "PeerRepository",
        lambda db: FakePeerRepository(db, existing_peer=existing_peer),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rooms.join_room(
                data=RoomJoinRequest(invite_code="ABC123"),
                user=SimpleNamespace(id=user_id),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "User has already joined this room"


def test_join_room_success_creates_peer_and_uses_invite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    room_id = uuid4()
    invite = _make_invite(vpn_network_id=room_id, max_uses=3)
    room = _make_room(room_id)

    monkeypatch.setattr(
        rooms,
        "VpnInviteRepository",
        lambda db: FakeInviteRepository(db, invite=invite),
    )
    monkeypatch.setattr(
        rooms,
        "VpnNetworkRepository",
        lambda db: FakeNetworkRepository(db, room=room),
    )
    monkeypatch.setattr(
        rooms,
        "PeerRepository",
        lambda db: FakePeerRepository(db, existing_peer=None),
    )
    monkeypatch.setattr(rooms, "generate_keypair", lambda: ("private-key", "public-key"))
    monkeypatch.setattr(rooms, "encrypt_value", lambda value: f"encrypted-{value}")

    response = asyncio.run(
        rooms.join_room(
            data=RoomJoinRequest(invite_code="ABC123"),
            user=SimpleNamespace(id=user_id),
            db=object(),
        )
    )

    assert response.room.id == room_id
    assert response.member.user_id == user_id
    assert response.member.status == "disconnected"
    assert response.config_available is True

    assert FakeInviteRepository.last_instance is not None
    assert FakeInviteRepository.last_instance.used_invite == invite

    assert FakePeerRepository.last_instance is not None
    assert FakePeerRepository.last_instance.created_peer is not None
    assert FakePeerRepository.last_instance.created_peer.wireguard_public_key == "public-key"
    assert (
        FakePeerRepository.last_instance.created_peer.private_key_encrypted
        == "encrypted-private-key"
    )


class FakeConfigNetworkRepository:
    def __init__(self, _db: object, room: object | None = None) -> None:
        self.room = room

    async def get_by_id(self, _room_id: str) -> object | None:
        return self.room

    async def list_user_networks(self, _user_id: str) -> list[object]:
        if self.room is None:
            return []
        return [self.room]


class FakeConfigPeerRepository:
    def __init__(
        self,
        _db: object,
        peer: object | None = None,
        private_key: str | None = "private-key",
    ) -> None:
        self.peer = peer
        self.private_key = private_key

    async def get_by_network(self, _room_id: str) -> list[object]:
        if self.peer is None:
            return []
        return [self.peer]

    async def get_private_key(self, _peer: object) -> str | None:
        return self.private_key


def test_get_room_config_returns_current_user_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    room_id = uuid4()
    room = _make_room(room_id)
    peer = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        vpn_ip="10.42.0.2",
    )

    monkeypatch.setattr(
        rooms,
        "VpnNetworkRepository",
        lambda db: FakeConfigNetworkRepository(db, room=room),
    )
    monkeypatch.setattr(
        rooms,
        "PeerRepository",
        lambda db: FakeConfigPeerRepository(db, peer=peer, private_key="private-key"),
    )
    monkeypatch.setattr(
        rooms,
        "generate_peer_config",
        lambda **kwargs: "generated-config",
    )

    response = asyncio.run(
        rooms.get_room_config(
            room_id=str(room_id),
            user=SimpleNamespace(id=user_id),
            db=object(),
        )
    )

    assert response.room_id == room_id
    assert response.peer_id == peer.id
    assert response.config == "generated-config"
    assert response.filename == f"room-{room_id}-peer-{peer.id}.conf"


def test_get_room_config_fails_when_user_has_no_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    room_id = uuid4()
    room = _make_room(room_id)

    monkeypatch.setattr(
        rooms,
        "VpnNetworkRepository",
        lambda db: FakeConfigNetworkRepository(db, room=room),
    )
    monkeypatch.setattr(
        rooms,
        "PeerRepository",
        lambda db: FakeConfigPeerRepository(db, peer=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rooms.get_room_config(
                room_id=str(room_id),
                user=SimpleNamespace(id=user_id),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Room config is not available yet"


def test_get_room_config_fails_when_private_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    room_id = uuid4()
    room = _make_room(room_id)
    peer = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        vpn_ip="10.42.0.2",
    )

    monkeypatch.setattr(
        rooms,
        "VpnNetworkRepository",
        lambda db: FakeConfigNetworkRepository(db, room=room),
    )
    monkeypatch.setattr(
        rooms,
        "PeerRepository",
        lambda db: FakeConfigPeerRepository(db, peer=peer, private_key=None),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rooms.get_room_config(
                room_id=str(room_id),
                user=SimpleNamespace(id=user_id),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Room config is not available yet"
