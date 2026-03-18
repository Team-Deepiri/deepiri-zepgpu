"""WebSocket connection manager for real-time updates."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: str) -> None:
        """Connect a new WebSocket client."""
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].append(websocket)
        logger.info(f"WebSocket connected for user {user_id}")

    async def disconnect(self, websocket: WebSocket, user_id: str) -> None:
        """Disconnect a WebSocket client."""
        async with self._lock:
            if websocket in self._connections[user_id]:
                self._connections[user_id].remove(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
        logger.info(f"WebSocket disconnected for user {user_id}")

    async def send_personal_message(self, message: dict[str, Any], user_id: str) -> None:
        """Send message to a specific user's connections."""
        async with self._lock:
            connections = list(self._connections.get(user_id, []))

        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to user {user_id}: {e}")

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all connected clients."""
        async with self._lock:
            all_connections = []
            for user_id, connections in self._connections.items():
                all_connections.extend(connections)

        for connection in all_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting message: {e}")

    async def broadcast_task_update(self, task_id: str, status: str, user_id: str, data: dict[str, Any] | None = None) -> None:
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

    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return sum(len(conns) for conns in self._connections.values())

    def get_user_count(self) -> int:
        """Get number of unique connected users."""
        return len(self._connections)


manager = ConnectionManager()
