"""Task router - routes GPU tasks to remote peers over the VPN."""

from __future__ import annotations

import asyncio
import base64
import pickle
import time

import httpx

from deepiri_zepgpu.vpn.config import vpn_settings


class TaskRouter:
    """Route GPU tasks to remote peer nodes over the VPN."""

    def __init__(self, relay_api_url: str | None = None):
        self._relay_url = relay_api_url or vpn_settings.relay_api_url

    async def execute_on_peer(
        self,
        peer_vpn_ip: str,
        task_id: str,
        func,
        args: tuple,
        kwargs: dict,
        gpu_device_id: int,
        gpu_memory_mb: int,
        timeout_seconds: int = 3600,
    ) -> dict:
        """Execute a function on a remote peer via its VPN IP."""
        func_encoded = base64.b64encode(pickle.dumps(func)).decode()
        args_encoded = base64.b64encode(pickle.dumps(args)).decode()
        kwargs_encoded = base64.b64encode(pickle.dumps(kwargs)).decode()

        async with httpx.AsyncClient(timeout=timeout_seconds + 10) as client:
            try:
                response = await client.post(
                    f"http://{peer_vpn_ip}:{vpn_settings.peer_server_port}/execute",
                    json={
                        "task_id": task_id,
                        "func_encoded": func_encoded,
                        "args_encoded": args_encoded,
                        "kwargs_encoded": kwargs_encoded,
                        "gpu_device_id": gpu_device_id,
                        "gpu_memory_mb": gpu_memory_mb,
                        "timeout_seconds": timeout_seconds,
                    },
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException:
                return {
                    "task_id": task_id,
                    "success": False,
                    "error": "Task timed out on remote peer",
                    "execution_time": timeout_seconds,
                }
            except Exception as e:
                return {
                    "task_id": task_id,
                    "success": False,
                    "error": str(e),
                    "execution_time": 0.0,
                }

    async def poll_task_result(
        self,
        peer_vpn_ip: str,
        task_id: str,
        poll_interval: float = 2.0,
        max_wait: float = 3600.0,
    ) -> dict | None:
        """Poll a remote peer for task result."""
        start = time.time()
        async with httpx.AsyncClient(timeout=10) as client:
            while time.time() - start < max_wait:
                try:
                    response = await client.get(
                        f"http://{peer_vpn_ip}:{vpn_settings.peer_server_port}/result/{task_id}",
                        timeout=5,
                    )
                    if response.status_code == 200:
                        return response.json()
                    await asyncio.sleep(poll_interval)
                except Exception:
                    await asyncio.sleep(poll_interval)
        return None
