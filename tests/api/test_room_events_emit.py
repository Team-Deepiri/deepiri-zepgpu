"""Unit tests for room WebSocket event helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from deepiri_zepgpu.api.server.room_events import assignment_payload, emit_room_event
from deepiri_zepgpu.api.server.routes.node_tasks import _emit_room_task_event


@pytest.mark.asyncio
async def test_emit_room_event_payload_shape() -> None:
    with patch(
        "deepiri_zepgpu.api.server.room_events.manager.broadcast_to_room",
        new_callable=AsyncMock,
    ) as mock_broadcast:
        await emit_room_event(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "room_gpu_update",
            {"peer_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"},
        )

        mock_broadcast.assert_awaited_once()
        room_id, message = mock_broadcast.await_args.args
        assert room_id == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        assert message["type"] == "room_gpu_update"
        assert message["room_id"] == room_id
        assert "timestamp" in message
        assert message["payload"]["peer_id"] == "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_emit_room_event_swallows_errors() -> None:
    with patch(
        "deepiri_zepgpu.api.server.room_events.manager.broadcast_to_room",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        await emit_room_event("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "room_node_online", {})


def test_assignment_payload() -> None:
    payload = assignment_payload(
        task_id="t1",
        assignment_id="a1",
        peer_id="p1",
        gpu_share_id="g1",
        status="assigned",
        assignment_status="assigned",
    )
    assert payload["task_id"] == "t1"
    assert payload["assignment_id"] == "a1"
    assert payload["error"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type",
    [
        "room_task_assigned",
        "room_task_started",
        "room_task_completed",
        "room_task_failed",
    ],
)
async def test_emit_room_task_event_includes_invalidation_ids(event_type: str) -> None:
    assignment = SimpleNamespace(
        id="assignment-1",
        task_id="task-1",
        vpn_network_id="room-1",
        peer_id="peer-1",
        gpu_share_id="gpu-1",
        status=SimpleNamespace(value="running"),
        error=None,
    )
    task = SimpleNamespace(status=SimpleNamespace(value="running"), error=None)

    with patch(
        "deepiri_zepgpu.api.server.routes.node_tasks.emit_room_event",
        new_callable=AsyncMock,
    ) as mock_emit:
        await _emit_room_task_event(
            event_type=event_type,
            task=task,
            assignment=assignment,
        )

    mock_emit.assert_awaited_once()
    room_id, emitted_type, payload = mock_emit.await_args.args
    assert room_id == "room-1"
    assert emitted_type == event_type
    assert payload["task_id"] == "task-1"
    assert payload["assignment_id"] == "assignment-1"
    assert payload["peer_id"] == "peer-1"
    assert payload["gpu_share_id"] == "gpu-1"
