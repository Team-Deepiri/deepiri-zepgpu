"""Local GPU discovery for node agent heartbeat payloads."""

from __future__ import annotations

from typing import Any

from deepiri_zepgpu.vpn.peer_node import GpuInfo, discover_local_gpus

SIMULATED_GPUS: list[dict[str, Any]] = [
    {
        "device_index": 0,
        "name": "Simulated GPU 0",
        "total_memory_mb": 24576,
        "available_memory_mb": 20000,
        "compute_capability": "8.9",
        "gpu_type": "nvidia",
        "state": "idle",
        "utilization_percent": 5.0,
    },
    {
        "device_index": 1,
        "name": "Simulated GPU 1",
        "total_memory_mb": 16384,
        "available_memory_mb": 14000,
        "compute_capability": "8.6",
        "gpu_type": "nvidia",
        "state": "idle",
        "utilization_percent": 2.0,
    },
]


def _gpu_info_to_heartbeat(gpu: GpuInfo) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_index": gpu.device_index,
        "name": gpu.name,
        "total_memory_mb": gpu.total_memory_mb,
        "available_memory_mb": gpu.available_memory_mb,
        "gpu_type": gpu.gpu_type,
        "state": gpu.state,
    }
    if gpu.compute_capability is not None:
        payload["compute_capability"] = gpu.compute_capability
    if gpu.utilization_percent is not None:
        payload["utilization_percent"] = gpu.utilization_percent
    return payload


def collect_gpu_status(*, simulation_mode: bool = False) -> list[dict[str, Any]]:
    """Return gpu_status entries for RoomNodeHeartbeatRequest."""
    if simulation_mode:
        return [dict(entry) for entry in SIMULATED_GPUS]

    gpus = discover_local_gpus()
    return [_gpu_info_to_heartbeat(gpu) for gpu in gpus]
