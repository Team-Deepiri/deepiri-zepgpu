"""Tests for remote task callback and WebSocket event helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deepiri_zepgpu.api.server import remote_task_events


class FakeStatus:
    value = "completed"


class FakeAssignmentStatus:
    value = "completed"


class FakeTask:
    id = "task-1"
    user_id = "user-1"
    status = FakeStatus()
    result_ref = "s3://bucket/result.json"
    result_size_bytes = 123
    error = None
    metadata_json = {
        "remote_result": {
            "status": "ok",
            "kind": "noop",
            "result_ref": "s3://bucket/result.json",
            "result_size_bytes": 123,
        }
    }
    callback_url = "http://callback.local/task"


class FakeAssignment:
    id = "assignment-1"
    vpn_network_id = "room-1"
    peer_id = "peer-1"
    gpu_share_id = "gpu-share-1"
    status = FakeAssignmentStatus()


def test_build_remote_task_update_payload() -> None:
    payload = remote_task_events.build_remote_task_update_payload(
        task=FakeTask(),  # type: ignore[arg-type]
        assignment=FakeAssignment(),  # type: ignore[arg-type]
    )

    assert payload["type"] == "task_update"
    assert payload["source"] == "remote_node"
    assert payload["task_id"] == "task-1"
    assert payload["assignment_id"] == "assignment-1"
    assert payload["status"] == "completed"
    assert payload["assignment_status"] == "completed"
    assert payload["result_ref"] == "s3://bucket/result.json"
    assert payload["result_size_bytes"] == 123
    assert payload["remote_result"]["kind"] == "noop"


@pytest.mark.asyncio
async def test_emit_remote_task_update_uses_manager_broadcast_to_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeManager:
        async def broadcast_to_user(self, user_id: str, payload: dict[str, Any]) -> None:
            calls.append((user_id, payload))

    monkeypatch.setattr(remote_task_events, "manager", FakeManager())

    await remote_task_events.emit_remote_task_update(
        task=FakeTask(),  # type: ignore[arg-type]
        assignment=FakeAssignment(),  # type: ignore[arg-type]
    )

    assert calls[0][0] == "user-1"
    assert calls[0][1]["type"] == "task_update"
    assert calls[0][1]["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_send_remote_task_callback_posts_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, Any]) -> FakeResponse:
            calls.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(
        remote_task_events.httpx,
        "AsyncClient",
        FakeAsyncClient,
    )

    await remote_task_events.send_remote_task_callback(
        task=FakeTask(),  # type: ignore[arg-type]
        assignment=FakeAssignment(),  # type: ignore[arg-type]
    )

    assert calls[0][0] == "http://callback.local/task"
    assert calls[0][1]["type"] == "task_update"
    assert calls[0][1]["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_notify_terminal_state_skips_missing_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback = SimpleNamespace(called=False)

    async def fake_emit(*_args: Any, **_kwargs: Any) -> None:
        callback.called = True

    monkeypatch.setattr(remote_task_events, "emit_remote_task_update", fake_emit)

    await remote_task_events.notify_remote_task_terminal_state(
        task=None,
        assignment=FakeAssignment(),  # type: ignore[arg-type]
    )

    assert callback.called is False
