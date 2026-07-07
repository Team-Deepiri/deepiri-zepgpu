"""GPU pool aggregator - integrates remote GPUs from VPN peers into the scheduler."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from deepiri_zepgpu.core.gpu_manager import GPUDevice, GPUManager, GPUState, GPUType

if TYPE_CHECKING:
    from deepiri_zepgpu.vpn.remote_gpu_lock import RemoteGpuLock


@dataclass
class RemoteGPUDevice:
    """Wraps a remote peer's GPU as a local GPU device."""

    peer_id: str
    peer_username: str
    share_id: str
    device_index: int
    name: str
    gpu_type: GPUType
    total_memory_mb: int
    available_memory_mb: int
    compute_capability: tuple[int, int]
    state: GPUState = GPUState.IDLE
    current_task_id: str | None = None
    utilization_percent: float = 0.0
    temperature_celsius: float = 0.0
    power_draw_watts: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    vpn_ip: str = ""
    vpn_network_id: str = ""

    @property
    def device_id(self) -> int:
        """Synthetic device id for scheduler compatibility (stable per share)."""
        return abs(hash(self.share_id)) % 1_000_000

    def can_allocate(self, required_memory_mb: int) -> bool:
        return self.state == GPUState.IDLE and self.available_memory_mb >= required_memory_mb

    def allocate(self, task_id: str) -> bool:
        if self.state != GPUState.IDLE:
            return False
        self.state = GPUState.ALLOCATED
        self.current_task_id = task_id
        return True

    def release(self) -> None:
        self.state = GPUState.IDLE
        self.current_task_id = None

    def to_dict(self) -> dict:
        cc = self.compute_capability
        return {
            "device_id": self.device_id,
            "name": self.name,
            "gpu_type": self.gpu_type.value,
            "total_memory_mb": self.total_memory_mb,
            "available_memory_mb": self.available_memory_mb,
            "compute_capability": f"{cc[0]}.{cc[1]}" if cc else "unknown",
            "state": self.state.value,
            "current_task_id": self.current_task_id,
            "utilization_percent": self.utilization_percent,
            "temperature_celsius": self.temperature_celsius,
            "power_draw_watts": self.power_draw_watts,
            "last_updated": self.last_updated.isoformat(),
            "peer_id": self.peer_id,
            "peer_username": self.peer_username,
            "vpn_ip": self.vpn_ip,
        }


class GpuPoolAggregator:
    """Aggregates local and remote GPUs into a unified pool."""

    def __init__(self, gpu_manager: GPUManager, remote_lock: RemoteGpuLock | None = None) -> None:
        self._local_manager = gpu_manager
        self._remote_devices: dict[str, RemoteGPUDevice] = {}
        self._lock = threading.RLock()
        self._remote_lock = remote_lock

    async def refresh_remote_gpus(self, remote_gpus: list[dict]) -> None:
        """Refresh remote GPU state from relay registry."""
        with self._lock:
            new_map = {}
            for gpu_data in remote_gpus:
                share_id = gpu_data["share_id"]
                cc_str = gpu_data.get("compute_capability", "0.0")
                cc_parts = cc_str.split(".")
                cc = (
                    int(cc_parts[0]) if len(cc_parts) > 0 else 0,
                    int(cc_parts[1]) if len(cc_parts) > 1 else 0,
                )

                device = RemoteGPUDevice(
                    peer_id=gpu_data["peer_id"],
                    peer_username=gpu_data.get("peer_username", "unknown"),
                    share_id=share_id,
                    device_index=gpu_data["device_index"],
                    name=gpu_data.get("name", "Unknown GPU"),
                    gpu_type=GPUType(gpu_data.get("gpu_type", "nvidia")),
                    total_memory_mb=gpu_data["total_memory_mb"],
                    available_memory_mb=gpu_data["available_memory_mb"],
                    compute_capability=cc,
                    state=GPUState(gpu_data.get("state", "idle")),
                    current_task_id=gpu_data.get("current_task_id"),
                    utilization_percent=gpu_data.get("utilization_percent", 0.0),
                    vpn_ip=gpu_data.get("vpn_ip", ""),
                    vpn_network_id=gpu_data.get("vpn_network_id", ""),
                )
                new_map[share_id] = device
            self._remote_devices = new_map

    def get_available_device(
        self,
        required_memory_mb: int = 1024,
        gpu_type: str | None = None,
        room_id: str | None = None,
        remote_only: bool = False,
    ) -> GPUDevice | RemoteGPUDevice | None:
        """Find an available GPU across local + remote, optionally room-scoped."""
        if not remote_only:
            local = self._local_manager.get_available_device(
                required_memory_mb=required_memory_mb,
                gpu_type=gpu_type,
            )
            if local:
                return local

        best_remote: RemoteGPUDevice | None = None
        with self._lock:
            for device in self._remote_devices.values():
                if room_id and device.vpn_network_id != str(room_id):
                    continue
                if gpu_type and device.gpu_type.value != gpu_type:
                    continue
                if not device.can_allocate(required_memory_mb):
                    continue
                if best_remote is None:
                    best_remote = device
                    continue
                if (
                    device.available_memory_mb > best_remote.available_memory_mb
                    or (
                        device.available_memory_mb == best_remote.available_memory_mb
                        and device.utilization_percent < best_remote.utilization_percent
                    )
                ):
                    best_remote = device
        return best_remote

    def allocate_device(
        self,
        device_id: int,
        task_id: str,
        is_remote: bool = False,
        share_id: str | None = None,
    ) -> bool:
        """Allocate a GPU device."""
        if is_remote and share_id:
            with self._lock:
                device = self._remote_devices.get(share_id)
                if not device or not device.can_allocate(0):
                    return False
                if self._remote_lock is not None and not self._remote_lock.acquire(
                    share_id, task_id
                ):
                    return False
                if not device.allocate(task_id):
                    if self._remote_lock is not None:
                        self._remote_lock.release(share_id, task_id)
                    return False
                return True
        else:
            return self._local_manager.allocate_device(device_id, task_id)

    def release_device(
        self,
        device_id: int,
        is_remote: bool = False,
        share_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        """Release a GPU device."""
        if is_remote and share_id:
            tid = task_id
            with self._lock:
                device = self._remote_devices.get(share_id)
                if device:
                    if tid is None:
                        tid = device.current_task_id
                    device.release()
                if self._remote_lock is not None and tid:
                    self._remote_lock.release(share_id, tid)
        else:
            self._local_manager.release_device(device_id)

    def get_device(
        self, device_id: int, is_remote: bool = False, share_id: str | None = None
    ) -> GPUDevice | RemoteGPUDevice | None:
        if is_remote and share_id:
            with self._lock:
                return self._remote_devices.get(share_id)
        return self._local_manager.get_device(device_id)

    def list_devices(self) -> list[GPUDevice | RemoteGPUDevice]:
        """List all available devices (local + remote)."""
        with self._lock:
            remote = list(self._remote_devices.values())
        return self._local_manager.list_devices() + remote

    def get_total_memory_mb(self) -> int:
        with self._lock:
            remote_total = sum(d.total_memory_mb for d in self._remote_devices.values())
        return self._local_manager.get_total_memory_mb() + remote_total

    def get_available_memory_mb(self) -> int:
        with self._lock:
            remote_available = sum(d.available_memory_mb for d in self._remote_devices.values())
        return self._local_manager.get_available_memory_mb() + remote_available

    def get_remote_vpn_ip(self, share_id: str) -> str | None:
        with self._lock:
            device = self._remote_devices.get(share_id)
            return device.vpn_ip if device else None
