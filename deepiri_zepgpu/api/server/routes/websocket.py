"""WebSocket endpoints for real-time updates."""

from __future__ import annotations

import asyncio
import jwt
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from deepiri_zepgpu.api.server.websocket_manager import manager
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.session import get_db_context
from deepiri_zepgpu.database.repositories import TaskRepository, GPURepository

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
    except jwt.JWTError:
        return None


@router.websocket("/ws/tasks")
async def task_updates_websocket(
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
        await websocket.send_json({
            "type": "connected",
            "user_id": user_id,
            "message": "Connected to task updates stream",
        })
        
        while True:
            data = await websocket.receive_text()
            
            try:
                message = asyncio.get_event_loop().run_in_executor(
                    None, lambda: __import__("json").loads(data)
                )
                msg = await message
                
                if isinstance(msg, dict):
                    msg_type = msg.get("type")
                    
                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                    
                    elif msg_type == "subscribe_task":
                        task_id = msg.get("task_id")
                        if task_id:
                            await websocket.send_json({
                                "type": "subscribed",
                                "task_id": task_id,
                            })
                    
                    elif msg_type == "unsubscribe_task":
                        task_id = msg.get("task_id")
                        if task_id:
                            await websocket.send_json({
                                "type": "unsubscribed",
                                "task_id": task_id,
                            })
                    
                    elif msg_type == "get_status":
                        async with get_db_context() as db:
                            repo = TaskRepository(db)
                            pending = await repo.list_pending(limit=10)
                            await websocket.send_json({
                                "type": "status",
                                "pending_tasks": len(pending),
                            })
                
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e),
                })
                
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
        await websocket.send_json({
            "type": "connected",
            "user_id": user_id,
            "message": "Connected to GPU metrics stream",
        })
        
        async def send_gpu_updates():
            """Send periodic GPU updates."""
            while True:
                try:
                    async with get_db_context() as db:
                        gpu_repo = GPURepository(db)
                        devices = await gpu_repo.list_all()
                        
                        for device in devices:
                            await websocket.send_json({
                                "type": "gpu_update",
                                "device_id": device.device_index,
                                "name": device.name,
                                "utilization_percent": device.utilization_percent,
                                "temperature_celsius": device.temperature_celsius,
                                "power_draw_watts": device.power_draw_watts,
                                "state": device.state.value if hasattr(device.state, 'value') else str(device.state),
                            })
                    
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
async def metrics_websocket(
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
        await websocket.send_json({
            "type": "connected",
            "user_id": user_id,
            "message": "Connected to metrics stream",
        })
        
        async def send_metrics():
            """Send periodic system metrics."""
            import psutil
            
            while True:
                try:
                    cpu_percent = psutil.cpu_percent(interval=1)
                    memory = psutil.virtual_memory()
                    
                    async with get_db_context() as db:
                        from deepiri_zepgpu.database.repositories import TaskRepository, GPURepository
                        
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
                    
                    await websocket.send_json({
                        "type": "metrics",
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory.percent,
                        "pending_tasks": pending_count,
                        "available_gpus": available_gpus,
                    })
                    
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
