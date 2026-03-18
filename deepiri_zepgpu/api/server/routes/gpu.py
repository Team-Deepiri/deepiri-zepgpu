"""GPU API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel


router = APIRouter()


class GPUDeviceResponse(BaseModel):
    """GPU device response."""
    id: int
    device_index: int
    name: str | None
    gpu_type: str
    vendor: str | None
    total_memory_mb: int | None
    available_memory_mb: int | None
    memory_usage_percent: float | None
    state: str
    utilization_percent: float | None
    temperature_celsius: int | None
    power_draw_watts: float | None
    compute_capability: str | None
    current_task_id: str | None

    class Config:
        from_attributes = True


class GPUListResponse(BaseModel):
    """GPU list response."""
    devices: list[GPUDeviceResponse]
    total_count: int
    available_count: int


class GPUMetricsResponse(BaseModel):
    """GPU metrics response."""
    device_index: int
    utilization_percent: float
    memory_used_mb: float
    memory_total_mb: float
    temperature_celsius: int | None
    power_draw_watts: float | None
    timestamp: datetime


@router.get("/devices", response_model=GPUListResponse)
async def list_gpu_devices() -> GPUListResponse:
    """List all GPU devices."""
    from deepiri_zepgpu.core.gpu_manager import GPUManager
    
    gpu_manager = GPUManager(enable_nvml=False)
    await gpu_manager.initialize()
    
    devices = gpu_manager.list_devices()
    
    return GPUListResponse(
        devices=[
            GPUDeviceResponse(
                id=d.device_id,
                device_index=d.device_id,
                name=d.name,
                gpu_type=d.gpu_type.value,
                vendor=None,
                total_memory_mb=d.total_memory_mb,
                available_memory_mb=d.available_memory_mb,
                memory_usage_percent=((d.total_memory_mb - d.available_memory_mb) / d.total_memory_mb * 100) if d.total_memory_mb > 0 else None,
                state=d.state.value,
                utilization_percent=d.utilization_percent,
                temperature_celsius=int(d.temperature_celsius) if d.temperature_celsius else None,
                power_draw_watts=d.power_draw_watts,
                compute_capability=f"{d.compute_capability[0]}.{d.compute_capability[1]}" if d.compute_capability else None,
                current_task_id=d.current_task_id,
            )
            for d in devices
        ],
        total_count=len(devices),
        available_count=len([d for d in devices if d.state.value == "idle"]),
    )


@router.get("/devices/{device_index}", response_model=GPUDeviceResponse)
async def get_gpu_device(device_index: int) -> GPUDeviceResponse:
    """Get GPU device by index."""
    from deepiri_zepgpu.core.gpu_manager import GPUManager
    
    gpu_manager = GPUManager(enable_nvml=False)
    await gpu_manager.initialize()
    
    device = gpu_manager.get_device(device_index)
    
    if not device:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="GPU device not found")
    
    return GPUDeviceResponse(
        id=device.device_id,
        device_index=device.device_id,
        name=device.name,
        gpu_type=device.gpu_type.value,
        vendor=None,
        total_memory_mb=device.total_memory_mb,
        available_memory_mb=device.available_memory_mb,
        memory_usage_percent=((device.total_memory_mb - device.available_memory_mb) / device.total_memory_mb * 100) if device.total_memory_mb > 0 else None,
        state=device.state.value,
        utilization_percent=device.utilization_percent,
        temperature_celsius=int(device.temperature_celsius) if device.temperature_celsius else None,
        power_draw_watts=device.power_draw_watts,
        compute_capability=f"{device.compute_capability[0]}.{device.compute_capability[1]}" if device.compute_capability else None,
        current_task_id=device.current_task_id,
    )


@router.get("/metrics", response_model=list[GPUMetricsResponse])
async def get_gpu_metrics() -> list[GPUMetricsResponse]:
    """Get current GPU metrics."""
    from deepiri_zepgpu.core.gpu_manager import GPUManager
    
    gpu_manager = GPUManager(enable_nvml=False)
    await gpu_manager.initialize()
    
    devices = gpu_manager.list_devices()
    
    return [
        GPUMetricsResponse(
            device_index=d.device_id,
            utilization_percent=d.utilization_percent or 0.0,
            memory_used_mb=d.total_memory_mb - d.available_memory_mb,
            memory_total_mb=d.total_memory_mb,
            temperature_celsius=int(d.temperature_celsius) if d.temperature_celsius else None,
            power_draw_watts=d.power_draw_watts,
            timestamp=datetime.utcnow(),
        )
        for d in devices
    ]


@router.get("/stats")
async def get_gpu_stats() -> dict[str, Any]:
    """Get aggregated GPU statistics."""
    from deepiri_zepgpu.core.gpu_manager import GPUManager
    
    gpu_manager = GPUManager(enable_nvml=False)
    await gpu_manager.initialize()
    
    devices = gpu_manager.list_devices()
    
    total_memory = sum(d.total_memory_mb for d in devices)
    available_memory = sum(d.available_memory_mb for d in devices)
    
    return {
        "total_devices": len(devices),
        "available_devices": len([d for d in devices if d.state.value == "idle"]),
        "allocated_devices": len([d for d in devices if d.state.value == "allocated"]),
        "total_memory_mb": total_memory,
        "available_memory_mb": available_memory,
        "used_memory_mb": total_memory - available_memory,
        "memory_utilization_percent": ((total_memory - available_memory) / total_memory * 100) if total_memory > 0 else 0,
    }
