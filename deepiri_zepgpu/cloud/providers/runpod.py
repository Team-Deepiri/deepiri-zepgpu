"""RunPod cloud provider implementation."""

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


@register_provider(CloudProviderType.RUNPOD)
class RunPodProvider(CloudProvider):
    """RunPod cloud GPU provider."""
    
    provider_type = CloudProviderType.RUNPOD
    provider_name = "RunPod"
    
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.endpoint = config.get("endpoint", "https://api.runpod.io/graphql")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    async def list_available_gpus(self) -> list[GPUInfo]:
        """List available GPU types from RunPod."""
        query = """
        query CloudGpuTypes {
            gpuTypes {
                id
                displayName
                memoryInGb
                lowestPrice {
                    minimumBidPrice
                    uninterruptablePrice
                }
                gpuCount
                manufacturer
            }
        }
        """
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.endpoint,
                    json={"query": query},
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                
                gpus = []
                for gpu in data.get("data", {}).get("gpuTypes", []):
                    price = gpu.get("lowestPrice", {})
                    gpus.append(GPUInfo(
                        provider_instance_id=gpu["id"],
                        name=gpu["displayName"],
                        gpu_type=gpu["id"],
                        gpu_count=gpu.get("gpuCount", 1),
                        memory_gb=gpu.get("memoryInGb", 0),
                        price_per_hour=price.get("uninterruptablePrice", 0) or price.get("minimumBidPrice", 0),
                        available=True,
                    ))
                return gpus
        except Exception:
            return []
    
    async def launch_instance(self, config: LaunchConfig) -> Instance:
        """Launch a RunPod GPU instance."""
        mutation = """
        mutation ContainerRuntime_Launch($input: ContainerInput!) {
            containerLaunch(input: $input) {
                id
                status
                runtime
                containerUri
            }
        }
        """
        
        variables = {
            "input": {
                "gpuTypeId": config.gpu_type_id,
                "containerDiskInGb": 50,
                "minMemoryInGb": config.memory_gb or 30,
                "minVcpuCount": config.cpu_count or 4,
                "dockerArgs": config.docker_args or "",
                " env": config.env or {},
                "imageName": config.image,
                "name": config.name,
                "startSsh": True,
            }
        }
        
        if config.max_price_per_hour:
            variables["input"]["maxBidPrice"] = config.max_price_per_hour
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.endpoint,
                    json={"query": mutation, "variables": variables},
                    headers=self.headers,
                    timeout=60.0,
                )
                response.raise_for_status()
                data = response.json()
                
                result = data.get("data", {}).get("containerLaunch", {})
                return Instance(
                    instance_id=result.get("id", ""),
                    provider_type=self.provider_type,
                    provider_instance_id=result.get("id", ""),
                    status=InstanceStatus.PENDING,
                    gpu_type=config.gpu_type_id,
                    gpu_count=config.count,
                    memory_gb=config.memory_gb or 30,
                    price_per_hour=config.max_price_per_hour or 0,
                    endpoint=result.get("containerUri"),
                )
        except Exception as e:
            raise RuntimeError(f"Failed to launch RunPod instance: {e}")
    
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop a RunPod instance."""
        mutation = """
        mutation ContainerRuntime_Terminate($input: ContainerTerminationInput!) {
            containerTerminate(input: $input) {
                status
            }
        }
        """
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.endpoint,
                    json={"query": mutation, "variables": {"input": {"containerId": instance_id}}},
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return True
        except Exception:
            return False
    
    async def start_instance(self, instance_id: str) -> Instance:
        """Start a stopped RunPod instance."""
        raise NotImplementedError("RunPod instances cannot be restarted after stopping")
    
    async def get_instance(self, instance_id: str) -> Instance | None:
        """Get RunPod instance details."""
        query = """
        query ContainerStatus($id: String!) {
            containerStatus(id: $id) {
                id
                status
                runtime
                containerUri
                gpuCount
                costPerHr
            }
        }
        """
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.endpoint,
                    json={"query": query, "variables": {"id": instance_id}},
                    headers=self.headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
                
                container = data.get("data", {}).get("containerStatus", {})
                if not container:
                    return None
                
                status_map = {
                    "PAUSED": InstanceStatus.STOPPED,
                    "EXITED": InstanceStatus.STOPPED,
                    "RUNNING": InstanceStatus.RUNNING,
                    "STARTING": InstanceStatus.STARTING,
                }
                
                return Instance(
                    instance_id=container.get("id", ""),
                    provider_type=self.provider_type,
                    provider_instance_id=container.get("id", ""),
                    status=status_map.get(container.get("status", ""), InstanceStatus.PENDING),
                    gpu_type="",
                    gpu_count=container.get("gpuCount", 0),
                    memory_gb=0,
                    price_per_hour=container.get("costPerHr", 0) or 0,
                    endpoint=container.get("containerUri"),
                )
        except Exception:
            return None
    
    async def delete_instance(self, instance_id: str) -> bool:
        """Delete a RunPod instance."""
        return await self.stop_instance(instance_id)
    
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
        """Get RunPod API health status."""
        query = """
        query {
            myself {
                id
            }
        }
        """
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.endpoint,
                    json={"query": query},
                    headers=self.headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                return {"status": "healthy", "provider": self.provider_name}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e), "provider": self.provider_name}
    
    def supports_auto_scaling(self) -> bool:
        """RunPod supports auto-scaling."""
        return True
    
    def supports_spot_instances(self) -> bool:
        """RunPod supports spot instances via bid pricing."""
        return True
