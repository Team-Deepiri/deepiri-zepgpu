"""Namespace and team repository for multi-tenant database operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.namespace import (
    Namespace,
    NamespaceStatus,
    NamespaceMember,
    TeamRole,
    Team,
    TeamMember,
    NamespaceQuota,
    NamespaceUsage,
)


class NamespaceRepository:
    """Repository for Namespace database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> Namespace:
        """Create a new namespace."""
        namespace = Namespace(id=str(uuid.uuid4()), **kwargs)
        self.session.add(namespace)
        await self.session.flush()
        return namespace

    async def get_by_id(self, namespace_id: str) -> Namespace | None:
        """Get namespace by ID."""
        result = await self.session.execute(
            select(Namespace).where(Namespace.id == namespace_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Namespace | None:
        """Get namespace by name."""
        result = await self.session.execute(
            select(Namespace).where(Namespace.name == name)
        )
        return result.scalar_one_or_none()

    async def get_by_owner(self, owner_id: str) -> Sequence[Namespace]:
        """Get namespaces owned by a user."""
        result = await self.session.execute(
            select(Namespace).where(Namespace.owner_id == owner_id)
        )
        return result.scalars().all()

    async def list_all(
        self,
        status: NamespaceStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Namespace]:
        """List all namespaces."""
        query = select(Namespace)
        if status:
            query = query.where(Namespace.status == status)
        query = query.order_by(Namespace.name).limit(limit).offset(offset)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def list_user_namespaces(self, user_id: str) -> Sequence[Namespace]:
        """List namespaces a user is a member of."""
        result = await self.session.execute(
            select(Namespace)
            .join(NamespaceMember, NamespaceMember.namespace_id == Namespace.id)
            .where(
                and_(
                    NamespaceMember.user_id == user_id,
                    NamespaceMember.is_active == True,
                )
            )
        )
        return result.scalars().all()

    async def update(self, namespace_id: str, **kwargs) -> Namespace | None:
        """Update a namespace."""
        namespace = await self.get_by_id(namespace_id)
        if not namespace:
            return None
        for key, value in kwargs.items():
            if hasattr(namespace, key):
                setattr(namespace, key, value)
        await self.session.flush()
        return namespace

    async def suspend(self, namespace_id: str) -> Namespace | None:
        """Suspend a namespace."""
        return await self.update(namespace_id, status=NamespaceStatus.SUSPENDED)

    async def activate(self, namespace_id: str) -> Namespace | None:
        """Activate a namespace."""
        return await self.update(namespace_id, status=NamespaceStatus.ACTIVE)

    async def archive(self, namespace_id: str) -> Namespace | None:
        """Archive a namespace."""
        return await self.update(namespace_id, status=NamespaceStatus.ARCHIVED)

    async def delete(self, namespace_id: str) -> bool:
        """Delete a namespace."""
        namespace = await self.get_by_id(namespace_id)
        if not namespace:
            return False
        await self.session.delete(namespace)
        await self.session.flush()
        return True


class NamespaceMemberRepository:
    """Repository for NamespaceMember database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> NamespaceMember:
        """Create a new namespace member."""
        member = NamespaceMember(
            id=str(uuid.uuid4()),
            joined_at=datetime.utcnow(),
            **kwargs,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_by_id(self, member_id: str) -> NamespaceMember | None:
        """Get member by ID."""
        result = await self.session.execute(
            select(NamespaceMember).where(NamespaceMember.id == member_id)
        )
        return result.scalar_one_or_none()

    async def get_by_user_namespace(self, user_id: str, namespace_id: str) -> NamespaceMember | None:
        """Get member by user and namespace."""
        result = await self.session.execute(
            select(NamespaceMember).where(
                and_(
                    NamespaceMember.user_id == user_id,
                    NamespaceMember.namespace_id == namespace_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_namespace(self, namespace_id: str) -> Sequence[NamespaceMember]:
        """List members of a namespace."""
        result = await self.session.execute(
            select(NamespaceMember)
            .where(NamespaceMember.namespace_id == namespace_id)
            .order_by(NamespaceMember.joined_at)
        )
        return result.scalars().all()

    async def list_by_user(self, user_id: str) -> Sequence[NamespaceMember]:
        """List namespaces for a user."""
        result = await self.session.execute(
            select(NamespaceMember).where(NamespaceMember.user_id == user_id)
        )
        return result.scalars().all()

    async def update_role(self, member_id: str, role: TeamRole) -> NamespaceMember | None:
        """Update member role."""
        member = await self.get_by_id(member_id)
        if not member:
            return None
        member.role = role
        await self.session.flush()
        return member

    async def deactivate(self, member_id: str) -> NamespaceMember | None:
        """Deactivate a member."""
        member = await self.get_by_id(member_id)
        if not member:
            return None
        member.is_active = False
        await self.session.flush()
        return member

    async def delete(self, member_id: str) -> bool:
        """Remove a member."""
        member = await self.get_by_id(member_id)
        if not member:
            return False
        await self.session.delete(member)
        await self.session.flush()
        return True

    async def is_member(self, user_id: str, namespace_id: str) -> bool:
        """Check if user is a member of namespace."""
        member = await self.get_by_user_namespace(user_id, namespace_id)
        return member is not None and member.is_active

    async def is_admin(self, user_id: str, namespace_id: str) -> bool:
        """Check if user is admin of namespace."""
        member = await self.get_by_user_namespace(user_id, namespace_id)
        if not member:
            return False
        return member.role in [TeamRole.OWNER, TeamRole.ADMIN]


class TeamRepository:
    """Repository for Team database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> Team:
        """Create a new team."""
        team = Team(id=str(uuid.uuid4()), **kwargs)
        self.session.add(team)
        await self.session.flush()
        return team

    async def get_by_id(self, team_id: str) -> Team | None:
        """Get team by ID."""
        result = await self.session.execute(
            select(Team).where(Team.id == team_id)
        )
        return result.scalar_one_or_none()

    async def get_by_namespace_name(self, namespace_id: str, name: str) -> Team | None:
        """Get team by namespace and name."""
        result = await self.session.execute(
            select(Team).where(
                and_(
                    Team.namespace_id == namespace_id,
                    Team.name == name,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_namespace(self, namespace_id: str) -> Sequence[Team]:
        """List teams in a namespace."""
        result = await self.session.execute(
            select(Team)
            .where(Team.namespace_id == namespace_id)
            .order_by(Team.name)
        )
        return result.scalars().all()

    async def update(self, team_id: str, **kwargs) -> Team | None:
        """Update a team."""
        team = await self.get_by_id(team_id)
        if not team:
            return None
        for key, value in kwargs.items():
            if hasattr(team, key):
                setattr(team, key, value)
        await self.session.flush()
        return team

    async def delete(self, team_id: str) -> bool:
        """Delete a team."""
        team = await self.get_by_id(team_id)
        if not team:
            return False
        await self.session.delete(team)
        await self.session.flush()
        return True


class TeamMemberRepository:
    """Repository for TeamMember database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> TeamMember:
        """Create a new team member."""
        member = TeamMember(
            id=str(uuid.uuid4()),
            joined_at=datetime.utcnow(),
            **kwargs,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_by_id(self, member_id: str) -> TeamMember | None:
        """Get member by ID."""
        result = await self.session.execute(
            select(TeamMember).where(TeamMember.id == member_id)
        )
        return result.scalar_one_or_none()

    async def list_by_team(self, team_id: str) -> Sequence[TeamMember]:
        """List members of a team."""
        result = await self.session.execute(
            select(TeamMember)
            .where(TeamMember.team_id == team_id)
            .order_by(TeamMember.joined_at)
        )
        return result.scalars().all()

    async def list_by_user(self, user_id: str) -> Sequence[TeamMember]:
        """List teams for a user."""
        result = await self.session.execute(
            select(TeamMember).where(TeamMember.user_id == user_id)
        )
        return result.scalars().all()

    async def update_role(self, member_id: str, role: TeamRole) -> TeamMember | None:
        """Update member role."""
        member = await self.get_by_id(member_id)
        if not member:
            return None
        member.role = role
        await self.session.flush()
        return member

    async def delete(self, member_id: str) -> bool:
        """Remove a member."""
        member = await self.get_by_id(member_id)
        if not member:
            return False
        await self.session.delete(member)
        await self.session.flush()
        return True


class NamespaceQuotaRepository:
    """Repository for NamespaceQuota database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> NamespaceQuota:
        """Create namespace quota."""
        quota = NamespaceQuota(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            **kwargs,
        )
        self.session.add(quota)
        await self.session.flush()
        return quota

    async def get_by_namespace(self, namespace_id: str) -> NamespaceQuota | None:
        """Get quota for namespace."""
        result = await self.session.execute(
            select(NamespaceQuota).where(NamespaceQuota.namespace_id == namespace_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, namespace_id: str) -> NamespaceQuota:
        """Get or create quota for namespace."""
        quota = await self.get_by_namespace(namespace_id)
        if quota:
            return quota
        return await self.create(namespace_id=namespace_id)

    async def update(self, namespace_id: str, **kwargs) -> NamespaceQuota | None:
        """Update namespace quota."""
        quota = await self.get_by_namespace(namespace_id)
        if not quota:
            quota = await self.create(namespace_id=namespace_id)
        for key, value in kwargs.items():
            if hasattr(quota, key):
                setattr(quota, key, value)
        quota.updated_at = datetime.utcnow()
        await self.session.flush()
        return quota


class NamespaceUsageRepository:
    """Repository for NamespaceUsage database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> NamespaceUsage:
        """Create namespace usage record."""
        usage = NamespaceUsage(
            id=str(uuid.uuid4()),
            period_start=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            **kwargs,
        )
        self.session.add(usage)
        await self.session.flush()
        return usage

    async def get_by_namespace(self, namespace_id: str) -> NamespaceUsage | None:
        """Get usage for namespace."""
        result = await self.session.execute(
            select(NamespaceUsage).where(NamespaceUsage.namespace_id == namespace_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, namespace_id: str) -> NamespaceUsage:
        """Get or create usage for namespace."""
        usage = await self.get_by_namespace(namespace_id)
        if usage:
            return usage
        return await self.create(namespace_id=namespace_id)

    async def increment_gpu(self, namespace_id: str, delta: int = 1) -> NamespaceUsage | None:
        """Increment current GPU count."""
        usage = await self.get_or_create(namespace_id)
        usage.current_gpus += delta
        usage.updated_at = datetime.utcnow()
        await self.session.flush()
        return usage

    async def add_gpu_hours(self, namespace_id: str, hours: float) -> NamespaceUsage | None:
        """Add GPU hours to usage."""
        usage = await self.get_or_create(namespace_id)
        usage.gpu_hours_today += hours
        usage.gpu_hours_this_month += hours
        usage.updated_at = datetime.utcnow()
        await self.session.flush()
        return usage

    async def increment_tasks(self, namespace_id: str, task_type: str = "total") -> NamespaceUsage | None:
        """Increment task count."""
        usage = await self.get_or_create(namespace_id)
        if task_type == "total":
            usage.total_tasks += 1
        elif task_type == "running":
            usage.running_tasks += 1
        elif task_type == "scheduled":
            usage.scheduled_tasks += 1
        elif task_type == "gang":
            usage.gang_tasks += 1
        usage.updated_at = datetime.utcnow()
        await self.session.flush()
        return usage

    async def decrement_running_tasks(self, namespace_id: str) -> NamespaceUsage | None:
        """Decrement running task count."""
        usage = await self.get_or_create(namespace_id)
        usage.running_tasks = max(0, usage.running_tasks - 1)
        usage.updated_at = datetime.utcnow()
        await self.session.flush()
        return usage

    async def reset_daily(self, namespace_id: str) -> NamespaceUsage | None:
        """Reset daily counters."""
        usage = await self.get_or_create(namespace_id)
        usage.gpu_hours_today = 0
        usage.updated_at = datetime.utcnow()
        await self.session.flush()
        return usage

    async def reset_monthly(self, namespace_id: str) -> NamespaceUsage | None:
        """Reset monthly counters."""
        usage = await self.get_or_create(namespace_id)
        usage.gpu_hours_this_month = 0
        usage.gpu_hours_today = 0
        usage.period_start = datetime.utcnow()
        usage.updated_at = datetime.utcnow()
        await self.session.flush()
        return usage
