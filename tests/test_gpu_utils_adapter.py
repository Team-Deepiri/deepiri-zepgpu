"""Parity tests for the legacy public GPU utility wrappers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from deepiri_gpu_utils import (
    GpuBackend,
    GpuDevice,
    GpuInventory,
    GpuMemory,
    RuntimeCapabilities,
)

from deepiri_zepgpu.utils import gpu_utils


def _runtime(**updates: object) -> RuntimeCapabilities:
    values = {
        "backend": GpuBackend.CPU,
        "hardware_detected": False,
        "tooling_detected": False,
        "torch_installed": False,
        "torch_usable": False,
        "cuda_usable": False,
        "rocm_usable": False,
        "mps_usable": False,
    }
    values.update(updates)
    return RuntimeCapabilities(**values)  # type: ignore[arg-type]


def test_get_gpu_info_preserves_json_shape_and_byte_units_for_multiple_gpus() -> None:
    inventory = GpuInventory(
        backend=GpuBackend.CUDA,
        source="nvidia-smi",
        devices=(
            GpuDevice(
                backend=GpuBackend.CUDA,
                index=0,
                name="A100",
                memory=GpuMemory(total_mib=40960, free_mib=30000, used_mib=10960),
            ),
            GpuDevice(
                backend=GpuBackend.CUDA,
                index=1,
                name="L4",
                memory=GpuMemory(total_mib=24576, free_mib=20000),
            ),
        ),
    )
    with (
        patch("deepiri_zepgpu.utils.gpu_utils.discover_gpus", return_value=inventory),
        patch(
            "deepiri_zepgpu.utils.gpu_utils.resolve_runtime",
            return_value=_runtime(
                backend=GpuBackend.CUDA,
                hardware_detected=True,
                tooling_detected=True,
                torch_installed=True,
                torch_usable=True,
                cuda_usable=True,
            ),
        ),
    ):
        result = gpu_utils.get_gpu_info()

    assert set(result) == {
        "cuda_available",
        "gpu_count",
        "gpus",
        "torch_available",
        "cupy_available",
    }
    assert result["cuda_available"] is True
    assert result["gpu_count"] == 2
    assert result["gpus"][0] == {
        "index": 0,
        "name": "A100",
        "total_memory": 40960 * 1024 * 1024,
        "free_memory": 30000 * 1024 * 1024,
        "used_memory": 10960 * 1024 * 1024,
    }


def test_cpu_and_broken_torch_report_unavailable_without_raising() -> None:
    inventory = GpuInventory(backend=GpuBackend.CPU)
    with (
        patch("deepiri_zepgpu.utils.gpu_utils.discover_gpus", return_value=inventory),
        patch(
            "deepiri_zepgpu.utils.gpu_utils.resolve_runtime",
            return_value=_runtime(torch_installed=True, warnings=("torch import failed: OSError",)),
        ),
    ):
        result = gpu_utils.get_gpu_info()
    assert result["cuda_available"] is False
    assert result["torch_available"] is False
    assert result["gpu_count"] == 0
    assert result["gpus"] == []


def test_hardware_inventory_preserves_no_torch_nvml_fallback_semantics() -> None:
    inventory = GpuInventory(
        backend=GpuBackend.CUDA,
        devices=(GpuDevice(backend=GpuBackend.CUDA, memory=GpuMemory(total_mib=8192)),),
    )
    with (
        patch("deepiri_zepgpu.utils.gpu_utils.discover_gpus", return_value=inventory),
        patch(
            "deepiri_zepgpu.utils.gpu_utils.resolve_runtime",
            return_value=_runtime(backend=GpuBackend.CUDA, hardware_detected=True),
        ),
    ):
        result = gpu_utils.get_gpu_info()
    assert result["cuda_available"] is True
    assert result["torch_available"] is False


def test_architecture_and_driver_use_canonical_device_fields() -> None:
    inventory = GpuInventory(
        backend=GpuBackend.CUDA,
        devices=(
            GpuDevice(
                backend=GpuBackend.CUDA,
                compute_capability="8.9",
                driver_version="550.54.15",
            ),
        ),
    )
    with patch("deepiri_zepgpu.utils.gpu_utils.discover_gpus", return_value=inventory):
        assert gpu_utils.detect_gpu_architecture() == "Ada"
        assert gpu_utils.check_nvidia_driver() == "550.54.15"


def test_cuda_version_preserves_nvcc_fallback_when_torch_runtime_is_absent() -> None:
    with (
        patch("deepiri_zepgpu.utils.gpu_utils.resolve_runtime", return_value=_runtime()),
        patch(
            "deepiri_zepgpu.utils.gpu_utils.subprocess.run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout="Cuda compilation tools, release 12.4, V12.4.131\n",
            ),
        ),
    ):
        assert gpu_utils.check_cuda_version() == "12.4, V12.4.131"
