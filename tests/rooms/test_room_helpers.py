"""Tests for room route helper functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server.routes.rooms import (
    _expires_at_to_days,
    _gpu_share_to_room_node_gpu_response,
    _peer_status_to_room_status,
    _peer_to_room_node_response,
)


def test_expires_at_to_days_defaults_to_seven_days() -> None:
    assert _expires_at_to_days(None) == 7


def test_expires_at_to_days_rounds_future_expiration_up() -> None:
    expires_at = datetime.now(UTC) + timedelta(hours=25)

    assert _expires_at_to_days(expires_at) == 2


def test_expires_at_to_days_rejects_past_expiration() -> None:
    expires_at = datetime.now(UTC) - timedelta(minutes=1)

    with pytest.raises(HTTPException) as exc_info:
        _expires_at_to_days(expires_at)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invite expiration must be in the future"

def test_peer_status_to_room_status_maps_online_to_connected() -> None:
    peer = SimpleNamespace(online_status=SimpleNamespace(value="online"))

    assert _peer_status_to_room_status(peer) == "connected"


def test_peer_status_to_room_status_maps_offline_to_disconnected() -> None:
    peer = SimpleNamespace(online_status=SimpleNamespace(value="offline"))

    assert _peer_status_to_room_status(peer) == "disconnected"


def test_peer_status_to_room_status_maps_awol_to_awol() -> None:
    peer = SimpleNamespace(online_status=SimpleNamespace(value="awol"))

    assert _peer_status_to_room_status(peer) == "awol"


def test_gpu_share_to_room_node_gpu_response_maps_share_fields() -> None:
    now = datetime.now(UTC)
    share = SimpleNamespace(
        id=uuid4(),
        peer_id=uuid4(),
        vpn_network_id=uuid4(),
        device_index=0,
        name="NVIDIA RTX 4090",
        total_memory_mb=24576,
        available_memory_mb=18000,
        compute_capability="8.9",
        gpu_type="nvidia",
        state=SimpleNamespace(value="idle"),
        utilization_percent=12.5,
        is_active=True,
        last_updated=now,
    )

    response = _gpu_share_to_room_node_gpu_response(share)

    assert response.device_index == 0
    assert response.name == "NVIDIA RTX 4090"
    assert response.state == "idle"
    assert response.available_memory_mb == 18000
    assert response.last_updated == now


def test_peer_to_room_node_response_summarizes_active_gpu_shares() -> None:
    room_id = uuid4()
    peer_id = uuid4()
    user_id = uuid4()
    now = datetime.now(UTC)

    active_idle_share = SimpleNamespace(
        is_active=True,
        state=SimpleNamespace(value="idle"),
        total_memory_mb=16000,
        available_memory_mb=12000,
    )
    inactive_share = SimpleNamespace(
        is_active=False,
        state=SimpleNamespace(value="idle"),
        total_memory_mb=8000,
        available_memory_mb=8000,
    )
    peer = SimpleNamespace(
        id=peer_id,
        vpn_network_id=room_id,
        user_id=user_id,
        user=SimpleNamespace(username="kapill"),
        vpn_ip="10.8.0.2",
        online_status=SimpleNamespace(value="online"),
        is_gpu_host=True,
        last_seen=now,
        gpu_shares=[active_idle_share, inactive_share],
    )

    response = _peer_to_room_node_response(peer)

    assert response.id == peer_id
    assert response.room_id == room_id
    assert response.user_id == user_id
    assert response.username == "kapill"
    assert response.status == "connected"
    assert response.is_online is True
    assert response.gpu_count == 1
    assert response.available_gpu_count == 1
    assert response.total_memory_mb == 16000
    assert response.available_memory_mb == 12000
