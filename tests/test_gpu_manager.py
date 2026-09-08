"""Tests for GPU manager module."""

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from deepiri_gpu_utils import GpuBackend, GpuInventory, GpuMemory
from deepiri_gpu_utils import GpuDevice as HostGpuDevice

from deepiri_zepgpu.core.gpu_manager import GPUManager, GPUState, GPUType


@pytest.fixture
async def gpu_manager() -> AsyncGenerator[GPUManager, None]:
    """Create a test GPU manager."""
    manager = GPUManager(enable_nvml=False)
    await manager.initialize()
    yield manager
    manager.shutdown()


class TestGPUManager:
    """Test cases for GPUManager."""

    @pytest.mark.asyncio
    async def test_initialize(self, gpu_manager: GPUManager) -> None:
        """Test GPU manager initialization."""
        devices = gpu_manager.list_devices()
        assert len(devices) > 0

    @pytest.mark.asyncio
    async def test_get_available_device(self, gpu_manager: GPUManager) -> None:
        """Test finding available device."""
        device = gpu_manager.get_available_device(required_memory_mb=1024)
        assert device is not None
        assert device.state == GPUState.IDLE

    @pytest.mark.asyncio
    async def test_allocate_device(self, gpu_manager: GPUManager) -> None:
        """Test device allocation."""
        device = gpu_manager.get_available_device()
        assert device is not None

        result = gpu_manager.allocate_device(device.device_id, "test_task")
        assert result is True

        device = gpu_manager.get_device(device.device_id)
        assert device is not None
        assert device.state == GPUState.ALLOCATED
        assert device.current_task_id == "test_task"

    @pytest.mark.asyncio
    async def test_release_device(self, gpu_manager: GPUManager) -> None:
        """Test device release."""
        device = gpu_manager.get_available_device()
        assert device is not None
        gpu_manager.allocate_device(device.device_id, "test_task")

        gpu_manager.release_device(device.device_id)
        device = gpu_manager.get_device(device.device_id)
        assert device is not None
        assert device.state == GPUState.IDLE
        assert device.current_task_id is None

    @pytest.mark.asyncio
    async def test_can_allocate(self, gpu_manager: GPUManager) -> None:
        """Test allocation check."""
        device = gpu_manager.get_available_device()
        assert device is not None
        assert device.can_allocate(1024) is True

        gpu_manager.allocate_device(device.device_id, "test_task")
        assert device.can_allocate(1024) is False

    @pytest.mark.asyncio
    async def test_get_device_stats(self, gpu_manager: GPUManager) -> None:
        """Test getting device statistics."""
        total_memory = gpu_manager.get_total_memory_mb()
        assert total_memory > 0

        available_memory = gpu_manager.get_available_memory_mb()
        assert available_memory > 0

    @pytest.mark.asyncio
    async def test_canonical_inventory_adapts_without_changing_scheduler_order(self) -> None:
        inventory = GpuInventory(
            backend=GpuBackend.CUDA,
            source="nvidia-smi",
            devices=(
                HostGpuDevice(
                    backend=GpuBackend.CUDA,
                    index=0,
                    name="small-first",
                    memory=GpuMemory(total_mib=8192, free_mib=7000),
                    compute_capability="8.6",
                ),
                HostGpuDevice(
                    backend=GpuBackend.CUDA,
                    index=1,
                    name="large-second",
                    memory=GpuMemory(total_mib=24576, free_mib=22000),
                    compute_capability="8.9",
                ),
            ),
        )
        manager = GPUManager(reserve_memory_mb=1024)
        with patch("deepiri_zepgpu.core.gpu_manager.discover_gpus", return_value=inventory):
            await manager.initialize()

        assert [device.device_id for device in manager.list_devices()] == [0, 1]
        assert manager.get_device(0).available_memory_mb == 7168  # type: ignore[union-attr]
        assert manager.get_device(0).compute_capability == (8, 6)  # type: ignore[union-attr]
        assert manager.get_available_device(required_memory_mb=7000).device_id == 0  # type: ignore[union-attr]
        assert manager.get_available_device(required_memory_mb=8000).device_id == 1  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_rocm_mps_and_malformed_capability_are_safe(self) -> None:
        inventory = GpuInventory(
            backend=GpuBackend.ROCM,
            devices=(
                HostGpuDevice(
                    backend=GpuBackend.ROCM,
                    index=0,
                    name="AMD MI300X",
                    memory=GpuMemory(total_mib=196608),
                    compute_capability="not-cuda",
                ),
                HostGpuDevice(
                    backend=GpuBackend.MPS,
                    index=1,
                    name="Apple MPS",
                    memory=GpuMemory(),
                ),
            ),
        )
        manager = GPUManager()
        with patch("deepiri_zepgpu.core.gpu_manager.discover_gpus", return_value=inventory):
            await manager.initialize()

        assert manager.get_device(0).gpu_type == GPUType.AMD  # type: ignore[union-attr]
        assert manager.get_device(0).compute_capability == (0, 0)  # type: ignore[union-attr]
        assert manager.get_device(1).gpu_type == GPUType.MPS  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_allocated_device_telemetry_refresh_uses_normalized_values(self) -> None:
        initial = GpuInventory(
            backend=GpuBackend.CUDA,
            devices=(
                HostGpuDevice(
                    backend=GpuBackend.CUDA,
                    index=0,
                    memory=GpuMemory(total_mib=10000, free_mib=9000),
                ),
            ),
        )
        refreshed = GpuInventory(
            backend=GpuBackend.CUDA,
            devices=(
                HostGpuDevice(
                    backend=GpuBackend.CUDA,
                    index=0,
                    memory=GpuMemory(total_mib=10000, free_mib=6000),
                    utilization_percent=25.5,
                    temperature_c=61.0,
                    power_watts=210.0,
                ),
            ),
        )
        manager = GPUManager(memory_overhead_mb=512)
        with patch(
            "deepiri_zepgpu.core.gpu_manager.discover_gpus",
            side_effect=[initial, refreshed],
        ):
            await manager.initialize()
            assert manager.allocate_device(0, "task")
            await manager._update_gpu_metrics()

        device = manager.get_device(0)
        assert device is not None
        assert device.available_memory_mb == 5488
        assert device.utilization_percent == 25.5
        assert device.temperature_celsius == 61.0
        assert device.power_draw_watts == 210.0

    @pytest.mark.asyncio
    async def test_missing_vendor_tooling_keeps_simulation_compatibility(self) -> None:
        manager = GPUManager()
        empty = GpuInventory(
            backend=GpuBackend.CPU,
            warnings=("No GPU detected; returning a valid CPU-only inventory",),
        )
        with patch("deepiri_zepgpu.core.gpu_manager.discover_gpus", return_value=empty):
            await manager.initialize()
        assert [device.name for device in manager.list_devices()] == [
            "Simulated A100",
            "Simulated A100",
        ]

    @pytest.mark.asyncio
    async def test_unexpected_discovery_failure_falls_back_to_simulation(self) -> None:
        manager = GPUManager()
        with patch(
            "deepiri_zepgpu.core.gpu_manager.discover_gpus", side_effect=OSError("broken probe")
        ):
            await manager.initialize()
        assert [device.name for device in manager.list_devices()] == [
            "Simulated A100",
            "Simulated A100",
        ]

    @pytest.mark.asyncio
    async def test_refresh_failure_preserves_mutable_allocation_state(self) -> None:
        inventory = GpuInventory(
            backend=GpuBackend.CUDA,
            devices=(
                HostGpuDevice(
                    backend=GpuBackend.CUDA,
                    index=0,
                    memory=GpuMemory(total_mib=10000, free_mib=9000),
                ),
            ),
        )
        manager = GPUManager()
        with patch("deepiri_zepgpu.core.gpu_manager.discover_gpus", return_value=inventory):
            await manager.initialize()
        assert manager.allocate_device(0, "task-1")
        before = manager.get_device(0)
        assert before is not None
        available_before = before.available_memory_mb

        with patch("deepiri_zepgpu.core.gpu_manager.discover_gpus", side_effect=OSError("timeout")):
            await manager._update_gpu_metrics()

        after = manager.get_device(0)
        assert after is before
        assert after.state == GPUState.ALLOCATED
        assert after.current_task_id == "task-1"
        assert after.available_memory_mb == available_before
