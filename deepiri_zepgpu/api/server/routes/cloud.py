"""Cloud GPU provider API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from deepiri_zepgpu.api.server.dependencies import get_current_user
from deepiri_zepgpu.cloud.manager import cloud_manager


router = APIRouter()


class LaunchInstanceRequest(BaseModel):
    """Request to launch a cloud GPU instance."""
    name: str = Field(default="zepgpu-instance", max_length=255)
    gpu_type: str | None = Field(None, description="Specific GPU type ID (e.g., 'NVIDIA A100' or 'g4dn.xlarge')")
    gpu_count: int = Field(default=1, ge=1, le=8)
    max_price_per_hour: float | None = Field(None, ge=0, description="Maximum price per hour in USD")
    provider: str | None = Field(None, description="Specific provider to use (runpod, aws, lambda)")
    image: str = Field(default="runpod/pytorch:2.1.0-python3.10")
    env: dict[str, str] = Field(default_factory=dict)


class InstanceResponse(BaseModel):
    """Cloud instance response."""
    instance_id: str
    provider: str
    provider_instance_id: str
    status: str
    gpu_type: str
    gpu_count: int
    memory_gb: float
    price_per_hour: float
    endpoint: str | None
    created_at: str


class GPUInfoResponse(BaseModel):
    """GPU info response."""
    provider: str
    gpu_type: str
    name: str
    gpu_count: int
    memory_gb: float
    price_per_hour: float
    available: bool


class CostEstimateResponse(BaseModel):
    """Cost estimate response."""
    provider: str
    gpu_type: str
    gpu_count: int
    price_per_hour: float
    estimated_monthly_cost: float
    currency: str


class ProviderStatusResponse(BaseModel):
    """Provider status response."""
    name: str
    type: str
    display_name: str
    status: str
    error: str | None = None


@router.get("/providers", response_model=list[ProviderStatusResponse])
async def list_providers() -> list[ProviderStatusResponse]:
    """List all configured cloud providers and their status."""
    status_info = await cloud_manager.get_health_status()
    providers = cloud_manager.list_providers()
    
    result = []
    for p in providers:
        name = p["name"]
        p_status = status_info.get(name, {})
        result.append(ProviderStatusResponse(
            name=name,
            type=p["type"],
            display_name=p["display_name"],
            status=p_status.get("status", "unknown"),
            error=p_status.get("error"),
        ))
    
    return result


@router.get("/gpus", response_model=list[GPUInfoResponse])
async def list_available_gpus(
    provider: str | None = None,
) -> list[GPUInfoResponse]:
    """List available GPU types from cloud providers."""
    if provider:
        p = cloud_manager.get_provider(provider)
        if not p:
            raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")
        
        gpus = await p.list_available_gpus()
        return [
            GPUInfoResponse(
                provider=provider,
                gpu_type=g.gpu_type,
                name=g.name,
                gpu_count=g.gpu_count,
                memory_gb=g.memory_gb,
                price_per_hour=g.price_per_hour,
                available=g.available,
            )
            for g in gpus
            if g.available
        ]
    
    all_gpus = await cloud_manager.list_all_available_gpus()
    result = []
    for p_name, gpus in all_gpus.items():
        for g in gpus:
            if g.available:
                result.append(GPUInfoResponse(
                    provider=p_name,
                    gpu_type=g.gpu_type,
                    name=g.name,
                    gpu_count=g.gpu_count,
                    memory_gb=g.memory_gb,
                    price_per_hour=g.price_per_hour,
                    available=g.available,
                ))
    
    result.sort(key=lambda x: x.price_per_hour)
    return result


@router.post("/launch", response_model=InstanceResponse)
async def launch_instance(
    request: LaunchInstanceRequest,
    current_user=Depends(get_current_user),
) -> InstanceResponse:
    """Launch a cloud GPU instance.
    
    If provider is specified, launches on that provider.
    Otherwise, launches on the cheapest available option.
    """
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if request.provider:
        p = cloud_manager.get_provider(request.provider)
        if not p:
            raise HTTPException(status_code=404, detail=f"Provider '{request.provider}' not found")
        
        from deepiri_zepgpu.cloud.providers.base import LaunchConfig
        config = LaunchConfig(
            name=request.name,
            gpu_type_id=request.gpu_type or "",
            count=request.gpu_count,
            max_price_per_hour=request.max_price_per_hour,
            image=request.image,
            env=request.env,
        )
        
        try:
            instance = await p.launch_instance(config)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to launch instance: {str(e)}")
        
        return InstanceResponse(
            instance_id=instance.instance_id,
            provider=request.provider,
            provider_instance_id=instance.provider_instance_id,
            status=instance.status.value,
            gpu_type=instance.gpu_type,
            gpu_count=instance.gpu_count,
            memory_gb=instance.memory_gb,
            price_per_hour=instance.price_per_hour,
            endpoint=instance.endpoint,
            created_at=instance.created_at.isoformat(),
        )
    
    result = await cloud_manager.launch_on_cheapest(
        gpu_type=request.gpu_type,
        count=request.gpu_count,
        max_price=request.max_price_per_hour,
        name=request.name,
    )
    
    if not result:
        raise HTTPException(status_code=500, detail="Failed to launch instance on any provider")
    
    provider_name, instance = result
    return InstanceResponse(
        instance_id=instance.instance_id,
        provider=provider_name,
        provider_instance_id=instance.provider_instance_id,
        status=instance.status.value,
        gpu_type=instance.gpu_type,
        gpu_count=instance.gpu_count,
        memory_gb=instance.memory_gb,
        price_per_hour=instance.price_per_hour,
        endpoint=instance.endpoint,
        created_at=instance.created_at.isoformat(),
    )


@router.get("/instances/{provider}/{instance_id}", response_model=InstanceResponse)
async def get_instance(
    provider: str,
    instance_id: str,
) -> InstanceResponse:
    """Get details of a cloud instance."""
    p = cloud_manager.get_provider(provider)
    if not p:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")
    
    instance = await p.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    return InstanceResponse(
        instance_id=instance.instance_id,
        provider=provider,
        provider_instance_id=instance.provider_instance_id,
        status=instance.status.value,
        gpu_type=instance.gpu_type,
        gpu_count=instance.gpu_count,
        memory_gb=instance.memory_gb,
        price_per_hour=instance.price_per_hour,
        endpoint=instance.endpoint,
        created_at=instance.created_at.isoformat() if instance.created_at else "",
    )


@router.post("/instances/{provider}/{instance_id}/stop")
async def stop_instance(
    provider: str,
    instance_id: str,
) -> dict[str, Any]:
    """Stop a cloud instance."""
    p = cloud_manager.get_provider(provider)
    if not p:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")
    
    success = await p.stop_instance(instance_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop instance")
    
    return {"status": "stopped", "provider": provider, "instance_id": instance_id}


@router.post("/instances/{provider}/{instance_id}/start")
async def start_instance(
    provider: str,
    instance_id: str,
) -> InstanceResponse:
    """Start a stopped cloud instance."""
    p = cloud_manager.get_provider(provider)
    if not p:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")
    
    try:
        instance = await p.start_instance(instance_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    return InstanceResponse(
        instance_id=instance.instance_id,
        provider=provider,
        provider_instance_id=instance.provider_instance_id,
        status=instance.status.value,
        gpu_type=instance.gpu_type,
        gpu_count=instance.gpu_count,
        memory_gb=instance.memory_gb,
        price_per_hour=instance.price_per_hour,
        endpoint=instance.endpoint,
        created_at=instance.created_at.isoformat() if instance.created_at else "",
    )


@router.delete("/instances/{provider}/{instance_id}")
async def delete_instance(
    provider: str,
    instance_id: str,
) -> dict[str, Any]:
    """Delete a cloud instance."""
    p = cloud_manager.get_provider(provider)
    if not p:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not found")
    
    success = await p.delete_instance(instance_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete instance")
    
    return {"status": "deleted", "provider": provider, "instance_id": instance_id}


@router.get("/costs/{gpu_type}", response_model=list[CostEstimateResponse])
async def compare_costs(
    gpu_type: str,
    hours: int = 1,
) -> list[CostEstimateResponse]:
    """Compare costs for a GPU type across all providers."""
    estimates = await cloud_manager.compare_costs(gpu_type, hours)
    
    return [
        CostEstimateResponse(
            provider=e.provider_type.value,
            gpu_type=e.gpu_type,
            gpu_count=e.gpu_count,
            price_per_hour=e.price_per_hour,
            estimated_monthly_cost=e.estimated_monthly_cost,
            currency=e.currency,
        )
        for e in estimates
    ]


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Check health of all cloud providers."""
    status = await cloud_manager.get_health_status()
    
    all_healthy = all(s.get("status") == "healthy" for s in status.values())
    
    return {
        "status": "healthy" if all_healthy else "degraded",
        "providers": status,
    }
