"""Lambda Labs cloud provider implementation."""

from __future__ import annotations

from typing import Any

import httpx

from deepiri_zepgpu.cloud.providers.base import (
    CloudProvider,
    CloudProviderType,
    GPUInfo,
    Instance,
    InstanceStatus,
    LaunchConfig,
    CostEstimate,
    register_provider,
)


@register_provider(CloudProviderType.LAMBDA_LABS)
class LambdaLabsProvider(CloudProvider):
    """Lambda Labs cloud GPU provider."""
    
    provider_type = CloudProviderType.LAMBDA_LABS
    provider_name = "Lambda Labs"
    
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.endpoint = config.get("endpoint", "https://cloud.lambdalabs.com/api/v1")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    async def list_available_gpus(self) -> list[GPUInfo]:
        """List available GPU types from Lambda Labs."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.endpoint}/instance-types",
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                
                gpus = []
                for type_id, type_data in data.get("data", {}).items():
                    gpus.append(GPUInfo(
                        provider_instance_id=type_id,
                        name=type_data.get("instance_type", {}).get("description", type_id),
                        gpu_type=type_id,
                        gpu_count=type_data.get("instance_type", {}).get("specs", {}).get("gpus", 1),
                        memory_gb=type_data.get("instance_type", {}).get("specs", {}).get("memory_gib", 0),
                        price_per_hour=type_data.get("instance_price_cents_per_hour", 0) / 100,
                        available=type_data.get("availability", "") == "available",
                    ))
                return gpus
        except Exception:
            return []
    
    async def launch_instance(self, config: LaunchConfig) -> Instance:
        """Launch a Lambda Labs GPU instance."""
        data = {
            "instance_type_name": config.gpu_type_id,
            "region_name": "us-west-1",
            "ssh_key_names": config.env.get("ssh_key_names", []) if config.env else [],
            "name": config.name,
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.endpoint}/instances",
                    json=data,
                    headers=self.headers,
                    timeout=60.0,
                )
                response.raise_for_status()
                result = response.json()
                
                instance_data = result.get("data", {})
                return Instance(
                    instance_id=instance_data.get("id", ""),
                    provider_type=self.provider_type,
                    provider_instance_id=instance_data.get("id", ""),
                    status=InstanceStatus.PENDING,
                    gpu_type=config.gpu_type_id,
                    gpu_count=config.count,
                    memory_gb=config.memory_gb or 0,
                    price_per_hour=0,
                )
        except Exception as e:
            raise RuntimeError(f"Failed to launch Lambda Labs instance: {e}")
    
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop a Lambda Labs instance."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.endpoint}/instances/{instance_id}/stop",
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return True
        except Exception:
            return False
    
    async def start_instance(self, instance_id: str) -> Instance:
        """Start a stopped Lambda Labs instance."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.endpoint}/instances/{instance_id}/start",
                    headers=self.headers,
                    timeout=60.0,
                )
                response.raise_for_status()
                result = response.json()
                instance_data = result.get("data", {})
                return Instance(
                    instance_id=instance_data.get("id", ""),
                    provider_type=self.provider_type,
                    provider_instance_id=instance_data.get("id", ""),
                    status=InstanceStatus.STARTING,
                    gpu_type=instance_data.get("instance_type", {}).get("name", ""),
                    gpu_count=0,
                    memory_gb=0,
                    price_per_hour=0,
                )
        except Exception as e:
            raise RuntimeError(f"Failed to start Lambda Labs instance: {e}")
    
    async def get_instance(self, instance_id: str) -> Instance | None:
        """Get Lambda Labs instance details."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.endpoint}/instances/{instance_id}",
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                
                instance_data = data.get("data", {})
                status_map = {
                    "pending": InstanceStatus.PENDING,
                    "booting": InstanceStatus.STARTING,
                    "running": InstanceStatus.RUNNING,
                    "stopping": InstanceStatus.STOPPING,
                    "stopped": InstanceStatus.STOPPED,
                    "shutting-down": InstanceStatus.STOPPING,
                    "terminated": InstanceStatus.ERROR,
                }
                
                return Instance(
                    instance_id=instance_data.get("id", ""),
                    provider_type=self.provider_type,
                    provider_instance_id=instance_data.get("id", ""),
                    status=status_map.get(instance_data.get("status", ""), InstanceStatus.PENDING),
                    gpu_type=instance_data.get("instance_type", {}).get("name", ""),
                    gpu_count=0,
                    memory_gb=0,
                    price_per_hour=0,
                    endpoint=instance_data.get("ip", ""),
                )
        except Exception:
            return None
    
    async def delete_instance(self, instance_id: str) -> bool:
        """Delete a Lambda Labs instance."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.endpoint}/instances/{instance_id}",
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return True
        except Exception:
            return False
    
    async def get_cost_estimate(self, gpu_type_id: str, hours: int = 1) -> CostEstimate:
        """Get cost estimate for a GPU type."""
        gpus = await self.list_available_gpus()
        gpu = next((g for g in gpus if g.gpu_type == gpu_type_id), None)
        
        if not gpu:
            return CostEstimate(
                provider_type=self.provider_type,
                gpu_type=gpu_type_id,
                gpu_count=1,
                price_per_hour=0,
                estimated_monthly_cost=0,
            )
        
        return CostEstimate(
            provider_type=self.provider_type,
            gpu_type=gpu_type_id,
            gpu_count=gpu.gpu_count,
            price_per_hour=gpu.price_per_hour,
            estimated_monthly_cost=gpu.price_per_hour * 24 * 30 * gpu.gpu_count,
        )
    
    async def get_status(self) -> dict[str, Any]:
        """Get Lambda Labs API health status."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.endpoint}/users/current",
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                return {"status": "healthy", "provider": self.provider_name}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e), "provider": self.provider_name}
    
    def supports_auto_scaling(self) -> bool:
        """Lambda Labs supports auto-scaling via API."""
        return True
    
    def supports_spot_instances(self) -> bool:
        """Lambda Labs supports spot instances."""
        return True
