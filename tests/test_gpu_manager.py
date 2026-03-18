"""Tests for GPU manager module."""

import asyncio
import pytest

from deepiri_zepgpu.core.gpu_manager import GPUManager, GPUState


@pytest.fixture
async def gpu_manager():
    """Create a test GPU manager."""
    manager = GPUManager(enable_nvml=False)
    await manager.initialize()
    yield manager
    manager.shutdown()


class TestGPUManager:
    """Test cases for GPUManager."""

    @pytest.mark.asyncio
    async def test_initialize(self, gpu_manager):
        """Test GPU manager initialization."""
        devices = gpu_manager.list_devices()
        assert len(devices) > 0

    @pytest.mark.asyncio
    async def test_get_available_device(self, gpu_manager):
        """Test finding available device."""
        device = gpu_manager.get_available_device(required_memory_mb=1024)
        assert device is not None
        assert device.state == GPUState.IDLE

    @pytest.mark.asyncio
    async def test_allocate_device(self, gpu_manager):
        """Test device allocation."""
        device = gpu_manager.get_available_device()
        assert device is not None

        result = gpu_manager.allocate_device(device.device_id, "test_task")
        assert result is True

        device = gpu_manager.get_device(device.device_id)
        assert device.state == GPUState.ALLOCATED
        assert device.current_task_id == "test_task"

    @pytest.mark.asyncio
    async def test_release_device(self, gpu_manager):
        """Test device release."""
        device = gpu_manager.get_available_device()
        gpu_manager.allocate_device(device.device_id, "test_task")

        gpu_manager.release_device(device.device_id)
        device = gpu_manager.get_device(device.device_id)
        assert device.state == GPUState.IDLE
        assert device.current_task_id is None

    @pytest.mark.asyncio
    async def test_can_allocate(self, gpu_manager):
        """Test allocation check."""
        device = gpu_manager.get_available_device()
        assert device.can_allocate(1024) is True

        gpu_manager.allocate_device(device.device_id, "test_task")
        assert device.can_allocate(1024) is False

    @pytest.mark.asyncio
    async def test_get_device_stats(self, gpu_manager):
        """Test getting device statistics."""
        total_memory = gpu_manager.get_total_memory_mb()
        assert total_memory > 0

        available_memory = gpu_manager.get_available_memory_mb()
        assert available_memory > 0
