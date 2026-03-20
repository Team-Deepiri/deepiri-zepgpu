"""Scheduled task run history model."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from deepiri_zepgpu.database.models.scheduled_task import ScheduledTask
    from deepiri_zepgpu.database.models.user import User


class ScheduleRunStatus(str, enum.Enum):
    """Schedule run status enum."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScheduledTaskRun(UUIDMixin, Base):
    """Record of a scheduled task execution."""
    
    __tablename__ = "scheduled_task_runs"
    
    schedule_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    
    status: Mapped[ScheduleRunStatus] = mapped_column(
        Enum(ScheduleRunStatus),
        default=ScheduleRunStatus.PENDING,
        nullable=False,
        index=True,
    )
    
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    trigger_type: Mapped[str] = mapped_column(String(50), default="scheduled", nullable=False)
    
    schedule: Mapped["ScheduledTask"] = relationship("ScheduledTask", back_populates="runs")
    user: Mapped["User | None"] = relationship("User")
    
    __table_args__ = (
        Index("idx_scheduled_task_runs_schedule_created", "schedule_id", "created_at"),
        Index("idx_scheduled_task_runs_status", "status"),
    )

    @property
    def is_terminal(self) -> bool:
        """Check if run is in terminal state."""
        return self.status in {
            ScheduleRunStatus.COMPLETED,
            ScheduleRunStatus.FAILED,
            ScheduleRunStatus.CANCELLED,
        }

    def __repr__(self) -> str:
        return f"<ScheduledTaskRun(id={self.id}, schedule_id={self.schedule_id}, status={self.status})>"
