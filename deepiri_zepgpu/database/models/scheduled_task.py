"""Scheduled task model for periodic/cron task execution."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from deepiri_zepgpu.database.models.user import User


class ScheduleType(str, enum.Enum):
    """Schedule type enum."""
    CRON = "cron"
    INTERVAL = "interval"
    ONCE = "once"


class ScheduleStatus(str, enum.Enum):
    """Schedule status enum."""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ScheduledTask(UUIDMixin, TimestampMixin, Base):
    """Periodic/scheduled task model."""
    
    __tablename__ = "scheduled_tasks"
    
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    schedule_type: Mapped[ScheduleType] = mapped_column(
        Enum(ScheduleType),
        default=ScheduleType.CRON,
        nullable=False,
    )
    
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    start_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    status: Mapped[ScheduleStatus] = mapped_column(
        Enum(ScheduleStatus),
        default=ScheduleStatus.ACTIVE,
        nullable=False,
    )
    
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    func_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    serialized_func: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    args: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    kwargs: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    
    priority: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    gpu_memory_mb: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    cpu_cores: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=3600, nullable=False)
    
    gpu_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    allow_fallback_cpu: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    callback_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    user: Mapped["User | None"] = relationship("User", back_populates="scheduled_tasks")
    
    __table_args__ = (
        Index("idx_scheduled_tasks_user_enabled", "user_id", "is_enabled"),
        Index("idx_scheduled_tasks_next_run", "next_run_at", "is_enabled"),
        Index("idx_scheduled_tasks_status", "status"),
    )

    @property
    def is_active(self) -> bool:
        """Check if schedule is active."""
        return self.is_enabled and self.status == ScheduleStatus.ACTIVE

    def __repr__(self) -> str:
        return f"<ScheduledTask(id={self.id}, name={self.name}, type={self.schedule_type})>"
