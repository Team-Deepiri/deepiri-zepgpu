"""Tests for canonical host inventory to peer-protocol adaptation."""

from __future__ import annotations

from unittest.mock import patch

from deepiri_gpu_utils import GpuBackend, GpuDevice, GpuInventory, GpuMemory

from deepiri_zepgpu.vpn.peer_node import discover_local_gpus


def test_nvidia_rocm_and_mps_keep_peer_json_contract() -> None:
    inventory = GpuInventory(
        backend=GpuBackend.CUDA,
        devices=(
            GpuDevice(
                backend=GpuBackend.CUDA,
                index=0,
                name="RTX 4090",
                memory=GpuMemory(total_mib=24576, free_mib=18000),
                compute_capability="8.9",
                utilization_percent=12.5,
            ),
            GpuDevice(
                backend=GpuBackend.ROCM,
                index=1,
                name="MI300X",
                memory=GpuMemory(total_mib=196608, free_mib=190000),
            ),
            GpuDevice(backend=GpuBackend.MPS, index=2, name="Apple MPS"),
        ),
    )
    with patch("deepiri_zepgpu.vpn.peer_node.discover_gpus", return_value=inventory):
        result = discover_local_gpus()

    assert [gpu.gpu_type for gpu in result] == ["nvidia", "amd", "mps"]
    assert result[0].model_dump() == {
        "device_index": 0,
        "name": "RTX 4090",
        "total_memory_mb": 24576,
        "available_memory_mb": 18000,
        "compute_capability": "8.9",
        "gpu_type": "nvidia",
        "state": "idle",
        "utilization_percent": 12.5,
    }
    assert result[2].total_memory_mb == 0
    assert result[2].available_memory_mb == 0


def test_missing_or_malformed_tooling_inventory_is_an_empty_peer_list() -> None:
    inventory = GpuInventory(
        backend=GpuBackend.UNKNOWN,
        warnings=("nvidia-smi inventory queries failed or timed out",),
    )
    with patch("deepiri_zepgpu.vpn.peer_node.discover_gpus", return_value=inventory):
        assert discover_local_gpus() == []


def test_unexpected_probe_failure_is_an_empty_peer_list() -> None:
    with patch("deepiri_zepgpu.vpn.peer_node.discover_gpus", side_effect=OSError("timeout")):
        assert discover_local_gpus() == []
