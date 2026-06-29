"""Tests for room node heartbeat behavior."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server.routes import rooms
from deepiri_zepgpu.rooms.models import RoomNodeHeartbeatRequest


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
    last_instance: FakePeerRepository | None = None

    def __init__(self, _db: object, peer: object | None = None) -> None:
        self.peer = peer
        self.heartbeat_calls: list[dict[str, object]] = []
        FakePeerRepository.last_instance = self

    async def get_by_id(self, _peer_id: str) -> object | None:
        return self.peer

    async def heartbeat(
        self,
        peer_id: str,
        is_online: bool = True,
        endpoint: str | None = None,
        mark_gpu_host: bool | None = None,
    ) -> object | None:
        self.heartbeat_calls.append(
            {
                "peer_id": peer_id,
                "is_online": is_online,
                "endpoint": endpoint,
                "mark_gpu_host": mark_gpu_host,
            }
        )
        if self.peer is None:
            return None

        self.peer.last_seen = datetime.now(UTC)
        self.peer.endpoint = endpoint
        self.peer.is_gpu_host = bool(mark_gpu_host)
        self.peer.online_status = SimpleNamespace(value="online" if is_online else "offline")
        return self.peer


class FakeGpuShareRepository:
    last_instance: FakeGpuShareRepository | None = None

    def __init__(self, _db: object) -> None:
        self.upsert_calls: list[dict[str, object]] = []
        FakeGpuShareRepository.last_instance = self

    async def upsert(
        self,
        peer_id: str,
        vpn_network_id: str,
        gpu_data: dict,
    ) -> object:
        self.upsert_calls.append(
            {
                "peer_id": peer_id,
                "vpn_network_id": vpn_network_id,
                "gpu_data": gpu_data,
            }
        )
        return SimpleNamespace(
            id=uuid4(),
            peer_id=peer_id,
            vpn_network_id=vpn_network_id,
            **gpu_data,
        )


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
        user=SimpleNamespace(username="kapill"),
        vpn_ip="10.8.0.2",
        online_status=SimpleNamespace(value="offline"),
        is_gpu_host=False,
        last_seen=datetime.now(UTC),
        gpu_shares=[],
    )


def test_room_node_heartbeat_updates_peer_and_upserts_gpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    room_id = uuid4()
    peer_id = uuid4()
    room = _make_room(room_id)
    peer = _make_peer(peer_id=peer_id, room_id=room_id, user_id=user_id)

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
        lambda db: FakeGpuShareRepository(db),
    )

    response = asyncio.run(
        rooms.room_node_heartbeat(
            room_id=str(room_id),
            peer_id=str(peer_id),
            data=RoomNodeHeartbeatRequest(
                is_online=True,
                endpoint="192.168.1.25:51820",
                gpu_status=[
                    {
                        "device_index": 0,
                        "name": "NVIDIA RTX 4090",
                        "total_memory_mb": 24576,
                        "available_memory_mb": 18000,
                        "compute_capability": "8.9",
                        "gpu_type": "nvidia",
                        "state": "idle",
                        "utilization_percent": 12.5,
                    }
                ],
            ),
            user=SimpleNamespace(id=user_id),
            db=object(),
        )
    )

    peer_repo = FakePeerRepository.last_instance
    gpu_repo = FakeGpuShareRepository.last_instance

    assert peer_repo is not None
    assert gpu_repo is not None
    assert peer_repo.heartbeat_calls == [
        {
            "peer_id": str(peer_id),
            "is_online": True,
            "endpoint": "192.168.1.25:51820",
            "mark_gpu_host": True,
        }
    ]
    assert len(gpu_repo.upsert_calls) == 1
    assert gpu_repo.upsert_calls[0]["peer_id"] == str(peer_id)
    assert gpu_repo.upsert_calls[0]["vpn_network_id"] == str(room_id)
    assert gpu_repo.upsert_calls[0]["gpu_data"]["device_index"] == 0
    assert gpu_repo.upsert_calls[0]["gpu_data"]["available_memory_mb"] == 18000

    assert response.id == peer_id
    assert response.room_id == room_id
    assert response.status == "connected"
    assert response.is_gpu_host is True


def test_room_node_heartbeat_rejects_peer_from_another_room(
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
            rooms.room_node_heartbeat(
                room_id=str(room_id),
                peer_id=str(peer_id),
                data=RoomNodeHeartbeatRequest(),
                user=SimpleNamespace(id=user_id),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Node not found"


def test_room_node_heartbeat_rejects_updating_another_users_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    other_user_id = uuid4()
    room_id = uuid4()
    peer_id = uuid4()
    room = _make_room(room_id)
    peer = _make_peer(peer_id=peer_id, room_id=room_id, user_id=other_user_id)

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
            rooms.room_node_heartbeat(
                room_id=str(room_id),
                peer_id=str(peer_id),
                data=RoomNodeHeartbeatRequest(),
                user=SimpleNamespace(id=user_id),
                db=object(),
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "You cannot update this node"
