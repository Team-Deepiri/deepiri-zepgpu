"""GPU and system metrics collection."""

from __future__ import annotations

import asyncio
import psutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False


@dataclass
class SystemMetrics:
    """System-level metrics."""
    cpu_percent: float
    memory_used_gb: float
    memory_total_gb: float
    memory_percent: float
    disk_used_gb: float
    disk_total_gb: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class GPUMetrics:
    """GPU-specific metrics."""
    device_id: int
    name: str
    utilization_percent: float
    memory_used_mb: float
    memory_total_mb: float
    memory_percent: float
    temperature_celsius: float
    power_watts: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TaskMetrics:
    """Per-task metrics."""
    task_id: str
    gpu_device_id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    execution_time_seconds: float = 0.0
    peak_gpu_memory_mb: float = 0.0
    avg_gpu_utilization: float = 0.0
    status: str = "running"


class MetricsCollector:
    """Collects and stores system and GPU metrics."""

    def __init__(
        self,
        collect_interval: float = 5.0,
        history_size: int = 1000,
    ):
        self._collect_interval = collect_interval
        self._history_size = history_size

        self._system_metrics: list[SystemMetrics] = []
        self._gpu_metrics: list[GPUMetrics] = []
        self._task_metrics: dict[str, TaskMetrics] = {}

        self._lock = threading.RLock()
        self._collecting = False
        self._collect_task: Optional[asyncio.Task] = None
        self._nvml_initialized = False

        if PYNVML_AVAILABLE:
            try:
                pynvml.nvmlInit()
                self._nvml_initialized = True
            except Exception:
                pass

    async def start(self) -> None:
        """Start metrics collection."""
        if self._collecting:
            return
        self._collecting = True
        self._collect_task = asyncio.create_task(self._collect_loop())

    async def stop(self) -> None:
        """Stop metrics collection."""
        self._collecting = False
        if self._collect_task:
            self._collect_task.cancel()
            try:
                await self._collect_task
            except asyncio.CancelledError:
                pass
        if self._nvml_initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    async def _collect_loop(self) -> None:
        """Main collection loop."""
        while self._collecting:
            try:
                await self._collect_system_metrics()
                await self._collect_gpu_metrics()
            except Exception:
                pass
            await asyncio.sleep(self._collect_interval)

    async def _collect_system_metrics(self) -> None:
        """Collect system metrics."""
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        metrics = SystemMetrics(
            cpu_percent=cpu_percent,
            memory_used_gb=memory.used / (1024**3),
            memory_total_gb=memory.total / (1024**3),
            memory_percent=memory.percent,
            disk_used_gb=disk.used / (1024**3),
            disk_total_gb=disk.total / (1024**3),
        )

        with self._lock:
            self._system_metrics.append(metrics)
            if len(self._system_metrics) > self._history_size:
                self._system_metrics.pop(0)

    async def _collect_gpu_metrics(self) -> None:
        """Collect GPU metrics."""
        if not self._nvml_initialized:
            return

        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle) or f"GPU-{i}"

                memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)

                try:
                    temperature = pynvml.nvmlDeviceGetTemperature(
                        handle, pynvml.NVML_TEMPERATURE_GPU
                    )
                except Exception:
                    temperature = 0

                try:
                    power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                except Exception:
                    power = 0.0

                metrics = GPUMetrics(
                    device_id=i,
                    name=name,
                    utilization_percent=utilization.gpu,
                    memory_used_mb=memory_info.used / (1024**2),
                    memory_total_mb=memory_info.total / (1024**2),
                    memory_percent=(memory_info.used / memory_info.total * 100) if memory_info.total > 0 else 0,
                    temperature_celsius=temperature,
                    power_watts=power,
                )

                with self._lock:
                    self._gpu_metrics.append(metrics)
                    if len(self._gpu_metrics) > self._history_size:
                        self._gpu_metrics = [m for m in self._gpu_metrics if m.device_id != i]
                        self._gpu_metrics.append(metrics)

        except Exception:
            pass

    def record_task_start(self, task_id: str, gpu_device_id: int) -> None:
        """Record task start."""
        with self._lock:
            self._task_metrics[task_id] = TaskMetrics(
                task_id=task_id,
                gpu_device_id=gpu_device_id,
                start_time=datetime.utcnow(),
            )

    def record_task_end(
        self,
        task_id: str,
        status: str,
        peak_memory_mb: float = 0.0,
        avg_utilization: float = 0.0,
    ) -> None:
        """Record task end."""
        with self._lock:
            if task_id in self._task_metrics:
                metrics = self._task_metrics[task_id]
                metrics.end_time = datetime.utcnow()
                metrics.execution_time_seconds = (
                    metrics.end_time - metrics.start_time
                ).total_seconds()
                metrics.peak_gpu_memory_mb = peak_memory_mb
                metrics.avg_gpu_utilization = avg_utilization
                metrics.status = status

    def get_system_metrics(self, limit: int = 100) -> list[SystemMetrics]:
        """Get recent system metrics."""
        with self._lock:
            return list(self._system_metrics[-limit:])

    def get_gpu_metrics(self, device_id: Optional[int] = None, limit: int = 100) -> list[GPUMetrics]:
        """Get recent GPU metrics."""
        with self._lock:
            if device_id is not None:
                return [m for m in self._gpu_metrics if m.device_id == device_id][-limit:]
            return list(self._gpu_metrics[-limit:])

    def get_task_metrics(self, task_id: Optional[str] = None) -> dict[str, TaskMetrics]:
        """Get task metrics."""
        with self._lock:
            if task_id:
                return {task_id: self._task_metrics[task_id]} if task_id in self._task_metrics else {}
            return dict(self._task_metrics)

    def get_summary(self) -> dict:
        """Get metrics summary."""
        with self._lock:
            recent_system = self._system_metrics[-10:] if self._system_metrics else []
            recent_gpu = self._gpu_metrics[-10:] if self._gpu_metrics else []

            return {
                "system": {
                    "cpu_percent_avg": sum(m.cpu_percent for m in recent_system) / len(recent_system) if recent_system else 0,
                    "memory_percent_avg": sum(m.memory_percent for m in recent_system) / len(recent_system) if recent_system else 0,
                },
                "gpu": {
                    "device_count": len(set(m.device_id for m in recent_gpu)) if recent_gpu else 0,
                    "utilization_avg": sum(m.utilization_percent for m in recent_gpu) / len(recent_gpu) if recent_gpu else 0,
                    "memory_percent_avg": sum(m.memory_percent for m in recent_gpu) / len(recent_gpu) if recent_gpu else 0,
                },
                "tasks": {
                    "total_tracked": len(self._task_metrics),
                    "completed": len([t for t in self._task_metrics.values() if t.status == "completed"]),
                    "running": len([t for t in self._task_metrics.values() if t.status == "running"]),
                },
            }
