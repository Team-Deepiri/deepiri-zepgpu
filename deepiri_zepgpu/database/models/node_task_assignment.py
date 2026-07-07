"""Node task assignment models for room-aware dispatch."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from deepiri_zepgpu.database.models.task import Task


class NodeAssignmentStatus(str, enum.Enum):
    """Lifecycle status for a node task assignment."""

    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeTaskAssignment(UUIDMixin, TimestampMixin, Base):
    """Maps a task to a room GPU share on a specific peer."""

    __tablename__ = "node_task_assignments"

    vpn_network_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vpn_networks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    peer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vpn_peers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    gpu_share_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("gpu_shares.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[NodeAssignmentStatus] = mapped_column(
        Enum(NodeAssignmentStatus),
        default=NodeAssignmentStatus.ASSIGNED,
        nullable=False,
        index=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    task: Mapped[Task] = relationship("Task", back_populates="node_assignments")
    events: Mapped[list["NodeTaskEvent"]] = relationship(
        "NodeTaskEvent",
        back_populates="assignment",
        lazy="selectin",
    )


class NodeTaskEvent(UUIDMixin, Base):
    """Audit events for node task assignment lifecycle."""

    __tablename__ = "node_task_events"

    assignment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("node_task_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    assignment: Mapped[NodeTaskAssignment] = relationship(
        "NodeTaskAssignment",
        back_populates="events",
    )
