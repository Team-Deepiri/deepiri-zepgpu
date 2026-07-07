"""Tests for room task dispatch API validation."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server.routes import tasks as task_routes
from deepiri_zepgpu.api.server.routes.tasks import TaskCreateRequest


def test_validate_room_dispatch_requires_room_id() -> None:
    request = TaskCreateRequest(
        func_name="random.seed",
        dispatch_mode="room_auto",
        gpu_memory_mb=0,
    )
    with pytest.raises(HTTPException) as exc:
        task_routes._validate_room_dispatch_request(request)
    assert exc.value.status_code == 400


def test_validate_room_specific_requires_target() -> None:
    request = TaskCreateRequest(
        func_name="random.seed",
        dispatch_mode="room_specific_node",
        room_id=uuid4(),
        gpu_memory_mb=0,
    )
    with pytest.raises(HTTPException) as exc:
        task_routes._validate_room_dispatch_request(request)
    assert exc.value.status_code == 400


def test_local_dispatch_request_valid_without_room() -> None:
    request = TaskCreateRequest(func_name="random.seed", dispatch_mode="local", gpu_memory_mb=0)
    task_routes._validate_room_dispatch_request(request)


@pytest.mark.asyncio
async def test_create_task_room_auto_assigns_without_celery(monkeypatch) -> None:
    room_id = uuid4()
    user = SimpleNamespace(id=str(uuid4()))
    enqueued: list[str] = []
    monkeypatch.setattr(task_routes, "enqueue_task_to_celery", lambda task_id: enqueued.append(task_id))

    assignment = task_routes.TaskAssignmentResponse(
        assignment_id=str(uuid4()),
        room_id=str(room_id),
        peer_id=str(uuid4()),
        gpu_share_id=str(uuid4()),
        status="assigned",
    )
    dispatch_result = SimpleNamespace(
        assignment=SimpleNamespace(id=assignment.assignment_id, status=SimpleNamespace(value="assigned")),
        peer_id=assignment.peer_id,
        gpu_share_id=assignment.gpu_share_id,
        vpn_network_id=str(room_id),
    )

    async def fake_dispatch(*args, **kwargs):
        return dispatch_result

    class FakeRepo:
        def __init__(self, _db) -> None:
            self.task = SimpleNamespace(
                id=str(uuid4()),
                name="test",
                status=SimpleNamespace(value="assigned"),
                priority=SimpleNamespace(value=2),
                gpu_memory_mb=1024,
                timeout_seconds=3600,
                gpu_type=None,
                gpu_device_id=None,
                created_at=datetime.now(UTC),
                started_at=None,
                completed_at=None,
                error=None,
                execution_time_ms=None,
                user_id=user.id,
                vpn_network_id=str(room_id),
                dispatch_mode="room_auto",
                target_peer_id=None,
                target_gpu_share_id=None,
            )

        async def mark_assigned(self, _task_id: str):
            return self.task

        async def get_by_id(self, _task_id: str):
            return self.task

    monkeypatch.setattr(task_routes, "select_and_assign_room_gpu", fake_dispatch)
    monkeypatch.setattr(task_routes, "TaskRepository", FakeRepo)

    class FakeDb:
        async def flush(self) -> None:
            return None

        def add(self, _obj) -> None:
            return None

        async def rollback(self) -> None:
            return None

    request = TaskCreateRequest(
        func_name="random.seed",
        dispatch_mode="room_auto",
        room_id=room_id,
        gpu_memory_mb=1024,
    )

    response = await task_routes.create_task(
        request,
        background_tasks=SimpleNamespace(add_task=lambda *args: None),
        db=FakeDb(),  # type: ignore[arg-type]
        current_user=user,  # type: ignore[arg-type]
    )

    assert response.status == "assigned"
    assert response.assignment is not None
    assert enqueued == []
