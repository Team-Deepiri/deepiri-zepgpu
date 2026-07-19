"""WebSocket endpoints for real-time updates."""

from __future__ import annotations

import asyncio
import logging

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from deepiri_zepgpu.api.server.websocket_manager import manager
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.repositories import GPURepository, TaskRepository
from deepiri_zepgpu.database.session import get_db_context
from deepiri_zepgpu.vpn.repositories import VpnNetworkRepository

logger = logging.getLogger(__name__)

router = APIRouter()


async def authenticate_websocket(token: str | None) -> str | None:
    """Authenticate WebSocket connection using JWT token."""
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.auth.secret_key,
            algorithms=[settings.auth.algorithm],
        )
        return payload.get("sub")
    except jwt.JWTError:  # type: ignore[attr-defined]
        return None


@router.websocket("/ws/tasks")
async def task_updates_websocket(  # noqa: C901
    websocket: WebSocket,
    token: str | None = Query(None),
) -> None:
    """WebSocket endpoint for real-time task updates.

    Connect with: ws://host/ws/tasks?token=<jwt_token>
    """
    user_id = await authenticate_websocket(token)

    if not user_id:
        await websocket.close(code=4001, reason="Authentication required")
        return

    await manager.connect(websocket, user_id)

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "user_id": user_id,
                "message": "Connected to task updates stream",
            }
        )

        while True:
            data = await websocket.receive_text()

            try:
                message = asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda d=data: __import__("json").loads(d),  # type: ignore[misc]
                )
                msg = await message

                if isinstance(msg, dict):
                    msg_type = msg.get("type")

                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})

                    elif msg_type == "subscribe_task":
                        task_id = msg.get("task_id")
                        if task_id:
                            await websocket.send_json(
                                {
                                    "type": "subscribed",
                                    "task_id": task_id,
                                }
                            )

                    elif msg_type == "unsubscribe_task":
                        task_id = msg.get("task_id")
                        if task_id:
                            await websocket.send_json(
                                {
                                    "type": "unsubscribed",
                                    "task_id": task_id,
                                }
                            )

                    elif msg_type == "get_status":
                        async with get_db_context() as db:
                            repo = TaskRepository(db)
                            pending = await repo.list_pending(limit=10)
                            await websocket.send_json(
                                {
                                    "type": "status",
                                    "pending_tasks": len(pending),
                                }
                            )

            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": str(e),
                    }
                )

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, user_id)


@router.websocket("/ws/gpus")
async def gpu_updates_websocket(
    websocket: WebSocket,
    token: str | None = Query(None),
) -> None:
    """WebSocket endpoint for real-time GPU metrics updates.

    Connect with: ws://host/ws/gpus?token=<jwt_token>
    """
    user_id = await authenticate_websocket(token)

    if not user_id:
        await websocket.close(code=4001, reason="Authentication required")
        return

    await manager.connect(websocket, user_id)

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "user_id": user_id,
                "message": "Connected to GPU metrics stream",
            }
        )

        async def send_gpu_updates() -> None:
            """Send periodic GPU updates."""
            while True:
                try:
                    async with get_db_context() as db:
                        gpu_repo = GPURepository(db)
                        devices = await gpu_repo.list_all()

                        for device in devices:
                            await websocket.send_json(
                                {
                                    "type": "gpu_update",
                                    "device_id": device.device_index,
                                    "name": device.name,
                                    "utilization_percent": device.utilization_percent,
                                    "temperature_celsius": device.temperature_celsius,
                                    "power_draw_watts": device.power_draw_watts,
                                    "state": (
                                        device.state.value
                                        if hasattr(device.state, "value")
                                        else str(device.state)
                                    ),
                                }
                            )

                    await asyncio.sleep(5)

                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error in GPU updates stream: {e}")
                    break

        update_task = asyncio.create_task(send_gpu_updates())

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            update_task.cancel()

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, user_id)


@router.websocket("/ws/metrics")
async def metrics_websocket(  # noqa: C901
    websocket: WebSocket,
    token: str | None = Query(None),
) -> None:
    """WebSocket endpoint for aggregated system metrics.

    Connect with: ws://host/ws/metrics?token=<jwt_token>
    """
    user_id = await authenticate_websocket(token)

    if not user_id:
        await websocket.close(code=4001, reason="Authentication required")
        return

    await manager.connect(websocket, user_id)

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "user_id": user_id,
                "message": "Connected to metrics stream",
            }
        )

        async def send_metrics() -> None:
            """Send periodic system metrics."""
            import psutil

            while True:
                try:
                    cpu_percent = psutil.cpu_percent(interval=1)
                    memory = psutil.virtual_memory()

                    async with get_db_context() as db:
                        from deepiri_zepgpu.database.repositories import (
                            GPURepository,
                            TaskRepository,
                        )

                        task_repo = TaskRepository(db)
                        gpu_repo = GPURepository(db)

                        pending_count = 0
                        for status in ["pending", "queued", "scheduled"]:
                            try:
                                from deepiri_zepgpu.database.models.task import TaskStatus

                                status_enum = TaskStatus(status)
                                count = await task_repo.count_by_status(status_enum)
                                pending_count += count
                            except (ValueError, AttributeError):
                                pass

                        available_gpus = await gpu_repo.count_available()

                    await websocket.send_json(
                        {
                            "type": "metrics",
                            "cpu_percent": cpu_percent,
                            "memory_percent": memory.percent,
                            "pending_tasks": pending_count,
                            "available_gpus": available_gpus,
                        }
                    )

                    await asyncio.sleep(10)

                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"Error in metrics stream: {e}")
                    break

        update_task = asyncio.create_task(send_metrics())

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            update_task.cancel()

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, user_id)


async def _load_user_room_ids(user_id: str) -> set[str]:
    """Load room IDs the user belongs to from the database."""
    async with get_db_context() as db:
        network_repo = VpnNetworkRepository(db)
        networks = await network_repo.list_user_networks(user_id)
        return {str(network.id) for network in networks}


async def _resolve_user_room_ids(user_id: str) -> set[str]:
    """Prefer Redis membership cache; fall back to DB (write-through via set_user_room_memberships)."""
    cached = await asyncio.to_thread(manager.membership_cache.get_rooms, user_id)
    if cached is not None:
        return cached
    return await _load_user_room_ids(user_id)


@router.websocket("/ws/rooms")
async def room_updates_websocket(  # noqa: C901
    websocket: WebSocket,
    token: str | None = Query(None),
) -> None:
    """WebSocket endpoint for room-scoped live updates.

    Connect with: ws://host/api/v1/ws/rooms?token=<jwt_token>
    Then send: {"type":"subscribe_room","room_id":"..."}
    """
    user_id = await authenticate_websocket(token)

    if not user_id:
        await websocket.close(code=4001, reason="Authentication required")
        return

    await manager.connect(websocket, user_id)
    room_ids = await _resolve_user_room_ids(user_id)
    await manager.set_user_room_memberships(user_id, room_ids)

    try:
        await websocket.send_json(
            {
                "type": "connected",
                "user_id": user_id,
                "message": "Connected to room updates stream",
            }
        )

        while True:
            data = await websocket.receive_json()
            if not isinstance(data, dict):
                await websocket.send_json(
                    {"type": "room_error", "detail": "Message must be a JSON object"}
                )
                continue

            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "subscribe_room":
                room_id = data.get("room_id")
                if not room_id or not isinstance(room_id, str):
                    await websocket.send_json(
                        {"type": "room_error", "detail": "room_id is required"}
                    )
                    continue
                if not manager.user_is_room_member(user_id, room_id):
                    await websocket.send_json(
                        {
                            "type": "room_error",
                            "room_id": room_id,
                            "detail": "Not a member of this room",
                        }
                    )
                    continue
                await manager.subscribe_room(websocket, room_id)
                await websocket.send_json({"type": "subscribed", "room_id": room_id})
                continue

            if msg_type == "unsubscribe_room":
                room_id = data.get("room_id")
                if not room_id or not isinstance(room_id, str):
                    await websocket.send_json(
                        {"type": "room_error", "detail": "room_id is required"}
                    )
                    continue
                await manager.unsubscribe_room(websocket, room_id)
                await websocket.send_json({"type": "unsubscribed", "room_id": room_id})
                continue

            await websocket.send_json(
                {"type": "room_error", "detail": f"Unknown message type: {msg_type}"}
            )

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket, user_id)
