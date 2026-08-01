"""First-class training run and persistent worker records."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin
from deepiri_zepgpu.database.models.types import str_enum


class TrainingRunState(str, enum.Enum):
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    SYNCING = "syncing"
    CHECKPOINTING = "checkpointing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class TrainingWorkerState(str, enum.Enum):
    CREATED = "created"
    AUTHENTICATING = "authenticating"
    READY = "ready"
    RUNNING = "running"
    SYNCING = "syncing"
    CHECKPOINTING = "checkpointing"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ABORTED = "aborted"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TrainingRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "training_runs"

    vpn_network_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vpn_networks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[TrainingRunState] = mapped_column(
        str_enum(TrainingRunState), default=TrainingRunState.CREATED, nullable=False, index=True
    )
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    startup_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    workers: Mapped[list[TrainingWorker]] = relationship(
        "TrainingWorker", back_populates="run", cascade="all, delete-orphan"
    )


class TrainingWorker(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "training_workers"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    peer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vpn_peers.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[TrainingWorkerState] = mapped_column(
        str_enum(TrainingWorkerState), default=TrainingWorkerState.CREATED, nullable=False
    )
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    restart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    credential_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    credential_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    run: Mapped[TrainingRun] = relationship("TrainingRun", back_populates="workers")

    __table_args__ = (UniqueConstraint("run_id", "peer_id", name="uq_training_worker_run_peer"),)


class TrainingWorkerEvent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "training_worker_events"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_workers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[str] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
