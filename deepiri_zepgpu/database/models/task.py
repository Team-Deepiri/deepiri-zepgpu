"""Task model."""

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


class TaskStatus(str, enum.Enum):
    """Task execution status."""
    PENDING = "pending"
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(int, enum.Enum):
    """Task priority levels."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4
    CRITICAL = 5


class Task(UUIDMixin, TimestampMixin, Base):
    """GPU compute task model."""
    
    __tablename__ = "tasks"
    
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    
    namespace_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("namespaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
    )
    
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority),
        default=TaskPriority.NORMAL,
        nullable=False,
    )
    
    func_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    serialized_func: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    args: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    kwargs: Mapped[bytes | None] = mapped_column(BYTEA, nullable=True)
    
    gpu_memory_mb: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    cpu_cores: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=3600, nullable=False)
    
    gpu_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    allow_fallback_cpu: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    gpu_device_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    result_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    
    execution_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    
    callback_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    user: Mapped["User | None"] = relationship("User", back_populates="tasks")
    
    __table_args__ = (
        Index("idx_tasks_user_status", "user_id", "status"),
        Index("idx_tasks_namespace", "namespace_id"),
        Index("idx_tasks_created_at", "created_at"),
        Index("idx_tasks_status_created", "status", "created_at"),
    )

    @property
    def execution_time_seconds(self) -> float | None:
        """Get execution time in seconds."""
        if self.execution_time_ms:
            return self.execution_time_ms / 1000.0
        return None

    @property
    def is_terminal(self) -> bool:
        """Check if task is in terminal state."""
        return self.status in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMEOUT,
        }

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, name={self.name}, status={self.status})>"
