"""User Quota model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import NUMERIC
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base

from deepiri_zepgpu.database.models.user import User


class UserQuota(Base):
    """User resource quota model."""
    
    __tablename__ = "user_quotas"
    
    user_id: Mapped[str] = mapped_column(
        primary_key=True,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    
    max_tasks: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_gpu_hours: Mapped[float] = mapped_column(Float, default=24.0, nullable=False)
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    max_gpu_memory_mb: Mapped[int] = mapped_column(Integer, default=16384, nullable=False)
    max_storage_gb: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    
    period_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    
    tasks_submitted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gpu_seconds_used: Mapped[float] = mapped_column(
        NUMERIC(15, 2),
        default=0.0,
        nullable=False,
    )
    concurrent_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_used_gb: Mapped[float] = mapped_column(
        NUMERIC(10, 2),
        default=0.0,
        nullable=False,
    )
    
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    
    user: Mapped["User"] = relationship("User", back_populates="quota")

    @property
    def gpu_hours_used(self) -> float:
        """Get GPU hours used."""
        return self.gpu_seconds_used / 3600.0

    @property
    def tasks_remaining(self) -> int:
        """Get remaining tasks in period."""
        return max(0, self.max_tasks - self.tasks_submitted)

    @property
    def gpu_hours_remaining(self) -> float:
        """Get remaining GPU hours in period."""
        return max(0, self.max_gpu_hours - self.gpu_hours_used)

    @property
    def concurrent_tasks_remaining(self) -> int:
        """Get remaining concurrent task slots."""
        return max(0, self.max_concurrent_tasks - self.concurrent_tasks)

    @property
    def is_period_expired(self) -> bool:
        """Check if quota period has expired."""
        from datetime import timedelta
        return datetime.utcnow() > self.period_start + timedelta(hours=self.period_hours)

    def reset_period(self) -> None:
        """Reset usage counters for new period."""
        self.tasks_submitted = 0
        self.gpu_seconds_used = 0.0
        self.concurrent_tasks = 0
        self.storage_used_gb = 0.0
        self.period_start = datetime.utcnow()

    def __repr__(self) -> str:
        return f"<UserQuota(user_id={self.user_id}, tasks={self.tasks_submitted}/{self.max_tasks})>"
