"""GPU abstraction and management layer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import threading

try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False


class GPUState(Enum):
    """GPU availability state."""
    IDLE = "idle"
    ALLOCATED = "allocated"
    RESERVED = "reserved"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class GPUType(Enum):
    """Supported GPU types."""
    NVIDIA = "nvidia"
    AMD = "amd"
    CPU = "cpu"


@dataclass
class GPUDevice:
    """Represents a GPU device."""
    device_id: int
    name: str
    gpu_type: GPUType = GPUType.NVIDIA
    total_memory_mb: int = 0
    available_memory_mb: int = 0
    compute_capability: tuple[int, int] = (0, 0)
    max_cuda_cores: int = 0
    state: GPUState = GPUState.IDLE
    current_task_id: Optional[str] = None
    utilization_percent: float = 0.0
    temperature_celsius: float = 0.0
    power_draw_watts: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def can_allocate(self, required_memory_mb: int) -> bool:
        """Check if GPU can allocate requested memory."""
        return (
            self.state == GPUState.IDLE and
            self.available_memory_mb >= required_memory_mb
        )

    def allocate(self, task_id: str) -> bool:
        """Allocate GPU to a task."""
        if self.state != GPUState.IDLE:
            return False
        self.state = GPUState.ALLOCATED
        self.current_task_id = task_id
        return True

    def release(self) -> None:
        """Release GPU from current task."""
        self.state = GPUState.IDLE
        self.current_task_id = None

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "gpu_type": self.gpu_type.value,
            "total_memory_mb": self.total_memory_mb,
            "available_memory_mb": self.available_memory_mb,
            "compute_capability": f"{self.compute_capability[0]}.{self.compute_capability[1]}",
            "max_cuda_cores": self.max_cuda_cores,
            "state": self.state.value,
            "current_task_id": self.current_task_id,
            "utilization_percent": self.utilization_percent,
            "temperature_celsius": self.temperature_celsius,
            "power_draw_watts": self.power_draw_watts,
            "last_updated": self.last_updated.isoformat(),
        }


class GPUManager:
    """Manages GPU allocation, monitoring, and health checks."""

    def __init__(
        self,
        enable_nvml: bool = True,
        memory_overhead_mb: int = 512,
        reserve_memory_mb: int = 1024,
    ):
        self._devices: dict[int, GPUDevice] = {}
        self._lock = threading.RLock()
        self._nvml_initialized = False
        self._enable_nvml = enable_nvml and PYNVML_AVAILABLE
        self._memory_overhead_mb = memory_overhead_mb
        self._reserve_memory_mb = reserve_memory_mb
        self._monitoring_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize GPU manager and discover devices."""
        if self._enable_nvml:
            try:
                pynvml.nvmlInit()
                self._nvml_initialized = True
                await self._discover_devices()
            except Exception as e:
                print(f"Failed to initialize NVML: {e}. Falling back to simulation mode.")
                await self._initialize_simulation_mode()
        else:
            await self._initialize_simulation_mode()

    async def _discover_devices(self) -> None:
        """Discover available NVIDIA GPUs."""
        if not self._nvml_initialized:
            return

        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                if name is None:
                    name = f"GPU-{i}"

                memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                total_mb = memory_info.total // (1024 * 1024)

                try:
                    compute_cap = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
                    compute_capability = (compute_cap.major, compute_cap.minor)
                except Exception:
                    compute_capability = (0, 0)

                try:
                    max_cores = pynvml.nvmlDeviceGetMaxCudaConcurrentAtomiccs(handle)
                except Exception:
                    max_cores = 0

                device = GPUDevice(
                    device_id=i,
                    name=name,
                    gpu_type=GPUType.NVIDIA,
                    total_memory_mb=total_mb,
                    available_memory_mb=total_mb - self._reserve_memory_mb,
                    compute_capability=compute_capability,
                    max_cuda_cores=max_cores,
                )
                self._devices[i] = device
        except Exception as e:
            print(f"Error discovering GPUs: {e}")
            await self._initialize_simulation_mode()

    async def _initialize_simulation_mode(self) -> None:
        """Initialize with simulated GPUs for testing/development."""
        self._devices = {
            0: GPUDevice(
                device_id=0,
                name="Simulated A100",
                gpu_type=GPUType.NVIDIA,
                total_memory_mb=40960,
                available_memory_mb=39936,
                compute_capability=(8, 0),
                max_cuda_cores=8192,
            ),
            1: GPUDevice(
                device_id=1,
                name="Simulated A100",
                gpu_type=GPUType.NVIDIA,
                total_memory_mb=40960,
                available_memory_mb=39936,
                compute_capability=(8, 0),
                max_cuda_cores=8192,
            ),
        }

    async def start_monitoring(self, interval_seconds: float = 5.0) -> None:
        """Start continuous GPU monitoring."""
        if self._monitoring_task is not None:
            return

        async def monitor_loop():
            while True:
                await self._update_gpu_metrics()
                await asyncio.sleep(interval_seconds)

        self._monitoring_task = asyncio.create_task(monitor_loop())

    async def stop_monitoring(self) -> None:
        """Stop GPU monitoring."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None

    async def _update_gpu_metrics(self) -> None:
        """Update GPU metrics from hardware."""
        if not self._nvml_initialized:
            return

        with self._lock:
            for device_id, device in self._devices.items():
                if device.state == GPUState.ALLOCATED:
                    try:
                        handle = pynvml.nvmlDeviceGetHandleByIndex(device_id)
                        memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        device.available_memory_mb = (
                            memory_info.free // (1024 * 1024) - self._memory_overhead_mb
                        )
                        device.utilization_percent = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
                        device.temperature_celsius = pynvml.nvmlDeviceGetTemperature(
                            handle, pynvml.NVML_TEMPERATURE_GPU
                        )
                        device.power_draw_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                        device.last_updated = datetime.utcnow()
                    except Exception:
                        pass

    def get_available_device(
        self,
        required_memory_mb: int = 1024,
        gpu_type: Optional[str] = None,
    ) -> Optional[GPUDevice]:
        """Find an available GPU that meets requirements."""
        with self._lock:
            for device in self._devices.values():
                if gpu_type and device.gpu_type.value != gpu_type:
                    continue
                if device.can_allocate(required_memory_mb):
                    return device
            return None

    def allocate_device(self, device_id: int, task_id: str) -> bool:
        """Allocate a specific GPU device to a task."""
        with self._lock:
            device = self._devices.get(device_id)
            if device and device.can_allocate(0):
                device.allocate(task_id)
                return True
            return False

    def release_device(self, device_id: int) -> None:
        """Release a GPU device."""
        with self._lock:
            device = self._devices.get(device_id)
            if device:
                device.release()

    def get_device(self, device_id: int) -> Optional[GPUDevice]:
        """Get device by ID."""
        return self._devices.get(device_id)

    def list_devices(self) -> list[GPUDevice]:
        """List all available devices."""
        return list(self._devices.values())

    def get_total_memory_mb(self) -> int:
        """Get total GPU memory across all devices."""
        return sum(d.total_memory_mb for d in self._devices.values())

    def get_available_memory_mb(self) -> int:
        """Get available GPU memory across all devices."""
        return sum(d.available_memory_mb for d in self._devices.values())

    def shutdown(self) -> None:
        """Shutdown GPU manager and cleanup resources."""
        if self._monitoring_task:
            asyncio.create_task(self.stop_monitoring())
        if self._nvml_initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
