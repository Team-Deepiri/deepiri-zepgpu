"""Audit repository for database operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.audit_log import AuditAction, AuditLog


class AuditRepository:
    """Repository for AuditLog database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        action: AuditAction,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        status_code: int | None = None,
        error_message: str | None = None,
    ) -> AuditLog:
        """Create a new audit log entry."""
        log = AuditLog(
            id=str(uuid.uuid4()),
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            status_code=status_code,
            error_message=error_message,
            created_at=datetime.utcnow(),
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def get_by_id(self, log_id: str) -> AuditLog | None:
        """Get audit log by ID."""
        result = await self.session.execute(
            select(AuditLog).where(AuditLog.id == log_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str,
        action: AuditAction | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AuditLog]:
        """List audit logs for a user."""
        query = select(AuditLog).where(AuditLog.user_id == user_id)
        
        if action:
            query = query.where(AuditLog.action == action)
        
        query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return result.scalars().all()

    async def list_by_resource(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AuditLog]:
        """List audit logs for a resource."""
        result = await self.session.execute(
            select(AuditLog)
            .where(
                and_(
                    AuditLog.resource_type == resource_type,
                    AuditLog.resource_id == resource_id,
                )
            )
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def list_by_action(
        self,
        action: AuditAction,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AuditLog]:
        """List audit logs by action type."""
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.action == action)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def list_recent(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AuditLog]:
        """List recent audit logs."""
        result = await self.session.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def count_by_action(
        self,
        action: AuditAction,
        since: datetime | None = None,
    ) -> int:
        """Count audit logs by action."""
        query = select(func.count(AuditLog.id)).where(AuditLog.action == action)
        
        if since:
            query = query.where(AuditLog.created_at >= since)
        
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def count_by_user(
        self,
        user_id: str,
        since: datetime | None = None,
    ) -> int:
        """Count audit logs for a user."""
        query = select(func.count(AuditLog.id)).where(AuditLog.user_id == user_id)
        
        if since:
            query = query.where(AuditLog.created_at >= since)
        
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def delete_old(self, days: int = 90) -> int:
        """Delete old audit logs."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        from sqlalchemy import delete
        result = await self.session.execute(
            delete(AuditLog).where(AuditLog.created_at < cutoff)
        )
        await self.session.flush()
        return result.rowcount or 0

    async def log_task_action(
        self,
        action: AuditAction,
        task_id: str,
        user_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        error: str | None = None,
    ) -> AuditLog:
        """Log a task-related action."""
        return await self.create(
            action=action,
            user_id=user_id,
            resource_type="task",
            resource_id=task_id,
            details=details,
            ip_address=ip_address,
            error_message=error,
        )

    async def log_user_action(
        self,
        action: AuditAction,
        target_user_id: str,
        user_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        error: str | None = None,
    ) -> AuditLog:
        """Log a user-related action."""
        return await self.create(
            action=action,
            user_id=user_id,
            resource_type="user",
            resource_id=target_user_id,
            details=details,
            ip_address=ip_address,
            error_message=error,
        )
