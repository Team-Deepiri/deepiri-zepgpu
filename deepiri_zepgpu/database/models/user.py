"""User model."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from deepiri_zepgpu.database.models.task import Task
    from deepiri_zepgpu.database.models.pipeline import Pipeline
    from deepiri_zepgpu.database.models.audit_log import AuditLog
    from deepiri_zepgpu.database.models.user_quota import UserQuota
    from deepiri_zepgpu.database.models.scheduled_task import ScheduledTask
    from deepiri_zepgpu.database.models.gang_scheduling import GangTask


class UserRole(str, enum.Enum):
    """User roles for access control."""
    ADMIN = "admin"
    RESEARCHER = "researcher"
    USER = "user"
    GUEST = "guest"


class User(UUIDMixin, TimestampMixin, Base):
    """User account model."""
    
    __tablename__ = "users"
    
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),
        default=UserRole.USER,
        nullable=False,
    )
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="user", lazy="dynamic")
    pipelines: Mapped[list["Pipeline"]] = relationship("Pipeline", back_populates="user", lazy="dynamic")
    audit_logs: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="user", lazy="dynamic")
    quota: Mapped["UserQuota"] = relationship("UserQuota", back_populates="user", uselist=False)
    scheduled_tasks: Mapped[list["ScheduledTask"]] = relationship("ScheduledTask", back_populates="user", lazy="dynamic")
    gang_tasks: Mapped[list["GangTask"]] = relationship("GangTask", back_populates="user", lazy="dynamic")

    @property
    def full_name(self) -> str:
        """Get user's full name."""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"
