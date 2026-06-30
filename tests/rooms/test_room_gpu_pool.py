"""Tests for room node GPU listing behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server.routes import rooms


class FakeNetworkRepository:
    def __init__(self, _db: object, room: object | None = None) -> None:
        self.room = room

    async def get_by_id(self, _room_id: str) -> object | None:
        return self.room

    async def list_user_networks(self, _user_id: str) -> list[object]:
        if self.room is None:
            return []
        return [self.room]


class FakePeerRepository:
    def __init__(self, _db: object, peer: object | None = None) -> None:
        self.peer = peer

    async def get_by_id(self, _peer_id: str) -> object | None:
        return self.peer


class FakeGpuShareRepository:
    def __init__(self, _db: object, shares: list[object] | None = None) -> None:
        self.shares = shares or []

    async def list_by_peer(self, _peer_id: str) -> list[object]:
        return self.shares


def _make_room(room_id: object) -> SimpleNamespace:
    return SimpleNamespace(id=room_id)


def _make_peer(
    *,
    peer_id: object,
    room_id: object,
    user_id: object,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=peer_id,
        vpn_network_id=room_id,
        user_id=user_id,
    )


def _make_gpu_share(
    *,
    peer_id: object,
    room_id: object,
    device_index: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        peer_id=peer_id,
        vpn_network_id=room_id,
        device_index=device_index,
        name="NVIDIA RTX 4090",
        total_memory_mb=24576,
        available_memory_mb=18000,
        compute_capability="8.9",
        gpu_type="nvidia",
        state=SimpleNamespace(value="idle"),
        utilization_percent=12.5,
        is_active=True,
        last_updated=datetime.now(UTC),
    )


def test_list_room_node_gpus_returns_only_room_scoped_shares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    room_id = uuid4()
    other_room_id = uuid4()
    peer_id = uuid4()

    room = _make_room(room_id)
    peer = _make_peer(peer_id=peer_id, room_id=room_id, user_id=user_id)
    room_share = _make_gpu_share(peer_id=peer_id, room_id=room_id)
    other_room_share = _make_gpu_share(
        peer_id=peer_id,
        room_id=other_room_id,
        device_index=1,
    )

    monkeypatch.setattr(
        rooms,
        "VpnNetworkRepository",
        lambda db: FakeNetworkRepository(db, room=room),
    )
    monkeypatch.setattr(
        rooms,
        "PeerRepository",
        lambda db: FakePeerRepository(db, peer=peer),
    )
    monkeypatch.setattr(
        rooms,
        "GpuShareRepository",
        lambda db: FakeGpuShareRepository(db, shares=[room_share, other_room_share]),
    )

    response = asyncio.run(
        rooms.list_room_node_gpus(
            room_id=str(room_id),
            peer_id=str(peer_id),
            user=SimpleNamespace(id=user_id),
            db=object(),
        )
    )

    assert len(response) == 1
    assert response[0].peer_id == peer_id
    assert response[0].room_id == room_id
    assert response[0].device_index == 0
    assert response[0].name == "NVIDIA RTX 4090"
    assert response[0].available_memory_mb == 18000
    assert response[0].state == "idle"


def test_list_room_node_gpus_rejects_peer_from_another_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    room_id = uuid4()
    other_room_id = uuid4()
    peer_id = uuid4()

    room = _make_room(room_id)
    peer = _make_peer(peer_id=peer_id, room_id=other_room_id, user_id=user_id)

    monkeypatch.setattr(
        rooms,
        "VpnNetworkRepository",
        lambda db: FakeNetworkRepository(db, room=room),
    )
    monkeypatch.setattr(
        rooms,
        "PeerRepository",
        lambda db: FakePeerRepository(db, peer=peer),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            rooms.list_room_node_gpus(
                room_id=str(room_id),
                peer_id=str(peer_id),
                user=SimpleNamespace(id=user_id),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Node not found"
