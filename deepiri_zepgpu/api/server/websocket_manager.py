"""WebSocket connection manager for real-time updates."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates.

    User-scoped connections power ``/ws/tasks|gpus|metrics``.
    Room channels power ``/ws/rooms`` subscribers via ``subscribe_room``.
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._socket_to_user_id: dict[WebSocket, str] = {}
        self._room_subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._socket_rooms: dict[WebSocket, set[str]] = defaultdict(set)
        self._user_room_memberships: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        """Connect a new WebSocket client."""
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].append(websocket)
            self._socket_to_user_id[websocket] = user_id
        logger.info(f"WebSocket connected for user {user_id}")

    async def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        """Disconnect a WebSocket client and clear room subscriptions."""
        async with self._lock:
            if websocket in self._connections[user_id]:
                self._connections[user_id].remove(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
                    self._user_room_memberships.pop(user_id, None)
            self._socket_to_user_id.pop(websocket, None)
            self._remove_socket_from_rooms_locked(websocket)
        logger.info(f"WebSocket disconnected for user {user_id}")

    def _remove_socket_from_rooms_locked(self, websocket: WebSocket) -> None:
        room_ids = list(self._socket_rooms.get(websocket, set()))
        for room_id in room_ids:
            subscribers = self._room_subscriptions.get(room_id)
            if subscribers is not None:
                subscribers.discard(websocket)
                if not subscribers:
                    del self._room_subscriptions[room_id]
        self._socket_rooms.pop(websocket, None)

    async def subscribe_room(self, websocket: WebSocket, room_id: str) -> None:
        """Subscribe a connected socket to a room channel."""
        async with self._lock:
            self._room_subscriptions[room_id].add(websocket)
            self._socket_rooms[websocket].add(room_id)

    async def unsubscribe_room(self, websocket: WebSocket, room_id: str) -> None:
        """Unsubscribe a socket from a single room channel."""
        async with self._lock:
            subscribers = self._room_subscriptions.get(room_id)
            if subscribers is not None:
                subscribers.discard(websocket)
                if not subscribers:
                    del self._room_subscriptions[room_id]
            rooms = self._socket_rooms.get(websocket)
            if rooms is not None:
                rooms.discard(room_id)
                if not rooms:
                    del self._socket_rooms[websocket]

    async def unsubscribe_all(self, websocket: WebSocket) -> None:
        """Remove a socket from every room channel."""
        async with self._lock:
            self._remove_socket_from_rooms_locked(websocket)

    async def unsubscribe_user_from_room(self, user_id: str, room_id: str) -> None:
        """Remove all of a user's sockets from one room channel and revoke membership cache."""
        async with self._lock:
            for websocket in list(self._connections.get(user_id, [])):
                subscribers = self._room_subscriptions.get(room_id)
                if subscribers is not None:
                    subscribers.discard(websocket)
                    if not subscribers:
                        del self._room_subscriptions[room_id]

                rooms = self._socket_rooms.get(websocket)
                if rooms is not None:
                    rooms.discard(room_id)
                    if not rooms:
                        del self._socket_rooms[websocket]

            memberships = self._user_room_memberships.get(user_id)
            if memberships is not None:
                memberships.discard(room_id)

    async def set_user_room_memberships(self, user_id: str, room_ids: set[str]) -> None:
        """Replace the cached room memberships for a user."""
        async with self._lock:
            self._user_room_memberships[user_id] = set(room_ids)

    async def grant_room_membership(self, user_id: str, room_id: str) -> None:
        """Add a room to the user's membership cache if they are connected."""
        async with self._lock:
            if user_id not in self._connections and user_id not in self._user_room_memberships:
                return
            memberships = self._user_room_memberships.setdefault(user_id, set())
            memberships.add(room_id)

    def user_is_room_member(self, user_id: str, room_id: str) -> bool:
        """Return whether the cached membership set includes the room."""
        memberships = self._user_room_memberships.get(user_id)
        if memberships is None:
            return False
        return room_id in memberships

    async def _drop_dead_socket(self, websocket: WebSocket) -> None:
        """Remove a failed socket from user and room indexes."""
        async with self._lock:
            user_id = self._socket_to_user_id.pop(websocket, None)
            if user_id is not None:
                connections = self._connections.get(user_id)
                if connections and websocket in connections:
                    connections.remove(websocket)
                    if not connections:
                        del self._connections[user_id]
                        self._user_room_memberships.pop(user_id, None)
            self._remove_socket_from_rooms_locked(websocket)

    async def send_personal_message(self, message: dict[str, Any], user_id: str) -> None:
        """Send message to a specific user's connections."""
        async with self._lock:
            connections = list(self._connections.get(user_id, []))

        dead: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to user {user_id}: {e}")
                dead.append(connection)

        for connection in dead:
            await self._drop_dead_socket(connection)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients."""
        async with self._lock:
            all_connections: list[WebSocket] = []
            for connections in self._connections.values():
                all_connections.extend(connections)

        dead: list[WebSocket] = []
        for connection in all_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")
                dead.append(connection)

        for connection in dead:
            await self._drop_dead_socket(connection)

    async def broadcast_to_room(self, room_id: str, message: dict[str, Any]) -> None:
        """Send a message to every socket subscribed to a room."""
        async with self._lock:
            connections = list(self._room_subscriptions.get(room_id, set()))

        dead: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to room {room_id}: {e}")
                dead.append(connection)

        for connection in dead:
            await self._drop_dead_socket(connection)

    async def broadcast_task_update(
        self, task_id: str, status: str, user_id: str, data: dict[str, Any] | None = None
    ) -> None:
        """Broadcast task status update."""
        message = {
            "type": "task_update",
            "task_id": task_id,
            "status": status,
            "user_id": user_id,
            "data": data or {},
        }
        await self.send_personal_message(message, user_id)

    async def broadcast_gpu_update(self, device_id: int, metrics: dict[str, Any]) -> None:
        """Broadcast GPU metrics update."""
        message = {
            "type": "gpu_update",
            "device_id": device_id,
            "metrics": metrics,
        }
        await self.broadcast(message)

    async def broadcast_queue_update(self, queue_length: int, pending_tasks: int) -> None:
        """Broadcast queue statistics update."""
        message = {
            "type": "queue_update",
            "queue_length": queue_length,
            "pending_tasks": pending_tasks,
        }
        await self.broadcast(message)

    async def broadcast_all(self, message: dict[str, Any]) -> None:
        """Broadcast a message to every connected client.

        Alias for broadcast(). Kept as an explicit public method so callers
        that specifically probe for `broadcast_all` (e.g. remote_task_events'
        fallback chain) have a stable name to depend on, without duplicating
        the locking/error-handling logic that broadcast() already has.
        """
        await self.broadcast(message)

    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return sum(len(conns) for conns in self._connections.values())

    def get_user_count(self) -> int:
        """Get number of unique connected users."""
        return len(self._connections)

    def get_room_subscriber_count(self, room_id: str) -> int:
        """Get number of sockets subscribed to a room."""
        return len(self._room_subscriptions.get(room_id, set()))


manager = ConnectionManager()
