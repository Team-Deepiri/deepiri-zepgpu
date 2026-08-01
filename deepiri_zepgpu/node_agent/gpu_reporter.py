"""Local GPU and runtime capability discovery for node agent heartbeats."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from deepiri_zepgpu.vpn.peer_node import GpuInfo, discover_local_gpus

logger = logging.getLogger(__name__)

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
        "temperature_celsius": 42.0,
        "power_watts": 75.0,
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
        "temperature_celsius": 38.0,
        "power_watts": 55.0,
    },
]

SIMULATED_RUNTIME: dict[str, Any] = {
    "compute_capability": "8.9",
    "driver_version": "550.54.15",
    "cuda_version": "12.4",
    "pytorch_version": "2.4.0",
    "container_runtime": "none",
    "nccl_version": "2.21.5",
    "fsdp_available": True,
    "deepspeed_available": False,
}

SIMULATED_TOPOLOGY: dict[str, Any] = {
    "p2p_access": "unavailable",
    "nvlink": "unavailable",
    "pcie_generation": "unavailable",
    "topology_hint": "simulated",
}


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


def _probe_runtime() -> dict[str, Any]:
    runtime: dict[str, Any] = {
        "compute_capability": None,
        "driver_version": None,
        "cuda_version": None,
        "pytorch_version": None,
        "container_runtime": None,
        "nccl_version": None,
        "fsdp_available": None,
        "deepspeed_available": None,
    }
    try:
        import torch

        runtime["pytorch_version"] = getattr(torch, "__version__", None)
        if torch.cuda.is_available():
            runtime["cuda_version"] = getattr(torch.version, "cuda", None)
            with contextlib.suppress(Exception):
                get_driver_version = getattr(torch.cuda, "get_driver_version", None)
                if callable(get_driver_version):
                    runtime["driver_version"] = str(get_driver_version())
            try:
                major, minor = torch.cuda.get_device_capability(0)
                runtime["compute_capability"] = f"{major}.{minor}"
            except Exception:
                pass
            runtime["fsdp_available"] = True
        try:
            import torch.distributed as dist  # noqa: F401

            runtime["nccl_version"] = getattr(torch.cuda.nccl, "version", lambda: None)()
            if callable(runtime["nccl_version"]):
                runtime["nccl_version"] = None
        except Exception:
            pass
    except Exception:
        logger.debug("PyTorch runtime probe unavailable", exc_info=False)

    try:
        import deepspeed

        runtime["deepspeed_available"] = True
        _ = deepspeed
    except Exception:
        runtime["deepspeed_available"] = False

    try:
        from pathlib import Path

        if Path("/.dockerenv").exists():
            runtime["container_runtime"] = "docker"
        else:
            runtime["container_runtime"] = "none"
    except Exception:
        runtime["container_runtime"] = None

    return runtime


def _probe_topology() -> dict[str, Any]:
    # Best-effort; mark unavailable when not detectable.
    return {
        "p2p_access": None,
        "nvlink": None,
        "pcie_generation": None,
        "topology_hint": None,
    }


def collect_capability_inventory(*, simulation_mode: bool = False) -> dict[str, Any]:
    """Return extended capability payload for heartbeat."""

    if simulation_mode:
        return {
            "gpus": [dict(entry) for entry in SIMULATED_GPUS],
            "runtime": dict(SIMULATED_RUNTIME),
            "topology": dict(SIMULATED_TOPOLOGY),
        }

    return {
        "gpus": collect_gpu_status(simulation_mode=False),
        "runtime": _probe_runtime(),
        "topology": _probe_topology(),
    }
