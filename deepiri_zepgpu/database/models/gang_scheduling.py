"""Gang scheduling model for multi-GPU distributed tasks."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from deepiri_zepgpu.database.models.user import User


class GangStatus(str, enum.Enum):
    """Gang scheduling status."""
    PENDING = "pending"
    SCHEDULING = "scheduling"
    ALLOCATED = "allocated"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL_FAILURE = "partial_failure"


class GangTask(UUIDMixin, TimestampMixin, Base):
    """Gang scheduled task - a task requiring multiple GPUs atomically allocated."""
    
    __tablename__ = "gang_tasks"
    
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    status: Mapped[GangStatus] = mapped_column(
        Enum(GangStatus),
        default=GangStatus.PENDING,
        nullable=False,
        index=True,
    )
    
    num_gpus_required: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    allocated_gpu_ids: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    
    gpu_memory_mb_per_gpu: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    gpu_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    priority: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    allow_partial_allocation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    func_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    serialized_func: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    args: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    kwargs: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=7200, nullable=False)
    
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    callback_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    can_be_preempted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    checkpoint_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    child_task_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    
    user: Mapped["User | None"] = relationship("User", back_populates="gang_tasks")
    
    __table_args__ = (
        Index("idx_gang_tasks_user_status", "user_id", "status"),
        Index("idx_gang_tasks_priority", "priority"),
        Index("idx_gang_tasks_created_at", "created_at"),
    )

    @property
    def is_terminal(self) -> bool:
        """Check if gang task is in terminal state."""
        return self.status in {
            GangStatus.COMPLETED,
            GangStatus.FAILED,
            GangStatus.CANCELLED,
        }

    @property
    def num_gpus_allocated(self) -> int:
        """Get number of GPUs currently allocated."""
        if self.allocated_gpu_ids:
            return len(self.allocated_gpu_ids)
        return 0

    @property
    def is_fully_allocated(self) -> bool:
        """Check if all required GPUs are allocated."""
        return self.num_gpus_allocated >= self.num_gpus_required

    def __repr__(self) -> str:
        return f"<GangTask(id={self.id}, name={self.name}, gpus={self.num_gpus_allocated}/{self.num_gpus_required})>"


class PreemptionRecord(UUIDMixin, Base):
    """Record of a preemption event for tracking and potential resume."""
    
    __tablename__ = "preemption_records"
    
    gang_task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gang_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    preempted_task_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    preempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    
    checkpoint_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    execution_time_before_preemption_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    
    resume_attempted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resume_successful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resume_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<PreemptionRecord(id={self.id}, gang_task_id={self.gang_task_id})>"


class FairShareBucket(UUIDMixin, Base):
    """Fair share scheduling bucket per user/namespace."""
    
    __tablename__ = "fair_share_buckets"
    
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    
    namespace: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    
    weight: Mapped[float] = mapped_column(default=1.0, nullable=False)
    
    gpu_seconds_used: Mapped[float] = mapped_column(default=0.0, nullable=False)
    gpu_seconds_limit: Mapped[float | None] = mapped_column(BigInteger, nullable=True)
    
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_preempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    @property
    def gpu_hours_used(self) -> float:
        """Get GPU hours used."""
        return self.gpu_seconds_used / 3600.0

    @property
    def gpu_hours_limit(self) -> float | None:
        """Get GPU hours limit."""
        if self.gpu_seconds_limit:
            return self.gpu_seconds_limit / 3600.0
        return None

    @property
    def is_over_limit(self) -> bool:
        """Check if user is over their GPU time limit."""
        if self.gpu_seconds_limit is None:
            return False
        return self.gpu_seconds_used >= self.gpu_seconds_limit

    def __repr__(self) -> str:
        return f"<FairShareBucket(user_id={self.user_id}, namespace={self.namespace}, weight={self.weight})>"
