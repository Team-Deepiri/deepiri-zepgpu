"""GPU Device model."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Column, DateTime, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from deepiri_zepgpu.database.models.task import Task


class GPUState(str, enum.Enum):
    """GPU availability state."""
    IDLE = "idle"
    ALLOCATED = "allocated"
    RESERVED = "reserved"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


class GPUType(str, enum.Enum):
    """GPU vendor/type."""
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    CPU = "cpu"


class GPUDevice(Base):
    """GPU device model."""
    
    __tablename__ = "gpu_devices"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    device_index: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    uuid: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    gpu_type: Mapped[GPUType] = mapped_column(
        Enum(GPUType),
        default=GPUType.NVIDIA,
        nullable=False,
    )
    
    vendor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    driver_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cuda_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    
    total_memory_mb: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    available_memory_mb: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    
    compute_capability_major: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compute_capability_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    max_cuda_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_multiprocessors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    state: Mapped[GPUState] = mapped_column(
        Enum(GPUState),
        default=GPUState.IDLE,
        nullable=False,
        index=True,
    )
    
    current_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    utilization_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_utilization_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    
    temperature_celsius: Mapped[int | None] = mapped_column(Integer, nullable=True)
    power_draw_watts: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_limit_watts: Mapped[float | None] = mapped_column(Float, nullable=True)
    
    fan_speed_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    clock_speed_mhz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_clock_mhz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    pci_bus_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pci_device_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    is_available: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_monitored: Mapped[bool] = mapped_column(default=True, nullable=False)
    
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    
    @property
    def compute_capability(self) -> str | None:
        """Get compute capability as string."""
        if self.compute_capability_major and self.compute_capability_minor:
            return f"{self.compute_capability_major}.{self.compute_capability_minor}"
        return None

    @property
    def memory_usage_percent(self) -> float | None:
        """Get memory usage percentage."""
        if self.total_memory_mb and self.available_memory_mb is not None:
            used = self.total_memory_mb - self.available_memory_mb
            return (used / self.total_memory_mb) * 100
        return None

    def __repr__(self) -> str:
        return f"<GPUDevice(id={self.id}, index={self.device_index}, name={self.name})>"
