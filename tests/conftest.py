"""Shared pytest fixtures for unit + integration tests."""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://zepgpu:zepgpu@127.0.0.1:5433/zepgpu_test",
)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: tests that need Postgres")
    config.addinivalue_line(
        "markers",
        "regression: full-system regression (API surface + cross-module smoke)",
    )
    config.addinivalue_line(
        "markers",
        "revolution: adversarial + multi-party credit economy + golden vectors",
    )


TRUNCATE_SQL = """
TRUNCATE TABLE
    ledger_bridge_receipts,
    ledger_transactions,
    ledger_blocks,
    ledger_balances,
    ledger_validators,
    scheduled_task_runs,
    scheduled_tasks,
    tasks,
    pipelines,
    namespace_usage,
    namespace_quotas,
    team_members,
    teams,
    namespace_members,
    namespaces,
    gang_tasks,
    preemption_records,
    fair_share_buckets,
    vpn_invites,
    gpu_share_quotas,
    gpu_shares,
    vpn_peers,
    friendships,
    vpn_networks,
    user_quotas,
    users,
    audit_logs
RESTART IDENTITY CASCADE
"""


def _postgres_reachable(url: str) -> bool:
    import asyncio

    async def _probe() -> bool:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


def _run_alembic_upgrade(url: str) -> None:
    env = os.environ.copy()
    env["DATABASE__URL"] = url
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    # Clear cached settings in child via fresh process
    result = subprocess.run(
        ["poetry", "run", "alembic", "upgrade", "head"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ALEMBIC STDOUT: {result.stdout}")
        print(f"ALEMBIC STDERR: {result.stderr}")
        result.check_returncode()


@pytest.fixture(scope="session")
def integration_db_url() -> str:
    if not _postgres_reachable(TEST_DATABASE_URL):
        pytest.skip(
            f"Postgres not reachable at {TEST_DATABASE_URL}. "
            "Start with: docker compose -f docker/docker-compose.test.yml up -d"
        )
    _run_alembic_upgrade(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest_asyncio.fixture
async def integration_engine(integration_db_url: str):
    """Per-test async engine against the migrated test database."""
    engine = create_async_engine(integration_db_url, echo=False, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(integration_engine) -> AsyncIterator[AsyncSession]:
    """Function-scoped session; truncate ledger-related tables after each test."""
    Session = async_sessionmaker(integration_engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
        await session.rollback()

    async with integration_engine.begin() as conn:
        await conn.execute(text("""
                TRUNCATE TABLE
                    ledger_bridge_receipts,
                    ledger_transactions,
                    ledger_blocks,
                    ledger_balances,
                    ledger_validators
                RESTART IDENTITY CASCADE
                """))


@pytest_asyncio.fixture
async def auth_user():
    """In-memory auth principal (API dependency override; no DB insert required)."""
    from deepiri_zepgpu.database.models.user import User, UserRole

    return User(
        id=uuid.uuid4(),
        username=f"itest_{uuid.uuid4().hex[:8]}",
        email=f"itest_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-used",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )


@pytest_asyncio.fixture
async def api_client(integration_engine, auth_user, unique_chain_id: str):
    """httpx ASGI client with DB + auth overrides (ledger-focused)."""
    from httpx import ASGITransport, AsyncClient

    from deepiri_zepgpu.api.server.dependencies import (
        get_current_user,
        get_db_session,
        get_required_user,
    )
    from deepiri_zepgpu.api.server.main import app
    from deepiri_zepgpu.config import get_settings, settings

    get_settings.cache_clear()
    settings.ledger.enabled = True
    settings.ledger.auto_seal = True
    settings.ledger.quorum_threshold = 1
    settings.ledger.isolate_vpn_networks = True
    settings.ledger.chain_id = unique_chain_id
    settings.ledger.extra_validator_private_keys = ""

    Session = async_sessionmaker(integration_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_user():
        return auth_user

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_required_user] = _override_user
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()

    async with integration_engine.begin() as conn:
        await conn.execute(text(TRUNCATE_SQL))


@pytest_asyncio.fixture
async def regression_client(integration_engine, auth_user, unique_chain_id: str, monkeypatch):
    """ASGI client for full-system regression: auth + DB + side-effect stubs."""
    from datetime import datetime

    from httpx import ASGITransport, AsyncClient

    from deepiri_zepgpu.api.server.dependencies import (
        get_current_user,
        get_db_session,
        get_required_user,
    )
    from deepiri_zepgpu.api.server.main import app
    from deepiri_zepgpu.config import get_settings, settings
    from deepiri_zepgpu.database.models.user import User
    from deepiri_zepgpu.database.models.user_quota import UserQuota
    from datetime import datetime

    get_settings.cache_clear()
    settings.ledger.enabled = True
    settings.ledger.auto_seal = True
    settings.ledger.quorum_threshold = 1
    settings.ledger.isolate_vpn_networks = True
    settings.ledger.chain_id = unique_chain_id
    settings.ledger.extra_validator_private_keys = ""

    # Persist auth user so FK-backed endpoints (gang fair-share, tasks) succeed
    Session = async_sessionmaker(integration_engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        session.add(
            User(
                id=auth_user.id,
                username=auth_user.username,
                email=auth_user.email,
                password_hash=auth_user.password_hash,
                role=auth_user.role,
                is_active=True,
                is_verified=True,
            )
        )
        session.add(
            UserQuota(
                user_id=auth_user.id,
                period_start=datetime.utcnow(),
            )
        )
        await session.commit()

    async def _noop_task(_task_id: str) -> None:
        return None

    def _noop_schedule(_schedule_id: str) -> None:
        return None

    monkeypatch.setattr(
        "deepiri_zepgpu.api.server.routes.tasks.enqueue_task_to_celery",
        _noop_task,
    )
    monkeypatch.setattr(
        "deepiri_zepgpu.api.server.routes.schedules._sync_schedule_to_beat",
        _noop_schedule,
    )

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_user():
        return auth_user

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_required_user] = _override_user
    app.dependency_overrides[get_current_user] = _override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()

    async with integration_engine.begin() as conn:
        await conn.execute(text(TRUNCATE_SQL))


@pytest_asyncio.fixture
async def anonymous_client(integration_engine):
    """ASGI client with DB override only (for register/login regression)."""
    from httpx import ASGITransport, AsyncClient

    from deepiri_zepgpu.api.server.dependencies import get_db_session
    from deepiri_zepgpu.api.server.main import app

    Session = async_sessionmaker(integration_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()

    async with integration_engine.begin() as conn:
        await conn.execute(text(TRUNCATE_SQL))


@pytest.fixture
def unique_chain_id() -> str:
    return f"zepgpu-itest-{uuid.uuid4().hex[:10]}"
