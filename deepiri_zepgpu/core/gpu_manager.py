"""GPU abstraction and management layer."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from deepiri_gpu_utils import GpuBackend, discover_gpus
from deepiri_gpu_utils import GpuDevice as HostGpuDevice


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
    MPS = "mps"
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
    current_task_id: str | None = None
    utilization_percent: float = 0.0
    temperature_celsius: float = 0.0
    power_draw_watts: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))

    def can_allocate(self, required_memory_mb: int) -> bool:
        """Check if GPU can allocate requested memory."""
        return self.state == GPUState.IDLE and self.available_memory_mb >= required_memory_mb

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
    ) -> None:
        self._devices: dict[int, GPUDevice] = {}
        self._lock = threading.RLock()
        # Keep the historical argument name as part of the public constructor. It now
        # controls canonical host discovery rather than ZepGPU-owned NVML probing.
        self._enable_hardware_discovery = enable_nvml
        self._memory_overhead_mb = memory_overhead_mb
        self._reserve_memory_mb = reserve_memory_mb
        self._monitoring_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        """Initialize GPU manager and discover devices."""
        if not self._enable_hardware_discovery:
            await self._initialize_simulation_mode()
            return

        try:
            await self._discover_devices()
        except Exception:
            # Canonical discovery contains its own vendor-tool error handling, but
            # preserve the manager's historical simulation fallback for any
            # unexpected adapter or import failure too.
            await self._initialize_simulation_mode()
            return
        if not self._devices:
            await self._initialize_simulation_mode()

    async def _discover_devices(self) -> None:
        """Adapt canonical host inventory into ZepGPU's allocation model."""
        # Initial vendor discovery has the same bounded subprocess timeouts as
        # refresh, so keep it off the asyncio event loop as well.
        inventory = await asyncio.to_thread(discover_gpus)
        self._devices = {
            device_id: self._from_host_device(host_device, device_id=device_id)
            for device_id, host_device in self._indexed_host_devices(inventory.devices)
        }

    @staticmethod
    def _indexed_host_devices(
        devices: tuple[HostGpuDevice, ...],
    ) -> list[tuple[int, HostGpuDevice]]:
        """Return stable unique IDs while honoring vendor-provided indices."""
        indexed: list[tuple[int, HostGpuDevice]] = []
        used: set[int] = set()
        for fallback_id, device in enumerate(devices):
            device_id = device.index if device.index is not None else fallback_id
            while device_id in used:
                device_id += 1
            used.add(device_id)
            indexed.append((device_id, device))
        return indexed

    def _from_host_device(self, device: HostGpuDevice, *, device_id: int) -> GPUDevice:
        total_mb = device.memory.total_mib or 0
        compute_capability = self._parse_compute_capability(device.compute_capability)
        gpu_type = {
            GpuBackend.CUDA: GPUType.NVIDIA,
            GpuBackend.ROCM: GPUType.AMD,
            GpuBackend.MPS: GPUType.MPS,
        }.get(device.backend, GPUType.CPU)
        max_cores = device.metadata.get("max_cuda_cores", 0)
        if not isinstance(max_cores, int) or isinstance(max_cores, bool):
            max_cores = 0
        return GPUDevice(
            device_id=device_id,
            name=device.name or f"GPU-{device_id}",
            gpu_type=gpu_type,
            total_memory_mb=total_mb,
            # Preserve ZepGPU's reservation policy. Live free memory is applied by
            # the monitoring pass once a device is allocated.
            available_memory_mb=total_mb - self._reserve_memory_mb,
            compute_capability=compute_capability,
            max_cuda_cores=max_cores,
            utilization_percent=device.utilization_percent or 0.0,
            temperature_celsius=device.temperature_c or 0.0,
            power_draw_watts=device.power_watts or 0.0,
        )

    @staticmethod
    def _parse_compute_capability(value: str | None) -> tuple[int, int]:
        if not value:
            return (0, 0)
        try:
            major, minor = value.split(".", maxsplit=1)
            return (int(major), int(minor))
        except (TypeError, ValueError):
            return (0, 0)

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

        async def monitor_loop() -> None:
            while True:
                await self._update_gpu_metrics()
                await asyncio.sleep(interval_seconds)

        self._monitoring_task = asyncio.create_task(monitor_loop())

    async def stop_monitoring(self) -> None:
        """Stop GPU monitoring."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitoring_task
            self._monitoring_task = None

    async def _update_gpu_metrics(self) -> None:
        """Update GPU metrics from hardware."""
        if not self._enable_hardware_discovery:
            return

        try:
            inventory = await asyncio.to_thread(discover_gpus)
        except Exception:
            # A transient probe failure must not terminate the monitoring task or
            # mutate allocation/reservation state.
            return
        host_devices = dict(self._indexed_host_devices(inventory.devices))
        with self._lock:
            for device_id, device in self._devices.items():
                if device.state == GPUState.ALLOCATED:
                    host_device = host_devices.get(device_id)
                    if host_device is None:
                        continue
                    if host_device.memory.free_mib is not None:
                        device.available_memory_mb = (
                            host_device.memory.free_mib - self._memory_overhead_mb
                        )
                    if host_device.utilization_percent is not None:
                        device.utilization_percent = host_device.utilization_percent
                    if host_device.temperature_c is not None:
                        device.temperature_celsius = host_device.temperature_c
                    if host_device.power_watts is not None:
                        device.power_draw_watts = host_device.power_watts
                    device.last_updated = datetime.now(UTC)

    def get_available_device(
        self,
        required_memory_mb: int = 1024,
        gpu_type: str | None = None,
    ) -> GPUDevice | None:
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

    def get_device(self, device_id: int) -> GPUDevice | None:
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
