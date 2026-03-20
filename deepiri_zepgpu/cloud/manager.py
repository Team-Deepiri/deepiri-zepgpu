"""Cloud GPU manager for orchestrating multiple providers."""

from __future__ import annotations

import logging
from typing import Any

from deepiri_zepgpu.cloud.providers.base import (
    CloudProvider,
    CloudProviderType,
    CloudProviderRegistry,
    GPUInfo,
    Instance,
    LaunchConfig,
    CostEstimate,
)

from deepiri_zepgpu.cloud.providers.runpod import RunPodProvider
from deepiri_zepgpu.cloud.providers.lambda_labs import LambdaLabsProvider
from deepiri_zepgpu.cloud.providers.aws import AWSProvider

logger = logging.getLogger(__name__)


class CloudGPUManager:
    """Manager for cloud GPU resources across multiple providers."""
    
    def __init__(self):
        self._providers: dict[str, CloudProvider] = {}
        self._initialized = False
    
    def initialize(self, configs: dict[str, dict[str, Any]]) -> None:
        """Initialize cloud providers from configs.
        
        Args:
            configs: Dict mapping provider names to their config dicts.
                    Example: {"runpod": {"api_key": "xxx"}, "aws": {"region": "us-east-1"}}
        """
        for name, config in configs.items():
            provider_type = self._get_provider_type(name)
            if provider_type:
                try:
                    provider = CloudProviderRegistry.create(provider_type, config)
                    self._providers[name] = provider
                    logger.info(f"Initialized cloud provider: {name} ({provider_type.value})")
                except Exception as e:
                    logger.warning(f"Failed to initialize provider {name}: {e}")
        
        self._initialized = True
    
    def _get_provider_type(self, name: str) -> CloudProviderType | None:
        """Map provider name to type."""
        mapping = {
            "runpod": CloudProviderType.RUNPOD,
            "aws": CloudProviderType.AWS,
            "ec2": CloudProviderType.AWS,
            "lambda": CloudProviderType.LAMBDA_LABS,
            "lambda_labs": CloudProviderType.LAMBDA_LABS,
        }
        return mapping.get(name.lower())
    
    def get_provider(self, name: str) -> CloudProvider | None:
        """Get a provider by name."""
        return self._providers.get(name)
    
    def list_providers(self) -> list[dict[str, Any]]:
        """List all configured providers."""
        return [
            {
                "name": name,
                "type": p.provider_type.value,
                "display_name": p.provider_name,
            }
            for name, p in self._providers.items()
        ]
    
    async def list_all_available_gpus(self) -> dict[str, list[GPUInfo]]:
        """List available GPUs from all providers."""
        results = {}
        for name, provider in self._providers.items():
            try:
                gpus = await provider.list_available_gpus()
                results[name] = gpus
            except Exception as e:
                logger.warning(f"Failed to list GPUs from {name}: {e}")
                results[name] = []
        return results
    
    async def get_cheapest_gpus(self, min_count: int = 1) -> list[tuple[str, GPUInfo]]:
        """Get cheapest available GPUs across all providers."""
        all_gpus = []
        
        for name, provider in self._providers.items():
            try:
                gpus = await provider.list_available_gpus()
                for gpu in gpus:
                    if gpu.available and gpu.gpu_count >= min_count:
                        all_gpus.append((name, gpu))
            except Exception:
                continue
        
        all_gpus.sort(key=lambda x: x[1].price_per_hour)
        return all_gpus
    
    async def launch_on_cheapest(
        self,
        gpu_type: str | None = None,
        count: int = 1,
        max_price: float | None = None,
        name: str = "zepgpu-instance",
    ) -> tuple[str, Instance] | None:
        """Launch instance on cheapest available provider.
        
        Returns:
            Tuple of (provider_name, instance) or None if failed.
        """
        if gpu_type:
            for name, provider in self._providers.items():
                try:
                    gpus = await provider.list_available_gpus()
                    matching = [g for g in gpus if g.gpu_type == gpu_type and g.available]
                    if matching:
                        gpu = matching[0]
                        if max_price and gpu.price_per_hour > max_price:
                            continue
                        
                        config = LaunchConfig(
                            name=name,
                            gpu_type_id=gpu.gpu_type,
                            count=count,
                            max_price_per_hour=max_price,
                        )
                        instance = await provider.launch_instance(config)
                        return name, instance
                except Exception:
                    continue
        
        gpus = await self.get_cheapest_gpus(count)
        for provider_name, gpu in gpus:
            if max_price and gpu.price_per_hour > max_price:
                continue
            
            provider = self._providers[provider_name]
            config = LaunchConfig(
                name=name,
                gpu_type_id=gpu.gpu_type,
                count=count,
                max_price_per_hour=max_price,
            )
            try:
                instance = await provider.launch_instance(config)
                return provider_name, instance
            except Exception as e:
                logger.warning(f"Failed to launch on {provider_name}: {e}")
                continue
        
        return None
    
    async def compare_costs(
        self,
        gpu_type: str,
        hours: int = 1,
    ) -> list[CostEstimate]:
        """Compare costs across all providers for a GPU type."""
        estimates = []
        
        for provider in self._providers.values():
            try:
                estimate = await provider.get_cost_estimate(gpu_type, hours)
                estimates.append(estimate)
            except Exception:
                continue
        
        estimates.sort(key=lambda x: x.price_per_hour)
        return estimates
    
    async def get_all_instances(self) -> dict[str, list[Instance]]:
        """Get all instances from all providers."""
        results = {}
        for name, provider in self._providers.items():
            try:
                status = await provider.get_status()
                if status.get("status") == "healthy":
                    results[name] = []
            except Exception:
                continue
        return results
    
    async def get_health_status(self) -> dict[str, dict[str, Any]]:
        """Get health status of all providers."""
        status = {}
        for name, provider in self._providers.items():
            try:
                provider_status = await provider.get_status()
                status[name] = provider_status
            except Exception as e:
                status[name] = {"status": "unhealthy", "error": str(e)}
        return status


cloud_manager = CloudGPUManager()
