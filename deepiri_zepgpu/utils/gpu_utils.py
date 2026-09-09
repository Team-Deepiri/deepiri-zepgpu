"""Backward-compatible GPU helpers backed by :mod:`deepiri_gpu_utils`.

The public functions in this module predate the shared package and remain as
compatibility wrappers for ZepGPU callers. Host detection, normalized inventory,
runtime capability probing, and driver metadata come from deepiri-gpu-utils.
Torch execution controls remain here because they operate on ZepGPU's process.
"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
from typing import Any

from deepiri_gpu_utils import GpuBackend, discover_gpus, resolve_runtime


def _torch() -> Any | None:
    try:
        return importlib.import_module("torch")
    except Exception:
        return None


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


# Retained for callers that imported these historical flags directly. A broken
# optional torch install is not considered available for execution.
TORCH_AVAILABLE = _torch() is not None
CUPY_AVAILABLE = _module_available("cupy")


def get_gpu_info() -> dict[str, Any]:
    """Return the established ZepGPU GPU-info shape from canonical inventory."""
    try:
        inventory = discover_gpus()
    except Exception:
        return {
            "cuda_available": False,
            "gpu_count": 0,
            "gpus": [],
            "torch_available": TORCH_AVAILABLE,
            "cupy_available": CUPY_AVAILABLE,
        }
    try:
        runtime = resolve_runtime(inventory=inventory)
    except Exception:
        runtime = None
    gpus: list[dict[str, Any]] = []
    for fallback_index, device in enumerate(inventory.devices):
        gpu: dict[str, Any] = {
            "index": device.index if device.index is not None else fallback_index,
            "name": device.name,
            "total_memory": (device.memory.total_mib or 0) * 1024 * 1024,
        }
        if device.memory.free_mib is not None:
            gpu["free_memory"] = device.memory.free_mib * 1024 * 1024
        if device.memory.used_mib is not None:
            gpu["used_memory"] = device.memory.used_mib * 1024 * 1024
        gpus.append(gpu)

    return {
        # Historical name: torch's ROCm build also exposes its GPU through the
        # cuda API, so preserve True for either torch CUDA or ROCm usability.
        "cuda_available": (
            (
                runtime.cuda_usable
                or runtime.rocm_usable
                or (
                    not runtime.torch_installed
                    and inventory.backend in (GpuBackend.CUDA, GpuBackend.ROCM)
                )
            )
            if runtime is not None
            else inventory.backend in (GpuBackend.CUDA, GpuBackend.ROCM)
        ),
        "gpu_count": inventory.count,
        "gpus": gpus,
        "torch_available": runtime.torch_usable if runtime is not None else TORCH_AVAILABLE,
        "cupy_available": CUPY_AVAILABLE,
    }


def get_gpu_memory_info(device_id: int = 0) -> dict[str, int]:
    """Get process-specific torch memory info for a GPU."""
    torch = _torch()
    if torch is not None and torch.cuda.is_available():
        torch.cuda.set_device(device_id)
        total = torch.cuda.get_device_properties(device_id).total_memory
        allocated = torch.cuda.memory_allocated(device_id)
        return {
            "total": total,
            "allocated": allocated,
            "cached": torch.cuda.memory_reserved(device_id),
            "free": total - allocated,
        }
    return {"total": 0, "allocated": 0, "cached": 0, "free": 0}


def format_memory(bytes: int) -> str:
    """Format memory size in bytes to the legacy human-readable form."""
    value = float(bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024.0:
            return f"{value:.2f}{unit}"
        value /= 1024.0
    return f"{value:.2f}PB"


def check_cuda_version() -> str | None:
    """Return CUDA runtime/toolchain version with legacy ``nvcc`` compatibility."""
    try:
        version = resolve_runtime().cuda_version
    except Exception:
        version = None
    if version is not None:
        return str(version)
    # RuntimeCapabilities intentionally describes the loaded runtime. Preserve the
    # older wrapper's toolchain-only result when torch is absent but nvcc exists.
    try:
        result = subprocess.run(
            ["nvcc", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if "release" in line:
                return line.strip().split("release")[-1].strip()
    return None


def check_nvidia_driver() -> str | None:
    """Return the normalized NVIDIA driver version when available."""
    try:
        inventory = discover_gpus()
    except Exception:
        return None
    return next(
        (
            device.driver_version
            for device in inventory.devices
            if device.backend == GpuBackend.CUDA and device.driver_version
        ),
        None,
    )


def set_gpu_device(device_id: int) -> bool:
    """Set the current torch GPU device."""
    torch = _torch()
    if torch is not None and torch.cuda.is_available():
        torch.cuda.set_device(device_id)
        return True
    return False


def clear_gpu_cache() -> None:
    """Clear the current process's torch GPU cache."""
    torch = _torch()
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def synchronize_gpu() -> None:
    """Synchronize GPU operations in the current torch process."""
    torch = _torch()
    if torch is not None and torch.cuda.is_available():
        torch.cuda.synchronize()


class GPUContext:
    """Context manager preserving ZepGPU's current-device behavior."""

    def __init__(self, device_id: int = 0):
        self._device_id = device_id
        self._previous_device: int | None = None
        self._torch: Any | None = None

    def __enter__(self) -> GPUContext:
        self._torch = _torch()
        if self._torch is not None and self._torch.cuda.is_available():
            self._previous_device = self._torch.cuda.current_device()
            self._torch.cuda.set_device(self._device_id)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._previous_device is not None and self._torch is not None:
            self._torch.cuda.set_device(self._previous_device)
            self._previous_device = None


def detect_gpu_architecture() -> str | None:
    """Map canonical CUDA compute capability to the historical family label."""
    try:
        inventory = discover_gpus()
    except Exception:
        return None
    capability = next(
        (
            device.compute_capability
            for device in inventory.devices
            if device.backend == GpuBackend.CUDA and device.compute_capability
        ),
        None,
    )
    if capability is None:
        return None
    try:
        major_text, minor_text = capability.split(".", maxsplit=1)
        major, minor = int(major_text), int(minor_text)
    except (TypeError, ValueError):
        return None
    arch_map = {
        (3, 0): "Kepler",
        (3, 5): "Kepler",
        (5, 0): "Maxwell",
        (5, 2): "Maxwell",
        (6, 0): "Pascal",
        (6, 1): "Pascal",
        (7, 0): "Volta",
        (7, 5): "Turing",
        (8, 0): "Ampere",
        (8, 6): "Ampere",
        (8, 9): "Ada",
        (9, 0): "Hopper",
    }
    return arch_map.get((major, minor), f"Unknown-{major}.{minor}")
