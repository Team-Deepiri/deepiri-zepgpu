"""Pipeline model."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from deepiri_zepgpu.database.models.user import User


class PipelineStatus(str, enum.Enum):
    """Pipeline execution status."""
    PENDING = "pending"
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineStageStatus(str, enum.Enum):
    """Pipeline stage status."""
    PENDING = "pending"
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Pipeline(UUIDMixin, TimestampMixin, Base):
    """Multi-stage pipeline model."""
    
    __tablename__ = "pipelines"
    
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    status: Mapped[PipelineStatus] = mapped_column(
        Enum(PipelineStatus),
        default=PipelineStatus.PENDING,
        nullable=False,
        index=True,
    )
    
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    
    stage_results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    stage_statuses: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    
    current_stage: Mapped[str | None] = mapped_column(String(255), nullable=True)
    completed_stages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    total_execution_time_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    user: Mapped["User | None"] = relationship("User", back_populates="pipelines")

    @property
    def total_stages(self) -> int:
        """Get total number of stages."""
        return len(self.stages) if self.stages else 0

    @property
    def progress_percent(self) -> float:
        """Get pipeline progress percentage."""
        if self.total_stages == 0:
            return 0.0
        return (self.completed_stages / self.total_stages) * 100

    def __repr__(self) -> str:
        return f"<Pipeline(id={self.id}, name={self.name}, status={self.status})>"
