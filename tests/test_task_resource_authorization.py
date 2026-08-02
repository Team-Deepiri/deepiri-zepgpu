"""Authorization regressions for task, schedule, and gang resource lifecycles."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from httpx import ASGITransport, AsyncClient

from deepiri_zepgpu.api.server.dependencies import get_db_session
from deepiri_zepgpu.api.server.main import app
from deepiri_zepgpu.api.server.routes import gang_scheduling, schedules, tasks
from deepiri_zepgpu.database.models.gang_scheduling import GangStatus
from deepiri_zepgpu.database.models.scheduled_task import ScheduleStatus, ScheduleType
from deepiri_zepgpu.database.models.task import TaskPriority, TaskStatus
from deepiri_zepgpu.database.models.user import UserRole


async def _anonymous_client() -> AsyncClient:
    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("GET", "/api/v1/tasks", None),
        ("GET", "/api/v1/tasks/00000000-0000-4000-8000-000000000001", None),
        ("GET", "/api/v1/tasks/00000000-0000-4000-8000-000000000001/result", None),
        ("POST", "/api/v1/tasks/00000000-0000-4000-8000-000000000001/retry", None),
        ("DELETE", "/api/v1/tasks/00000000-0000-4000-8000-000000000001", None),
        ("GET", "/api/v1/schedules", None),
        ("GET", "/api/v1/schedules/00000000-0000-4000-8000-000000000002", None),
        ("PUT", "/api/v1/schedules/00000000-0000-4000-8000-000000000002", {}),
        ("DELETE", "/api/v1/schedules/00000000-0000-4000-8000-000000000002", None),
        ("POST", "/api/v1/schedules/00000000-0000-4000-8000-000000000002/enable", None),
        ("POST", "/api/v1/schedules/00000000-0000-4000-8000-000000000002/disable", None),
        ("POST", "/api/v1/schedules/00000000-0000-4000-8000-000000000002/trigger", None),
        ("GET", "/api/v1/schedules/00000000-0000-4000-8000-000000000002/runs", None),
        ("GET", "/api/v1/gang/gang", None),
        ("GET", "/api/v1/gang/gang/00000000-0000-4000-8000-000000000003", None),
        ("PUT", "/api/v1/gang/gang/00000000-0000-4000-8000-000000000003", {}),
        ("DELETE", "/api/v1/gang/gang/00000000-0000-4000-8000-000000000003", None),
        ("POST", "/api/v1/gang/gang/00000000-0000-4000-8000-000000000003/retry", None),
        ("GET", "/api/v1/gang/fair-share/me", None),
        ("PUT", "/api/v1/gang/fair-share/me", {}),
        ("POST", "/api/v1/gang/preempt/check", None),
        ("GET", "/api/v1/gang/fair-share/weights", None),
    ],
)
async def test_resource_lifecycle_requires_authentication(
    method: str,
    path: str,
    json_body: dict[str, object] | None,
) -> None:
    try:
        client = await _anonymous_client()
        async with client:
            response = await client.request(method, path, json=json_body)
        assert response.status_code == 401, response.text
    finally:
        app.dependency_overrides.clear()


def _principal(role: UserRole = UserRole.USER) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), role=role)


def _task(owner_id: object, *, status: TaskStatus = TaskStatus.PENDING) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=owner_id,
        name="owned task",
        status=status,
        priority=TaskPriority.NORMAL,
        gpu_memory_mb=0,
        timeout_seconds=60,
        gpu_type=None,
        gpu_device_id=None,
        created_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
        error=None,
        execution_time_ms=None,
        vpn_network_id=None,
        dispatch_mode="local",
        target_peer_id=None,
        target_gpu_share_id=None,
        result_ref=None,
    )


def _schedule(owner_id: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=owner_id,
        name="owned schedule",
        description=None,
        schedule_type=ScheduleType.INTERVAL,
        cron_expression=None,
        interval_seconds=120,
        start_datetime=None,
        end_datetime=None,
        is_enabled=True,
        status=ScheduleStatus.ACTIVE,
        last_run_at=None,
        next_run_at=None,
        run_count=0,
        consecutive_failures=0,
        last_error=None,
        priority=2,
        gpu_memory_mb=0,
        timeout_seconds=60,
        created_at=datetime.now(UTC),
    )


def _gang_task(owner_id: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=owner_id,
        name="owned gang",
        description=None,
        status=GangStatus.PENDING,
        num_gpus_required=2,
        allocated_gpu_ids=None,
        gpu_memory_mb_per_gpu=0,
        gpu_type=None,
        priority=2,
        allow_partial_allocation=False,
        started_at=None,
        completed_at=None,
        error=None,
        can_be_preempted=False,
        child_task_ids=None,
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_task_owner_access_and_existing_admin_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _principal()
    unrelated_admin = _principal(UserRole.ADMIN)
    task = _task(owner.id)
    repo = SimpleNamespace(get_by_id=AsyncMock(return_value=task))
    monkeypatch.setattr(tasks, "TaskRepository", lambda _db: repo)
    monkeypatch.setattr(tasks, "_load_assignment_summary", AsyncMock(return_value=None))

    response = await tasks.get_task(str(task.id), AsyncMock(), owner)  # type: ignore[arg-type]
    assert response.id == str(task.id)

    with pytest.raises(HTTPException) as exc:
        await tasks.get_task(str(task.id), AsyncMock(), unrelated_admin)  # type: ignore[arg-type]
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_task_result_retry_cancel_and_missing_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _principal()
    task = _task(owner.id)
    repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=task),
        mark_cancelled=AsyncMock(),
    )
    monkeypatch.setattr(tasks, "TaskRepository", lambda _db: repo)

    result = await tasks.get_task_result(str(task.id), AsyncMock(), owner)  # type: ignore[arg-type]
    assert result.task_id == str(task.id)
    await tasks.cancel_task(str(task.id), AsyncMock(), owner)  # type: ignore[arg-type]
    repo.mark_cancelled.assert_awaited_once_with(str(task.id))

    failed = _task(owner.id, status=TaskStatus.FAILED)
    retry_repo = SimpleNamespace(
        get_by_id=AsyncMock(side_effect=[failed, _task(owner.id)]),
        update_status=AsyncMock(),
    )
    monkeypatch.setattr(tasks, "TaskRepository", lambda _db: retry_repo)
    retried = await tasks.retry_task(
        str(failed.id), BackgroundTasks(), AsyncMock(), owner  # type: ignore[arg-type]
    )
    assert retried.status == TaskStatus.PENDING.value

    missing_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=None))
    monkeypatch.setattr(tasks, "TaskRepository", lambda _db: missing_repo)
    with pytest.raises(HTTPException) as exc:
        await tasks.get_task(str(uuid4()), AsyncMock(), owner)  # type: ignore[arg-type]
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_module", "route_name", "factory", "missing_detail"),
    [
        (schedules, "get_schedule", _schedule, "Schedule not found"),
        (gang_scheduling, "get_gang_task", _gang_task, "Gang task not found"),
    ],
)
async def test_schedule_and_gang_owner_unrelated_and_missing_protection(
    monkeypatch: pytest.MonkeyPatch,
    route_module: object,
    route_name: str,
    factory: object,
    missing_detail: str,
) -> None:
    owner = _principal()
    unrelated = _principal(UserRole.ADMIN)
    resource = factory(owner.id)  # type: ignore[operator]
    repo = SimpleNamespace(get_by_id=AsyncMock(return_value=resource))
    repository_name = (
        "ScheduleRepository" if route_module is schedules else "GangScheduleRepository"
    )
    monkeypatch.setattr(route_module, repository_name, lambda _db: repo)
    route = getattr(route_module, route_name)

    response = await route(str(resource.id), AsyncMock(), owner)
    assert response.id == str(resource.id)

    with pytest.raises(HTTPException) as exc:
        await route(str(resource.id), AsyncMock(), unrelated)
    assert exc.value.status_code == 403

    repo.get_by_id = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as exc:
        await route(str(uuid4()), AsyncMock(), owner)
    assert exc.value.status_code == 404
    assert exc.value.detail == missing_detail


@pytest.mark.asyncio
async def test_lists_are_scoped_to_authenticated_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _principal()
    task_repo = SimpleNamespace(list_by_user=AsyncMock(return_value=[]))
    schedule_repo = SimpleNamespace(list_by_user=AsyncMock(return_value=[]))
    gang_repo = SimpleNamespace(list_by_user=AsyncMock(return_value=[]))
    monkeypatch.setattr(tasks, "TaskRepository", lambda _db: task_repo)
    monkeypatch.setattr(schedules, "ScheduleRepository", lambda _db: schedule_repo)
    monkeypatch.setattr(gang_scheduling, "GangScheduleRepository", lambda _db: gang_repo)

    await tasks.list_tasks(AsyncMock(), owner, None, 100, 0)  # type: ignore[arg-type]
    await schedules.list_schedules(AsyncMock(), owner, None, 100, 0)  # type: ignore[arg-type]
    await gang_scheduling.list_gang_tasks(AsyncMock(), owner, None, 100, 0)  # type: ignore[arg-type]

    assert str(task_repo.list_by_user.await_args.kwargs["user_id"]) == str(owner.id)
    assert str(schedule_repo.list_by_user.await_args.kwargs["user_id"]) == str(owner.id)
    assert str(gang_repo.list_by_user.await_args.kwargs["user_id"]) == str(owner.id)
