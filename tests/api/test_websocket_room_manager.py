"""Unit tests for room channel support on ConnectionManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from deepiri_zepgpu.api.server.websocket_manager import ConnectionManager


def _fake_ws() -> MagicMock:
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_subscribe_and_broadcast_to_room_only() -> None:
    mgr = ConnectionManager()
    room_a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    room_b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

    ws_a = _fake_ws()
    ws_b = _fake_ws()
    await mgr.connect(ws_a, "user-1")
    await mgr.connect(ws_b, "user-2")
    await mgr.subscribe_room(ws_a, room_a)
    await mgr.subscribe_room(ws_b, room_b)

    message = {"type": "room_node_online", "room_id": room_a}
    await mgr.broadcast_to_room(room_a, message)

    ws_a.send_json.assert_awaited_once_with(message)
    ws_b.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_unsubscribe_room_stops_delivery() -> None:
    mgr = ConnectionManager()
    room_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    ws = _fake_ws()
    await mgr.connect(ws, "user-1")
    await mgr.subscribe_room(ws, room_id)
    await mgr.unsubscribe_room(ws, room_id)

    await mgr.broadcast_to_room(room_id, {"type": "room_gpu_update", "room_id": room_id})
    ws.send_json.assert_not_awaited()
    assert mgr.get_room_subscriber_count(room_id) == 0


@pytest.mark.asyncio
async def test_disconnect_clears_room_subscriptions() -> None:
    mgr = ConnectionManager()
    room_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    ws = _fake_ws()
    await mgr.connect(ws, "user-1")
    await mgr.subscribe_room(ws, room_id)
    await mgr.disconnect(ws, "user-1")

    await mgr.broadcast_to_room(room_id, {"type": "room_member_joined", "room_id": room_id})
    ws.send_json.assert_not_awaited()
    assert mgr.get_room_subscriber_count(room_id) == 0
    assert mgr.get_connection_count() == 0


@pytest.mark.asyncio
async def test_multi_room_same_socket() -> None:
    mgr = ConnectionManager()
    room_a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    room_b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    ws = _fake_ws()
    await mgr.connect(ws, "user-1")
    await mgr.subscribe_room(ws, room_a)
    await mgr.subscribe_room(ws, room_b)

    await mgr.broadcast_to_room(room_a, {"type": "room_node_online", "room_id": room_a})
    await mgr.broadcast_to_room(room_b, {"type": "room_node_offline", "room_id": room_b})
    assert ws.send_json.await_count == 2


@pytest.mark.asyncio
async def test_failed_send_drops_socket_from_room() -> None:
    mgr = ConnectionManager()
    room_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    ws = _fake_ws()
    ws.send_json = AsyncMock(side_effect=RuntimeError("gone"))
    await mgr.connect(ws, "user-1")
    await mgr.subscribe_room(ws, room_id)

    await mgr.broadcast_to_room(room_id, {"type": "room_gpu_update", "room_id": room_id})
    assert mgr.get_room_subscriber_count(room_id) == 0
    assert mgr.get_connection_count() == 0


@pytest.mark.asyncio
async def test_unsubscribe_all() -> None:
    mgr = ConnectionManager()
    room_a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    room_b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    ws = _fake_ws()
    await mgr.connect(ws, "user-1")
    await mgr.subscribe_room(ws, room_a)
    await mgr.subscribe_room(ws, room_b)
    await mgr.unsubscribe_all(ws)

    assert mgr.get_room_subscriber_count(room_a) == 0
    assert mgr.get_room_subscriber_count(room_b) == 0


@pytest.mark.asyncio
async def test_unsubscribe_user_from_room_removes_all_user_sockets_only() -> None:
    mgr = ConnectionManager()
    room_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    user_socket_a = _fake_ws()
    user_socket_b = _fake_ws()
    other_socket = _fake_ws()

    await mgr.connect(user_socket_a, "user-1")
    await mgr.connect(user_socket_b, "user-1")
    await mgr.connect(other_socket, "user-2")
    await mgr.subscribe_room(user_socket_a, room_id)
    await mgr.subscribe_room(user_socket_b, room_id)
    await mgr.subscribe_room(other_socket, room_id)

    await mgr.unsubscribe_user_from_room("user-1", room_id)
    await mgr.broadcast_to_room(room_id, {"type": "room_node_online", "room_id": room_id})

    user_socket_a.send_json.assert_not_awaited()
    user_socket_b.send_json.assert_not_awaited()
    other_socket.send_json.assert_awaited_once()
    assert mgr.get_room_subscriber_count(room_id) == 1
