"""Database session management."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from deepiri_zepgpu.config import settings

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://deepiri:deepiri@localhost:5432/deepiri")
DATABASE_SYNC_URL = os.getenv("DATABASE_SYNC_URL", "postgresql://deepiri:deepiri@localhost:5432/deepiri")

async_engine = create_async_engine(
    DATABASE_URL,
    echo=settings.database.echo,
    pool_size=settings.database.pool_size,
    max_overflow=settings.database.max_overflow,
    pool_pre_ping=True,
    pool_recycle=3600,
)

sync_engine = create_engine(
    DATABASE_SYNC_URL,
    echo=settings.database.echo,
    pool_size=settings.database.pool_size,
    max_overflow=settings.database.max_overflow,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_db_sync() -> Generator[Session, None, None]:
    """Get sync database session."""
    with SyncSessionLocal() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables."""
    from deepiri_zepgpu.database.models import Base
    
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    await async_engine.dispose()


class DatabaseManager:
    """Database connection manager."""
    
    def __init__(self):
        self._engine = async_engine
        self._session_factory = AsyncSessionLocal
    
    async def create_session(self) -> AsyncSession:
        """Create a new session."""
        return self._session_factory()
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager for session."""
        session = await self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    
    async def dispose(self) -> None:
        """Dispose engine."""
        await self._engine.dispose()


db_manager = DatabaseManager()
