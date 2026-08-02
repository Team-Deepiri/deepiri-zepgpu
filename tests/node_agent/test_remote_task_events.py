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


class FakeTaskNoUser(FakeTask):
    user_id = None


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
async def test_emit_remote_task_update_uses_send_personal_message_for_owned_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matches ConnectionManager's real interface: a task with a user_id
    goes through send_personal_message, not a probed method name."""
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeManager:
        async def send_personal_message(self, payload: dict[str, Any], user_id: str) -> None:
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
async def test_emit_remote_task_update_broadcasts_when_task_has_no_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task with no user_id falls back to a plain broadcast() call."""
    calls: list[dict[str, Any]] = []

    class FakeManager:
        async def broadcast(self, payload: dict[str, Any]) -> None:
            calls.append(payload)

    monkeypatch.setattr(remote_task_events, "manager", FakeManager())

    await remote_task_events.emit_remote_task_update(
        task=FakeTaskNoUser(),  # type: ignore[arg-type]
        assignment=FakeAssignment(),  # type: ignore[arg-type]
    )

    assert calls[0]["type"] == "task_update"
    assert calls[0]["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_emit_remote_task_update_logs_and_swallows_manager_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the manager itself raises (e.g. interface mismatch or a dead
    socket bubbling up), emit_remote_task_update must not propagate --
    a WebSocket notification failure shouldn't fail the whole request."""

    class BrokenManager:
        async def send_personal_message(self, payload: dict[str, Any], user_id: str) -> None:
            raise RuntimeError("socket send failed")

    monkeypatch.setattr(remote_task_events, "manager", BrokenManager())

    # Should not raise.
    await remote_task_events.emit_remote_task_update(
        task=FakeTask(),  # type: ignore[arg-type]
        assignment=FakeAssignment(),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_send_remote_task_callback_uses_safe_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_deliver_callback(
        url: str,
        payload: dict[str, Any],
    ) -> None:
        calls.append((url, payload))

    monkeypatch.setattr(
        remote_task_events,
        "deliver_callback",
        fake_deliver_callback,
    )

    await remote_task_events.send_remote_task_callback(
        task=FakeTask(),  # type: ignore[arg-type]
        assignment=FakeAssignment(),  # type: ignore[arg-type]
    )

    assert len(calls) == 1
    assert calls[0][0] == "http://callback.local/task"
    assert calls[0][1]["type"] == "task_update"
    assert calls[0][1]["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_send_remote_task_callback_swallows_delivery_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_deliver_callback(
        _url: str,
        _payload: dict[str, Any],
    ) -> None:
        raise RuntimeError("blocked callback")

    monkeypatch.setattr(
        remote_task_events,
        "deliver_callback",
        failing_deliver_callback,
    )

    await remote_task_events.send_remote_task_callback(
        task=FakeTask(),  # type: ignore[arg-type]
        assignment=FakeAssignment(),  # type: ignore[arg-type]
    )


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
