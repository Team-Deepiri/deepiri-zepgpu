"""Peer node: GPU exposer and task receiver for remote GPU sharing."""

from __future__ import annotations

import asyncio
import base64
import pickle
import time
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException
from typing import Any, Callable

from pydantic import BaseModel

from deepiri_zepgpu.vpn.config import vpn_settings

app = FastAPI(title="ZepGPU Peer Node")


class GpuInfo(BaseModel):
    device_index: int
    name: str | None = None
    total_memory_mb: int
    available_memory_mb: int
    compute_capability: str | None = None
    gpu_type: str = "nvidia"
    state: str = "idle"
    utilization_percent: float | None = None


class TaskPayload(BaseModel):
    task_id: str
    func_encoded: str
    args_encoded: str
    kwargs_encoded: str
    gpu_device_id: int
    gpu_memory_mb: int
    timeout_seconds: int = 3600


class TaskResult(BaseModel):
    task_id: str
    success: bool
    result_encoded: str | None = None
    error: str | None = None
    traceback: str | None = None
    execution_time: float = 0.0


_task_results: dict[str, TaskResult] = {}
_local_gpus: list[GpuInfo] = []
_relay_url: str = ""
_peer_id: str = ""
_vpn_ip: str = ""


try:
    import pynvml

    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False


def discover_local_gpus() -> list[GpuInfo]:
    """Discover local GPUs using NVML."""
    gpus: list[GpuInfo] = []
    if not PYNVML_AVAILABLE:
        return gpus

    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle) or f"GPU-{i}"
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total_mb = mem_info.total // (1024 * 1024)
            free_mb = mem_info.free // (1024 * 1024)

            try:
                cc = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
                cc_str = f"{cc.major}.{cc.minor}"
            except Exception:
                cc_str = "0.0"

            gpus.append(
                GpuInfo(
                    device_index=i,
                    name=name,
                    total_memory_mb=total_mb,
                    available_memory_mb=free_mb,
                    compute_capability=cc_str,
                )
            )
        pynvml.nvmlShutdown()
    except Exception:
        pass

    return gpus


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "vpn_ip": _vpn_ip, "peer_id": _peer_id}


@app.get("/gpu/status")
async def gpu_status() -> dict:
    return {"gpus": _local_gpus, "timestamp": datetime.utcnow().isoformat()}


@app.post("/execute", response_model=TaskResult)
async def execute_task(payload: TaskPayload) -> TaskResult:
    start_time = time.time()
    try:
        func = pickle.loads(base64.b64decode(payload.func_encoded))
        args = pickle.loads(base64.b64decode(payload.args_encoded))
        kwargs = pickle.loads(base64.b64decode(payload.kwargs_encoded))

        import os

        old_cuda = os.environ.get("CUDA_VISIBLE_DEVICES")
        os.environ["CUDA_VISIBLE_DEVICES"] = str(payload.gpu_device_id)

        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, _run_func_sync, func, args, kwargs)
        finally:
            if old_cuda is None:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            else:
                os.environ["CUDA_VISIBLE_DEVICES"] = old_cuda

        result_encoded = base64.b64encode(pickle.dumps(result)).decode()
        execution_time = time.time() - start_time
        task_result = TaskResult(
            task_id=payload.task_id,
            success=True,
            result_encoded=result_encoded,
            execution_time=execution_time,
        )
    except Exception as e:
        import traceback

        execution_time = time.time() - start_time
        task_result = TaskResult(
            task_id=payload.task_id,
            success=False,
            error=str(e),
            traceback=traceback.format_exc(),
            execution_time=execution_time,
        )

    _task_results[payload.task_id] = task_result
    return task_result


def _run_func_sync(func: Callable[..., Any], args: tuple, kwargs: dict[str, Any]) -> object:
    return func(*args, **kwargs)


@app.get("/result/{task_id}")
async def get_result(task_id: str) -> TaskResult:
    result = _task_results.get(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return result


async def advertise_gpus_to_relay() -> None:
    """Periodically advertise GPU status to relay."""
    global _local_gpus
    while True:
        _local_gpus = discover_local_gpus()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{_relay_url.rstrip('/')}/api/v1/vpn/peers/heartbeat",
                    json={
                        "peer_id": _peer_id,
                        "gpu_status": [g.model_dump() for g in _local_gpus],
                        "is_online": True,
                    },
                )
        except Exception:
            pass
        await asyncio.sleep(vpn_settings.heartbeat_interval_seconds)


async def start_peer_server(relay_url: str, peer_id: str, vpn_ip: str) -> None:
    """Start the peer node server."""
    global _relay_url, _peer_id, _vpn_ip
    _relay_url = relay_url
    _peer_id = peer_id
    _vpn_ip = vpn_ip

    import uvicorn

    config = uvicorn.Config(
        app, host=vpn_ip, port=vpn_settings.peer_server_port, log_level="warning"
    )
    server = uvicorn.Server(config)
    await server.serve()
