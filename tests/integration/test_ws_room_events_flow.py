"""End-to-end-ish room event emissions into a subscribed room WebSocket."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from deepiri_zepgpu.api.server.main import app
from deepiri_zepgpu.api.server.room_events import emit_room_event

client = TestClient(app)

ROOM_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


@pytest.mark.asyncio
async def test_room_event_reaches_subscribed_client() -> None:
    with (
        patch(
            "deepiri_zepgpu.api.server.routes.websocket.authenticate_websocket",
            new_callable=AsyncMock,
            return_value="user-1",
        ),
        patch(
            "deepiri_zepgpu.api.server.routes.websocket._resolve_user_room_ids",
            new_callable=AsyncMock,
            return_value={ROOM_ID},
        ),
        client.websocket_connect("/api/v1/ws/rooms?token=ok") as ws,
    ):
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "subscribe_room", "room_id": ROOM_ID})
        assert ws.receive_json()["type"] == "subscribed"

        await emit_room_event(
            ROOM_ID,
            "room_task_assigned",
            {"task_id": "t1", "assignment_id": "a1"},
        )
        event = ws.receive_json()
        assert event["type"] == "room_task_assigned"
        assert event["room_id"] == ROOM_ID
        assert event["payload"]["task_id"] == "t1"


@pytest.mark.asyncio
async def test_room_event_does_not_leak_across_rooms() -> None:
    other_room = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    with (
        patch(
            "deepiri_zepgpu.api.server.routes.websocket.authenticate_websocket",
            new_callable=AsyncMock,
            return_value="user-1",
        ),
        patch(
            "deepiri_zepgpu.api.server.routes.websocket._resolve_user_room_ids",
            new_callable=AsyncMock,
            return_value={ROOM_ID},
        ),
        client.websocket_connect("/api/v1/ws/rooms?token=ok") as ws,
    ):
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "subscribe_room", "room_id": ROOM_ID})
        assert ws.receive_json()["type"] == "subscribed"

        await emit_room_event(other_room, "room_node_online", {"peer_id": "p1"})
        await emit_room_event(ROOM_ID, "room_node_online", {"peer_id": "p2"})
        event = ws.receive_json()
        assert event["type"] == "room_node_online"
        assert event["payload"]["peer_id"] == "p2"


@pytest.mark.asyncio
async def test_reconnected_client_can_resubscribe_without_stale_delivery() -> None:
    with (
        patch(
            "deepiri_zepgpu.api.server.routes.websocket.authenticate_websocket",
            new_callable=AsyncMock,
            return_value="user-1",
        ),
        patch(
            "deepiri_zepgpu.api.server.routes.websocket._resolve_user_room_ids",
            new_callable=AsyncMock,
            return_value={ROOM_ID},
        ),
    ):
        with client.websocket_connect("/api/v1/ws/rooms?token=ok") as first:
            assert first.receive_json()["type"] == "connected"
            first.send_json({"type": "subscribe_room", "room_id": ROOM_ID})
            assert first.receive_json()["type"] == "subscribed"

        with client.websocket_connect("/api/v1/ws/rooms?token=ok") as second:
            assert second.receive_json()["type"] == "connected"
            second.send_json({"type": "subscribe_room", "room_id": ROOM_ID})
            assert second.receive_json()["type"] == "subscribed"

            await emit_room_event(
                ROOM_ID,
                "room_task_completed",
                {"task_id": "t2", "assignment_id": "a2"},
            )
            event = second.receive_json()
            assert event["type"] == "room_task_completed"
            assert event["payload"]["task_id"] == "t2"
