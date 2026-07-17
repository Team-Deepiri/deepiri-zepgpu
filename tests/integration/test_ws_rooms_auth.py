"""WebSocket /ws/rooms auth and subscribe behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from deepiri_zepgpu.api.server.main import app

client = TestClient(app)


def test_ws_rooms_route_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/v1/ws/rooms" in paths


def test_ws_rooms_rejects_missing_token() -> None:
    with pytest.raises(WebSocketDisconnect) as exc_info, client.websocket_connect(
        "/api/v1/ws/rooms"
    ):
        pass
    assert exc_info.value.code == 4001


def test_ws_rooms_rejects_bad_token() -> None:
    with (
        patch(
            "deepiri_zepgpu.api.server.routes.websocket.authenticate_websocket",
            new_callable=AsyncMock,
            return_value=None,
        ),
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/api/v1/ws/rooms?token=bad"),
    ):
        pass
    assert exc_info.value.code == 4001


def test_ws_rooms_connected_ack() -> None:
    with (
        patch(
            "deepiri_zepgpu.api.server.routes.websocket.authenticate_websocket",
            new_callable=AsyncMock,
            return_value="user-1",
        ),
        client.websocket_connect("/api/v1/ws/rooms?token=ok") as ws,
    ):
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        assert msg["user_id"] == "user-1"


def test_ws_rooms_ping_pong() -> None:
    with (
        patch(
            "deepiri_zepgpu.api.server.routes.websocket.authenticate_websocket",
            new_callable=AsyncMock,
            return_value="user-1",
        ),
        client.websocket_connect("/api/v1/ws/rooms?token=ok") as ws,
    ):
        assert ws.receive_json()["type"] == "connected"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_ws_rooms_subscribe_requires_membership() -> None:
    with (
        patch(
            "deepiri_zepgpu.api.server.routes.websocket.authenticate_websocket",
            new_callable=AsyncMock,
            return_value="user-1",
        ),
        patch(
            "deepiri_zepgpu.api.server.routes.websocket._user_is_room_member",
            new_callable=AsyncMock,
            return_value=False,
        ),
        client.websocket_connect("/api/v1/ws/rooms?token=ok") as ws,
    ):
        assert ws.receive_json()["type"] == "connected"
        room_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ws.send_json({"type": "subscribe_room", "room_id": room_id})
        err = ws.receive_json()
        assert err["type"] == "room_error"
        assert "Not a member" in err["detail"]


def test_ws_rooms_subscribe_member_ack() -> None:
    with (
        patch(
            "deepiri_zepgpu.api.server.routes.websocket.authenticate_websocket",
            new_callable=AsyncMock,
            return_value="user-1",
        ),
        patch(
            "deepiri_zepgpu.api.server.routes.websocket._user_is_room_member",
            new_callable=AsyncMock,
            return_value=True,
        ),
        client.websocket_connect("/api/v1/ws/rooms?token=ok") as ws,
    ):
        assert ws.receive_json()["type"] == "connected"
        room_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        ws.send_json({"type": "subscribe_room", "room_id": room_id})
        ack = ws.receive_json()
        assert ack == {"type": "subscribed", "room_id": room_id}
        ws.send_json({"type": "unsubscribe_room", "room_id": room_id})
        assert ws.receive_json() == {"type": "unsubscribed", "room_id": room_id}
