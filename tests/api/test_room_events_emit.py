"""Unit tests for room WebSocket event helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from deepiri_zepgpu.api.server.room_events import assignment_payload, emit_room_event


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
