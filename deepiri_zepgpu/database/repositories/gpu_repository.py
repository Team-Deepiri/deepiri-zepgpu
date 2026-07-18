"""GPU repository for database operations."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.gpu_device import GPUDevice, GPUState


class GPURepository:
    """Repository for GPU Device database operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> GPUDevice:
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
        result = await self.session.execute(select(GPUDevice).where(GPUDevice.id == device_id))
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[GPUDevice]:
        """List all GPU devices."""
        result = await self.session.execute(select(GPUDevice).order_by(GPUDevice.device_index))
        return result.scalars().all()

    async def list_available(self) -> Sequence[GPUDevice]:
        """List available GPU devices."""
        result = await self.session.execute(
            select(GPUDevice)
            .where(
                GPUDevice.state == GPUState.IDLE,
                GPUDevice.is_available.is_(True),
            )
            .order_by(GPUDevice.device_index)
        )
        return result.scalars().all()

    async def list_available_for_gang(
        self,
        num_gpus: int,
        memory_per_gpu_mb: int,
        gpu_type: str | None = None,
    ) -> Sequence[GPUDevice]:
        """List available GPUs for gang scheduling.

        Args:
            num_gpus: Number of consecutive GPUs needed
            memory_per_gpu_mb: Memory required per GPU
            gpu_type: Optional GPU type filter

        Returns:
            List of consecutive available GPUs that meet requirements
        """
        query = (
            select(GPUDevice)
            .where(
                GPUDevice.state == GPUState.IDLE,
                GPUDevice.is_available.is_(True),
                GPUDevice.available_memory_mb >= memory_per_gpu_mb,
            )
            .order_by(GPUDevice.device_index)
        )

        if gpu_type:
            query = query.where(GPUDevice.gpu_type == gpu_type)

        result = await self.session.execute(query)
        devices = result.scalars().all()

        consecutive = []  # type: ignore[var-annotated]
        for device in devices:
            if len(consecutive) == 0:
                consecutive.append(device)
            else:
                last_idx = consecutive[-1].device_index
                if device.device_index == last_idx + 1:
                    consecutive.append(device)
                else:
                    if len(consecutive) >= num_gpus:
                        break
                    consecutive = [device]

        if len(consecutive) >= num_gpus:
            return consecutive[:num_gpus]
        return []

    async def list_preemptible(self, min_priority: int = 3) -> Sequence[GPUDevice]:
        """List GPUs running tasks that can be preempted.

        Args:
            min_priority: Minimum task priority to consider for preemption

        Returns:
            List of GPUs with preemptible tasks
        """
        result = await self.session.execute(
            select(GPUDevice)
            .where(
                GPUDevice.state == GPUState.ALLOCATED,
                GPUDevice.current_task_id.isnot(None),
            )
            .order_by(GPUDevice.device_index)
        )
        return result.scalars().all()

    async def update_or_create(
        self,
        device_index: int,
        **kwargs: Any,
    ) -> GPUDevice:
        """Update or create GPU device."""
        device = await self.get_by_device_index(device_index)

        if device:
            for key, value in kwargs.items():
                if hasattr(device, key):
                    setattr(device, key, value)
            device.last_seen = datetime.now(UTC)
        else:
            device = GPUDevice(
                device_index=device_index,
                last_seen=datetime.now(UTC),
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

        device.last_seen = datetime.now(UTC)
        await self.session.flush()
        return device

    async def allocate(
        self,
        device_index: int,
        task_id: str,
    ) -> GPUDevice | None:
        """Atomically allocate an idle GPU to a task."""
        result = await self.session.execute(
            update(GPUDevice)
            .where(
                GPUDevice.device_index == device_index,
                GPUDevice.state == GPUState.IDLE,
                GPUDevice.is_available.is_(True),
            )
            .values(
                state=GPUState.ALLOCATED,
                current_task_id=task_id,
                last_seen=datetime.now(UTC),
            )
            .returning(GPUDevice)
        )
        device = result.scalar_one_or_none()
        await self.session.flush()
        return device

    async def allocate_gang(
        self,
        device_indices: list[int],
        gang_task_id: str,
    ) -> list[GPUDevice] | None:
        """Atomically allocate multiple idle GPUs to a gang task."""
        result = await self.session.execute(
            select(GPUDevice)
            .where(
                GPUDevice.device_index.in_(device_indices),
                GPUDevice.state == GPUState.IDLE,
                GPUDevice.is_available.is_(True),
            )
            .with_for_update()
        )
        devices = list(result.scalars().all())

        if len(devices) != len(set(device_indices)):
            return None

        device_by_index = {device.device_index: device for device in devices}
        allocated: list[GPUDevice] = []

        for idx in device_indices:
            device = device_by_index.get(idx)
            if device is None or device.state != GPUState.IDLE:
                return None

            device.state = GPUState.GANG_ALLOCATED
            device.current_task_id = gang_task_id
            allocated.append(device)

        await self.session.flush()
        return allocated

    async def release(self, device_index: int) -> GPUDevice | None:
        """Release GPU from task."""
        device = await self.get_by_device_index(device_index)
        if not device:
            return None

        device.state = GPUState.IDLE
        device.current_task_id = None
        await self.session.flush()
        return device

    async def release_gang(self, gang_task_id: str) -> list[GPUDevice]:
        """Release all GPUs allocated to a gang task.

        Args:
            gang_task_id: The gang task ID to release

        Returns:
            List of released GPU devices
        """
        result = await self.session.execute(
            select(GPUDevice).where(GPUDevice.current_task_id == gang_task_id)
        )
        devices = result.scalars().all()

        released = []
        for device in devices:
            device.state = GPUState.IDLE
            device.current_task_id = None
            released.append(device)

        await self.session.flush()
        return released

    async def mark_preempting(self, device_index: int) -> GPUDevice | None:
        """Mark GPU as being preempted."""
        device = await self.get_by_device_index(device_index)
        if not device:
            return None

        device.state = GPUState.PREEMPTING
        await self.session.flush()
        return device

    async def mark_error(self, device_index: int, error: str | None = None) -> GPUDevice | None:
        """Mark GPU as having an error."""
        device = await self.get_by_device_index(device_index)
        if not device:
            return None

        device.state = GPUState.ERROR
        device.last_seen = datetime.now(UTC)
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
                GPUDevice.is_available.is_(True),
            )
        )
        return result.scalar() or 0

    async def count_available_for_gang(self, num_gpus: int) -> int:
        """Count available consecutive GPU blocks.

        Args:
            num_gpus: Number of consecutive GPUs needed

        Returns:
            Maximum number of gang tasks that can be scheduled
        """
        available = await self.list_available()

        blocks = 0
        consecutive = 0
        for device in available:
            if consecutive == 0:
                consecutive = 1
            else:
                last_idx = available[available.index(device) - 1].device_index
                if device.device_index == last_idx + 1:
                    consecutive += 1
                else:
                    if consecutive >= num_gpus:
                        blocks += 1
                    consecutive = 1

        if consecutive >= num_gpus:
            blocks += 1

        return blocks

    async def get_total_memory_mb(self) -> int:
        """Get total GPU memory."""
        result = await self.session.execute(select(func.sum(GPUDevice.total_memory_mb)))
        return result.scalar() or 0

    async def get_available_memory_mb(self) -> int:
        """Get total available GPU memory."""
        result = await self.session.execute(select(func.sum(GPUDevice.available_memory_mb)))
        return result.scalar() or 0
