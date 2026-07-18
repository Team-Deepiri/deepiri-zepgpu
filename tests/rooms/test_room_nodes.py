"""Tests for room node schemas and GPU share attachment."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from deepiri_zepgpu.api.server.routes.rooms import _attach_room_gpu_shares
from deepiri_zepgpu.rooms.models import (
    RoomNodeGpuResponse,
    RoomNodeHeartbeatRequest,
    RoomNodeResponse,
)


class FakeGpuShareRepository:
    def __init__(self, shares: list[object]) -> None:
        self._shares = shares

    async def list_by_network(self, _room_id: str, active_only: bool = True) -> list[object]:
        return self._shares


def test_room_node_response_accepts_gpu_summary_fields() -> None:
    node = RoomNodeResponse(
        id=uuid4(),
        room_id=uuid4(),
        user_id=uuid4(),
        username="kapill",
        vpn_ip="10.8.0.2",
        status="connected",
        is_gpu_host=True,
        is_online=True,
        last_seen=datetime.now(UTC),
        gpu_count=2,
        available_gpu_count=1,
        total_memory_mb=24576,
        available_memory_mb=12000,
    )

    assert node.status == "connected"
    assert node.gpu_count == 2
    assert node.available_gpu_count == 1
    assert node.total_memory_mb == 24576
    assert node.available_memory_mb == 12000


def test_room_node_gpu_response_uses_room_facing_ids() -> None:
    gpu = RoomNodeGpuResponse(
        id=uuid4(),
        peer_id=uuid4(),
        room_id=uuid4(),
        device_index=0,
        name="NVIDIA RTX 4090",
        total_memory_mb=24576,
        available_memory_mb=18000,
        compute_capability="8.9",
        gpu_type="nvidia",
        state="idle",
        utilization_percent=12.5,
        is_active=True,
        last_updated=datetime.now(UTC),
    )

    assert gpu.device_index == 0
    assert gpu.name == "NVIDIA RTX 4090"
    assert gpu.state == "idle"
    assert gpu.is_active is True


def test_room_node_heartbeat_request_defaults_to_online_empty_gpu_status() -> None:
    heartbeat = RoomNodeHeartbeatRequest()

    assert heartbeat.is_online is True
    assert heartbeat.endpoint is None
    assert heartbeat.gpu_status == []


@pytest.mark.asyncio
async def test_attach_room_gpu_shares_assigns_per_peer() -> None:
    room_id = str(uuid4())
    peer_a = SimpleNamespace(id=str(uuid4()))
    peer_b = SimpleNamespace(id=str(uuid4()))
    share_a = SimpleNamespace(peer_id=peer_a.id, vpn_network_id=room_id)
    share_b = SimpleNamespace(peer_id=peer_b.id, vpn_network_id=room_id)

    peers = await _attach_room_gpu_shares(
        FakeGpuShareRepository([share_a, share_b]),  # type: ignore[arg-type]
        room_id,
        [peer_a, peer_b],
    )

    assert peers[0]._room_gpu_shares == [share_a]  # type: ignore[attr-defined]
    assert peers[1]._room_gpu_shares == [share_b]  # type: ignore[attr-defined]
