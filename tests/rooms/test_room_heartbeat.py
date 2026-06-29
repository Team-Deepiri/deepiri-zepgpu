"""Tests for room node heartbeat request behavior."""

from __future__ import annotations

from deepiri_zepgpu.rooms.models import RoomNodeHeartbeatRequest


def test_room_node_heartbeat_request_accepts_gpu_status_payload() -> None:
    heartbeat = RoomNodeHeartbeatRequest(
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
    )

    assert heartbeat.is_online is True
    assert heartbeat.endpoint == "192.168.1.25:51820"
    assert len(heartbeat.gpu_status) == 1
    assert heartbeat.gpu_status[0].device_index == 0
    assert heartbeat.gpu_status[0].name == "NVIDIA RTX 4090"
    assert heartbeat.gpu_status[0].available_memory_mb == 18000
    assert heartbeat.gpu_status[0].state == "idle"


def test_room_node_heartbeat_request_defaults_to_nvidia_idle_gpu() -> None:
    heartbeat = RoomNodeHeartbeatRequest(
        gpu_status=[
            {
                "device_index": 0,
                "total_memory_mb": 16000,
                "available_memory_mb": 12000,
            }
        ]
    )

    gpu = heartbeat.gpu_status[0]

    assert gpu.gpu_type == "nvidia"
    assert gpu.state == "idle"
    assert gpu.name is None
    assert gpu.compute_capability is None
    assert gpu.utilization_percent is None
