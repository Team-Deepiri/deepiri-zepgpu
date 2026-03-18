"""GPU detection and utility functions."""

from __future__ import annotations

import os
import subprocess
from typing import Any, Optional

try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    import cupy as cp
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False


def get_gpu_info() -> dict[str, Any]:
    """Get information about available GPUs."""
    info = {
        "cuda_available": False,
        "gpu_count": 0,
        "gpus": [],
        "torch_available": TORCH_AVAILABLE,
        "cupy_available": CUPY_AVAILABLE,
    }

    if TORCH_AVAILABLE:
        info["cuda_available"] = torch.cuda.is_available()
        if info["cuda_available"]:
            info["gpu_count"] = torch.cuda.device_count()
            for i in range(info["gpu_count"]):
                gpu_info = {
                    "index": i,
                    "name": torch.cuda.get_device_name(i),
                    "total_memory": torch.cuda.get_device_properties(i).total_memory,
                }
                info["gpus"].append(gpu_info)

    elif PYNVML_AVAILABLE:
        try:
            pynvml.nvmlInit()
            info["gpu_count"] = pynvml.nvmlDeviceGetCount()
            info["cuda_available"] = True

            for i in range(info["gpu_count"]):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)

                gpu_info = {
                    "index": i,
                    "name": pynvml.nvmlDeviceGetName(handle),
                    "total_memory": memory.total,
                    "free_memory": memory.free,
                    "used_memory": memory.used,
                }
                info["gpus"].append(gpu_info)

            pynvml.nvmlShutdown()
        except Exception:
            pass

    return info


def get_gpu_memory_info(device_id: int = 0) -> dict[str, int]:
    """Get memory info for a specific GPU."""
    if TORCH_AVAILABLE and torch.cuda.is_available():
        torch.cuda.set_device(device_id)
        return {
            "total": torch.cuda.get_device_properties(device_id).total_memory,
            "allocated": torch.cuda.memory_allocated(device_id),
            "cached": torch.cuda.memory_reserved(device_id),
            "free": torch.cuda.get_device_properties(device_id).total_memory - torch.cuda.memory_allocated(device_id),
        }

    return {"total": 0, "allocated": 0, "cached": 0, "free": 0}


def format_memory(bytes: int) -> str:
    """Format memory size in bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes < 1024.0:
            return f"{bytes:.2f}{unit}"
        bytes /= 1024.0
    return f"{bytes:.2f}PB"


def check_cuda_version() -> Optional[str]:
    """Check CUDA version."""
    try:
        result = subprocess.run(
            ["nvcc", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "release" in line:
                    return line.strip().split("release")[-1].strip()
    except FileNotFoundError:
        pass
    return None


def check_nvidia_driver() -> Optional[str]:
    """Check NVIDIA driver version."""
    if not PYNVML_AVAILABLE:
        return None

    try:
        pynvml.nvmlInit()
        driver_version = pynvml.nvmlSystemGetDriverVersion()
        pynvml.nvmlShutdown()
        return driver_version
    except Exception:
        return None


def set_gpu_device(device_id: int) -> bool:
    """Set the current GPU device."""
    if TORCH_AVAILABLE and torch.cuda.is_available():
        torch.cuda.set_device(device_id)
        return True
    return False


def clear_gpu_cache() -> None:
    """Clear GPU cache."""
    if TORCH_AVAILABLE and torch.cuda.is_available():
        torch.cuda.empty_cache()


def synchronize_gpu() -> None:
    """Synchronize all GPU operations."""
    if TORCH_AVAILABLE and torch.cuda.is_available():
        torch.cuda.synchronize()


class GPUContext:
    """Context manager for GPU operations."""

    def __init__(self, device_id: int = 0):
        self._device_id = device_id
        self._previous_device = None

    def __enter__(self) -> "GPUContext":
        if TORCH_AVAILABLE and torch.cuda.is_available():
            self._previous_device = torch.cuda.current_device()
            torch.cuda.set_device(self._device_id)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._previous_device is not None and TORCH_AVAILABLE:
            torch.cuda.set_device(self._previous_device)
            self._previous_device = None


def detect_gpu_architecture() -> Optional[str]:
    """Detect GPU architecture."""
    if not TORCH_AVAILABLE or not torch.cuda.is_available():
        return None

    capability = torch.cuda.get_device_capability()
    major, minor = capability

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
