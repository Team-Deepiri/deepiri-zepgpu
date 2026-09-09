"""Tests for node agent GPU reporter."""

from __future__ import annotations

from unittest.mock import patch

from deepiri_gpu_utils import (
    GpuBackend,
    GpuDevice,
    GpuInventory,
    GpuMemory,
    RuntimeCapabilities,
)

from deepiri_zepgpu.node_agent.gpu_reporter import (
    _probe_runtime,
    collect_capability_inventory,
    collect_gpu_status,
)
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


def test_runtime_adapter_preserves_heartbeat_shape_for_rocm() -> None:
    inventory = GpuInventory(
        backend=GpuBackend.ROCM,
        source="rocm-smi",
        devices=(
            GpuDevice(
                backend=GpuBackend.ROCM,
                memory=GpuMemory(total_mib=196608),
                driver_version="6.3.0",
            ),
        ),
    )
    capabilities = RuntimeCapabilities(
        backend=GpuBackend.ROCM,
        hardware_detected=True,
        tooling_detected=True,
        torch_installed=True,
        torch_usable=True,
        cuda_usable=False,
        rocm_usable=True,
        mps_usable=False,
        driver_version="6.3.0",
        torch_version="2.4.0+rocm6.3",
        rocm_version="6.3",
    )
    with (
        patch("deepiri_zepgpu.node_agent.gpu_reporter.discover_gpus", return_value=inventory),
        patch("deepiri_zepgpu.node_agent.gpu_reporter.resolve_runtime", return_value=capabilities),
        patch(
            "deepiri_zepgpu.node_agent.gpu_reporter.importlib.import_module", side_effect=OSError
        ),
    ):
        result = _probe_runtime()

    assert set(result) == {
        "compute_capability",
        "driver_version",
        "cuda_version",
        "pytorch_version",
        "container_runtime",
        "nccl_version",
        "fsdp_available",
        "deepspeed_available",
    }
    # Keep the legacy JSON key but do not mislabel ROCm as a CUDA runtime.
    assert result["cuda_version"] is None
    assert result["driver_version"] == "6.3.0"
    assert result["fsdp_available"] is None


def test_capability_inventory_reuses_one_canonical_inventory() -> None:
    inventory = GpuInventory(
        backend=GpuBackend.CUDA,
        source="nvidia-smi",
        devices=(
            GpuDevice(
                backend=GpuBackend.CUDA,
                index=3,
                name="L4",
                memory=GpuMemory(total_mib=24576, free_mib=20000),
                compute_capability="8.9",
            ),
        ),
    )
    capabilities = RuntimeCapabilities(
        backend=GpuBackend.CUDA,
        hardware_detected=True,
        tooling_detected=True,
        torch_installed=False,
        torch_usable=False,
        cuda_usable=False,
        rocm_usable=False,
        mps_usable=False,
    )
    with (
        patch(
            "deepiri_zepgpu.node_agent.gpu_reporter.discover_gpus", return_value=inventory
        ) as discover,
        patch("deepiri_zepgpu.node_agent.gpu_reporter.resolve_runtime", return_value=capabilities),
        patch(
            "deepiri_zepgpu.vpn.peer_node.discover_gpus",
            side_effect=AssertionError("inventory should be reused"),
        ),
        patch(
            "deepiri_zepgpu.node_agent.gpu_reporter.importlib.import_module", side_effect=OSError
        ),
    ):
        result = collect_capability_inventory()

    discover.assert_called_once_with()
    assert result["gpus"] == [
        {
            "device_index": 3,
            "name": "L4",
            "total_memory_mb": 24576,
            "available_memory_mb": 20000,
            "gpu_type": "nvidia",
            "state": "idle",
            "compute_capability": "8.9",
        }
    ]


def test_runtime_probe_failure_preserves_empty_legacy_shape() -> None:
    with (
        patch("deepiri_zepgpu.node_agent.gpu_reporter.discover_gpus", side_effect=OSError),
        patch(
            "deepiri_zepgpu.node_agent.gpu_reporter.importlib.import_module", side_effect=OSError
        ),
    ):
        result = _probe_runtime()
    assert set(result) == {
        "compute_capability",
        "driver_version",
        "cuda_version",
        "pytorch_version",
        "container_runtime",
        "nccl_version",
        "fsdp_available",
        "deepspeed_available",
    }
    assert result["cuda_version"] is None
    assert result["driver_version"] is None
