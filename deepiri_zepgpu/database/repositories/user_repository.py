"""User repository for database operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepiri_zepgpu.database.models.user import User, UserRole
from deepiri_zepgpu.database.models.user_quota import UserQuota


class UserRepository:
    """Repository for User database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        username: str,
        email: str,
        password_hash: str,
        role: UserRole = UserRole.USER,
        **kwargs,
    ) -> User:
        """Create a new user."""
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
            **kwargs,
        )
        self.session.add(user)
        await self.session.flush()
        
        quota = UserQuota(
            user_id=user.id,
            period_start=datetime.utcnow(),
        )
        self.session.add(quota)
        await self.session.flush()
        
        return user

    async def get_by_id(self, user_id: str) -> User | None:
        """Get user by ID."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_quota(self, user_id: str) -> User | None:
        """Get user by ID with quota loaded."""
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.quota))
            .where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        """Get user by username."""
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Get user by email."""
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_username_or_email(self, username: str, email: str) -> User | None:
        """Get user by username or email."""
        result = await self.session.execute(
            select(User).where(
                or_(User.username == username, User.email == email)
            )
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        user_id: str,
        **kwargs,
    ) -> User | None:
        """Update user."""
        user = await self.get_by_id(user_id)
        if not user:
            return None
        
        for key, value in kwargs.items():
            if hasattr(user, key) and key != "id":
                setattr(user, key, value)
        
        await self.session.flush()
        return user

    async def update_last_login(self, user_id: str) -> User | None:
        """Update user's last login time."""
        return await self.update(user_id, last_login_at=datetime.utcnow())

    async def verify_user(self, user_id: str) -> User | None:
        """Mark user as verified."""
        return await self.update(user_id, is_verified=True)

    async def deactivate(self, user_id: str) -> User | None:
        """Deactivate user."""
        return await self.update(user_id, is_active=False)

    async def activate(self, user_id: str) -> User | None:
        """Activate user."""
        return await self.update(user_id, is_active=True)

    async def delete(self, user_id: str) -> bool:
        """Delete user."""
        user = await self.get_by_id(user_id)
        if not user:
            return False
        
        await self.session.delete(user)
        await self.session.flush()
        return True

    async def list(
        self,
        role: UserRole | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[User]:
        """List users with optional filtering."""
        query = select(User)
        
        if role is not None:
            query = query.where(User.role == role)
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        query = query.order_by(User.created_at.desc()).limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        return result.scalars().all()

    async def count(self, role: UserRole | None = None, is_active: bool | None = None) -> int:
        """Count users."""
        query = select(func.count(User.id))
        
        if role is not None:
            query = query.where(User.role == role)
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def exists_by_username(self, username: str) -> bool:
        """Check if username exists."""
        result = await self.session.execute(
            select(func.count(User.id)).where(User.username == username)
        )
        return (result.scalar() or 0) > 0

    async def exists_by_email(self, email: str) -> bool:
        """Check if email exists."""
        result = await self.session.execute(
            select(func.count(User.id)).where(User.email == email)
        )
        return (result.scalar() or 0) > 0
