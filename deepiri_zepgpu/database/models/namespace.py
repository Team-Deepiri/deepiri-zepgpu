"""Namespace and Team models for multi-tenant support."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from deepiri_zepgpu.database.models.user import User
    from deepiri_zepgpu.database.models.task import Task
    from deepiri_zepgpu.database.models.gang_scheduling import GangTask


class NamespaceStatus(str, enum.Enum):
    """Namespace status."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class Namespace(UUIDMixin, TimestampMixin, Base):
    """Namespace for multi-tenant isolation."""
    
    __tablename__ = "namespaces"
    
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    status: Mapped[NamespaceStatus] = mapped_column(
        Enum(NamespaceStatus),
        default=NamespaceStatus.ACTIVE,
        nullable=False,
    )
    
    owner_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    max_users: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_gpus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_storage_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    owner: Mapped["User | None"] = relationship("User", foreign_keys=[owner_id])
    members: Mapped[list["NamespaceMember"]] = relationship("NamespaceMember", back_populates="namespace", cascade="all, delete-orphan")
    teams: Mapped[list["Team"]] = relationship("Team", back_populates="namespace", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_namespaces_status", "status"),
        Index("idx_namespaces_owner", "owner_id"),
    )

    def __repr__(self) -> str:
        return f"<Namespace(id={self.id}, name={self.name})>"


class TeamRole(str, enum.Enum):
    """Team membership role."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class NamespaceMember(UUIDMixin, Base):
    """Namespace membership."""
    
    __tablename__ = "namespace_members"
    
    namespace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("namespaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    role: Mapped[TeamRole] = mapped_column(
        Enum(TeamRole),
        default=TeamRole.MEMBER,
        nullable=False,
    )
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    namespace: Mapped["Namespace"] = relationship("Namespace", back_populates="members")
    user: Mapped["User"] = relationship("User")
    
    __table_args__ = (
        Index("idx_namespace_members_user", "user_id"),
        Index("idx_namespace_members_unique", "namespace_id", "user_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<NamespaceMember(namespace_id={self.namespace_id}, user_id={self.user_id}, role={self.role})>"


class Team(UUIDMixin, TimestampMixin, Base):
    """Team within a namespace."""
    
    __tablename__ = "teams"
    
    namespace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("namespaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    team_lead_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    namespace: Mapped["Namespace"] = relationship("Namespace", back_populates="teams")
    team_lead: Mapped["User | None"] = relationship("User", foreign_keys=[team_lead_id])
    members: Mapped[list["TeamMember"]] = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("idx_teams_namespace", "namespace_id"),
        Index("idx_teams_unique", "namespace_id", "name", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Team(id={self.id}, name={self.name})>"


class TeamMember(UUIDMixin, Base):
    """Team membership."""
    
    __tablename__ = "team_members"
    
    team_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    role: Mapped[TeamRole] = mapped_column(
        Enum(TeamRole),
        default=TeamRole.MEMBER,
        nullable=False,
    )
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    team: Mapped["Team"] = relationship("Team", back_populates="members")
    user: Mapped["User"] = relationship("User")
    
    __table_args__ = (
        Index("idx_team_members_user", "user_id"),
        Index("idx_team_members_unique", "team_id", "user_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<TeamMember(team_id={self.team_id}, user_id={self.user_id})>"


class NamespaceQuota(UUIDMixin, Base):
    """Namespace-level resource quotas."""
    
    __tablename__ = "namespace_quotas"
    
    namespace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("namespaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    
    max_gpus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_gpus_per_user: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_storage_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    max_tasks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_scheduled_tasks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_gang_tasks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    max_gpu_hours_per_day: Mapped[float | None] = mapped_column(BigInteger, nullable=True)
    max_gpu_hours_per_month: Mapped[float | None] = mapped_column(BigInteger, nullable=True)
    
    max_concurrent_tasks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    namespace: Mapped["Namespace"] = relationship("Namespace")

    def __repr__(self) -> str:
        return f"<NamespaceQuota(namespace_id={self.namespace_id})>"


class NamespaceUsage(UUIDMixin, Base):
    """Namespace current resource usage tracking."""
    
    __tablename__ = "namespace_usage"
    
    namespace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("namespaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    
    current_gpus: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_storage_gb: Mapped[float] = mapped_column(Integer, default=0, nullable=False)
    
    total_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    running_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scheduled_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gang_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    gpu_hours_today: Mapped[float] = mapped_column(BigInteger, default=0, nullable=False)
    gpu_hours_this_month: Mapped[float] = mapped_column(BigInteger, default=0, nullable=False)
    
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    namespace: Mapped["Namespace"] = relationship("Namespace")

    def __repr__(self) -> str:
        return f"<NamespaceUsage(namespace_id={self.namespace_id}, gpus={self.current_gpus})>"
