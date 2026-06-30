"""Tests for node agent GPU reporter."""

from __future__ import annotations

from unittest.mock import patch

from deepiri_zepgpu.node_agent.gpu_reporter import collect_gpu_status
from deepiri_zepgpu.vpn.peer_node import GpuInfo


def test_simulation_mode_produces_stable_payload() -> None:
    gpus = collect_gpu_status(simulation_mode=True)
    assert len(gpus) == 2
    assert gpus[0]["device_index"] == 0
    assert gpus[0]["name"] == "Simulated GPU 0"
    assert gpus[0]["total_memory_mb"] == 24576
    assert gpus[0]["gpu_type"] == "nvidia"
    assert gpus[0]["state"] == "idle"


@patch("deepiri_zepgpu.node_agent.gpu_reporter.discover_local_gpus", return_value=[])
def test_no_nvml_returns_empty_list(_mock_discover: object) -> None:
    assert collect_gpu_status(simulation_mode=False) == []


@patch(
    "deepiri_zepgpu.node_agent.gpu_reporter.discover_local_gpus",
    return_value=[
        GpuInfo(
            device_index=0,
            name="NVIDIA RTX 4090",
            total_memory_mb=24576,
            available_memory_mb=18000,
            compute_capability="8.9",
            utilization_percent=12.5,
        )
    ],
)
def test_nvml_gpu_maps_to_heartbeat_fields(_mock_discover: object) -> None:
    gpus = collect_gpu_status(simulation_mode=False)
    assert gpus[0]["device_index"] == 0
    assert gpus[0]["compute_capability"] == "8.9"
    assert gpus[0]["utilization_percent"] == 12.5
