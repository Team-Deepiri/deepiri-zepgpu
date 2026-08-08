"""First-class training run and persistent worker records."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
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


class TrainingReservationState(str, enum.Enum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class TrainingOuterRoundState(str, enum.Enum):
    OPEN = "open"
    FINALIZED = "finalized"
    PAUSED = "paused"
    FAILED = "failed"


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
    placement_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    launch_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    launched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_outer_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    workers: Mapped[list[TrainingWorker]] = relationship(
        "TrainingWorker", back_populates="run", cascade="all, delete-orphan"
    )
    islands: Mapped[list[TrainingIsland]] = relationship(
        "TrainingIsland", back_populates="run", cascade="all, delete-orphan"
    )
    reservations: Mapped[list[TrainingGpuReservation]] = relationship(
        "TrainingGpuReservation", back_populates="run", cascade="all, delete-orphan"
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
    island_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("training_islands.id", ondelete="SET NULL"), nullable=True
    )
    global_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    island_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    world_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    island_world_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_devices: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    bootstrap_checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    run: Mapped[TrainingRun] = relationship("TrainingRun", back_populates="workers")
    island: Mapped[TrainingIsland | None] = relationship("TrainingIsland")

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


class TrainingIsland(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "training_islands"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    gpu_share_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    strategy_eligibility: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    topology: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped[TrainingRun] = relationship("TrainingRun", back_populates="islands")

    __table_args__ = (UniqueConstraint("run_id", "id", name="uq_training_island_run_id"),)


class TrainingGpuReservation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "training_gpu_reservations"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_workers.id", ondelete="SET NULL"),
        nullable=True,
    )
    island_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_islands.id", ondelete="SET NULL"),
        nullable=True,
    )
    vpn_network_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vpn_networks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    peer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vpn_peers.id", ondelete="CASCADE"), nullable=False
    )
    gpu_share_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gpu_shares.id", ondelete="CASCADE"), nullable=False
    )
    reservation_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[TrainingReservationState] = mapped_column(
        str_enum(TrainingReservationState),
        default=TrainingReservationState.ACTIVE,
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    run: Mapped[TrainingRun] = relationship("TrainingRun", back_populates="reservations")

    __table_args__ = (
        Index(
            "uq_training_gpu_reservations_active_share",
            "gpu_share_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
        Index("ix_training_gpu_reservations_expiry", "state", "expires_at"),
    )


class TrainingOuterRound(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "training_outer_rounds"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[TrainingOuterRoundState] = mapped_column(
        str_enum(TrainingOuterRoundState), default=TrainingOuterRoundState.OPEN, nullable=False
    )
    expected_workers: Mapped[int] = mapped_column(Integer, nullable=False)
    min_k: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_worker_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    rejected_updates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    optimizer_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "round_number", name="uq_training_outer_round_run_round"),
    )


class TrainingRunEvent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "training_run_events"

    run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("training_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
