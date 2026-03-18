"""GPU repository for database operations."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.gpu_device import GPUDevice, GPUState


class GPURepository:
    """Repository for GPU Device database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> GPUDevice:
        """Create or update GPU device."""
        device = GPUDevice(**kwargs)
        self.session.add(device)
        await self.session.flush()
        return device

    async def get_by_device_index(self, device_index: int) -> GPUDevice | None:
        """Get GPU by device index."""
        result = await self.session.execute(
            select(GPUDevice).where(GPUDevice.device_index == device_index)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, device_id: int) -> GPUDevice | None:
        """Get GPU by ID."""
        result = await self.session.execute(
            select(GPUDevice).where(GPUDevice.id == device_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[GPUDevice]:
        """List all GPU devices."""
        result = await self.session.execute(
            select(GPUDevice).order_by(GPUDevice.device_index)
        )
        return result.scalars().all()

    async def list_available(self) -> Sequence[GPUDevice]:
        """List available GPU devices."""
        result = await self.session.execute(
            select(GPUDevice)
            .where(
                GPUDevice.state == GPUState.IDLE,
                GPUDevice.is_available == True,
            )
            .order_by(GPUDevice.device_index)
        )
        return result.scalars().all()

    async def update_or_create(
        self,
        device_index: int,
        **kwargs,
    ) -> GPUDevice:
        """Update or create GPU device."""
        device = await self.get_by_device_index(device_index)
        
        if device:
            for key, value in kwargs.items():
                if hasattr(device, key):
                    setattr(device, key, value)
            device.last_seen = datetime.utcnow()
        else:
            device = GPUDevice(
                device_index=device_index,
                last_seen=datetime.utcnow(),
                **kwargs,
            )
            self.session.add(device)
        
        await self.session.flush()
        return device

    async def update_metrics(
        self,
        device_index: int,
        utilization_percent: float | None = None,
        memory_utilization_percent: float | None = None,
        temperature_celsius: int | None = None,
        power_draw_watts: float | None = None,
        available_memory_mb: int | None = None,
    ) -> GPUDevice | None:
        """Update GPU metrics."""
        device = await self.get_by_device_index(device_index)
        if not device:
            return None
        
        if utilization_percent is not None:
            device.utilization_percent = utilization_percent
        if memory_utilization_percent is not None:
            device.memory_utilization_percent = memory_utilization_percent
        if temperature_celsius is not None:
            device.temperature_celsius = temperature_celsius
        if power_draw_watts is not None:
            device.power_draw_watts = power_draw_watts
        if available_memory_mb is not None:
            device.available_memory_mb = available_memory_mb
        
        device.last_seen = datetime.utcnow()
        await self.session.flush()
        return device

    async def allocate(
        self,
        device_index: int,
        task_id: str,
    ) -> GPUDevice | None:
        """Allocate GPU to a task."""
        device = await self.get_by_device_index(device_index)
        if not device or device.state != GPUState.IDLE:
            return None
        
        device.state = GPUState.ALLOCATED
        device.current_task_id = task_id
        await self.session.flush()
        return device

    async def release(self, device_index: int) -> GPUDevice | None:
        """Release GPU from task."""
        device = await self.get_by_device_index(device_index)
        if not device:
            return None
        
        device.state = GPUState.IDLE
        device.current_task_id = None
        await self.session.flush()
        return device

    async def mark_error(self, device_index: int, error: str | None = None) -> GPUDevice | None:
        """Mark GPU as having an error."""
        device = await self.get_by_device_index(device_index)
        if not device:
            return None
        
        device.state = GPUState.ERROR
        device.last_seen = datetime.utcnow()
        await self.session.flush()
        return device

    async def mark_unavailable(self, device_index: int) -> GPUDevice | None:
        """Mark GPU as unavailable."""
        device = await self.get_by_device_index(device_index)
        if not device:
            return None
        
        device.state = GPUState.UNAVAILABLE
        device.is_available = False
        await self.session.flush()
        return device

    async def set_available(self, device_index: int) -> GPUDevice | None:
        """Set GPU as available."""
        device = await self.get_by_device_index(device_index)
        if not device:
            return None
        
        device.state = GPUState.IDLE
        device.is_available = True
        device.current_task_id = None
        await self.session.flush()
        return device

    async def count_available(self) -> int:
        """Count available GPUs."""
        result = await self.session.execute(
            select(func.count(GPUDevice.id)).where(
                GPUDevice.state == GPUState.IDLE,
                GPUDevice.is_available == True,
            )
        )
        return result.scalar() or 0

    async def get_total_memory_mb(self) -> int:
        """Get total GPU memory."""
        result = await self.session.execute(
            select(func.sum(GPUDevice.total_memory_mb))
        )
        return result.scalar() or 0

    async def get_available_memory_mb(self) -> int:
        """Get total available GPU memory."""
        result = await self.session.execute(
            select(func.sum(GPUDevice.available_memory_mb))
        )
        return result.scalar() or 0
