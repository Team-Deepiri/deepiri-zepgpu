"""Tests for room mapper helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from deepiri_zepgpu.database.models.vpn_models import GpuShareState
from deepiri_zepgpu.rooms.mappers import (
    gpu_shares_to_room_pool_summary,
    peer_to_room_member_response,
    room_create_to_vpn_network_data,
    vpn_invite_to_room_invite_response,
    vpn_network_to_room_response,
)
from deepiri_zepgpu.rooms.models import RoomCreateRequest


def test_vpn_network_to_room_response_maps_active_network() -> None:
    room_id = uuid4()
    host_id = uuid4()
    created_at = datetime.now(UTC)

    network = SimpleNamespace(
        id=room_id,
        name="Test Room",
        is_active=True,
        created_at=created_at,
        updated_at=None,
        host_id=None,
    )

    response = vpn_network_to_room_response(network, host_id=host_id)

    assert response.id == room_id
    assert response.name == "Test Room"
    assert response.host_id == host_id
    assert response.status == "active"
    assert response.created_at == created_at


def test_vpn_network_to_room_response_uses_network_host_id() -> None:
    room_id = uuid4()
    host_id = uuid4()
    created_at = datetime.now(UTC)

    network = SimpleNamespace(
        id=room_id,
        name="Hosted Room",
        is_active=True,
        created_at=created_at,
        updated_at=None,
        host_id=host_id,
    )

    response = vpn_network_to_room_response(network)

    assert response.host_id == host_id


def test_vpn_network_to_room_response_maps_archived_network() -> None:
    room_id = uuid4()
    created_at = datetime.now(UTC)

    network = SimpleNamespace(
        id=room_id,
        name="Archived Room",
        is_active=False,
        created_at=created_at,
        updated_at=None,
        host_id=None,
    )

    response = vpn_network_to_room_response(network)

    assert response.id == room_id
    assert response.status == "archived"
    assert response.host_id is None


def test_peer_to_room_member_response_uses_user_display_name() -> None:
    peer_id = uuid4()
    user_id = uuid4()
    last_seen = datetime.now(UTC)
    created_at = datetime.now(UTC)

    peer = SimpleNamespace(
        id=peer_id,
        user_id=user_id,
        user=SimpleNamespace(username="kapill", email="kapill@example.com"),
        online_status=SimpleNamespace(value="online"),
        created_at=created_at,
        last_seen=last_seen,
    )

    response = peer_to_room_member_response(peer)

    assert response.id == peer_id
    assert response.user_id == user_id
    assert response.display_name == "kapill"
    assert response.status == "connected"
    assert response.joined_at == created_at
    assert response.last_seen_at == last_seen


def test_gpu_shares_to_room_pool_summary_counts_active_shares() -> None:
    room_id = uuid4()

    shares = [
        SimpleNamespace(
            is_active=True,
            state=GpuShareState.IDLE,
            total_memory_mb=24000,
            available_memory_mb=20000,
            gpu_type="nvidia",
        ),
        SimpleNamespace(
            is_active=True,
            state=GpuShareState.ALLOCATED,
            total_memory_mb=16000,
            available_memory_mb=4000,
            gpu_type="nvidia",
        ),
        SimpleNamespace(
            is_active=False,
            state=GpuShareState.IDLE,
            total_memory_mb=8000,
            available_memory_mb=8000,
            gpu_type="amd",
        ),
    ]

    response = gpu_shares_to_room_pool_summary(room_id, shares)

    assert response.room_id == room_id
    assert response.total_gpus == 2
    assert response.available_gpus == 1
    assert response.allocated_gpus == 1
    assert response.total_memory_mb == 40000
    assert response.available_memory_mb == 20000
    assert response.providers == ["nvidia"]


def test_gpu_shares_to_room_pool_summary_excludes_offline_awol_from_available() -> None:
    room_id = uuid4()

    shares = [
        SimpleNamespace(
            is_active=True,
            state=GpuShareState.IDLE,
            total_memory_mb=24000,
            available_memory_mb=20000,
            gpu_type="nvidia",
            peer=SimpleNamespace(online_status=SimpleNamespace(value="online")),
        ),
        SimpleNamespace(
            is_active=True,
            state=GpuShareState.IDLE,
            total_memory_mb=16000,
            available_memory_mb=12000,
            gpu_type="nvidia",
            peer=SimpleNamespace(online_status=SimpleNamespace(value="offline")),
        ),
        SimpleNamespace(
            is_active=True,
            state=GpuShareState.IDLE,
            total_memory_mb=8000,
            available_memory_mb=6000,
            gpu_type="nvidia",
            peer=SimpleNamespace(online_status=SimpleNamespace(value="awol")),
        ),
    ]

    response = gpu_shares_to_room_pool_summary(room_id, shares)

    assert response.total_gpus == 3
    assert response.available_gpus == 1
    assert response.total_memory_mb == 48000
    assert response.available_memory_mb == 20000


def test_vpn_invite_to_room_invite_response_maps_fields() -> None:
    invite_id = uuid4()
    room_id = uuid4()
    creator_id = uuid4()
    created_at = datetime.now(UTC)
    expires_at = datetime.now(UTC)

    invite = SimpleNamespace(
        id=invite_id,
        vpn_network_id=room_id,
        code="ABC123",
        creator_id=creator_id,
        expires_at=expires_at,
        max_uses=3,
        used_count=1,
        is_revoked=False,
        created_at=created_at,
    )

    response = vpn_invite_to_room_invite_response(invite)

    assert response.id == invite_id
    assert response.room_id == room_id
    assert response.code == "ABC123"
    assert response.created_by == creator_id
    assert response.expires_at == expires_at
    assert response.max_uses == 3
    assert response.use_count == 1
    assert response.is_revoked is False
    assert response.created_at == created_at


def test_room_create_to_vpn_network_data_maps_name_only() -> None:
    request = RoomCreateRequest(name="GPU Room", description="Test description")

    data = room_create_to_vpn_network_data(request)

    assert data == {"name": "GPU Room", "transport_mode": "dialout"}
