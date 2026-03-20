"""Abstract base classes for cloud GPU providers."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class CloudProviderType(str, Enum):
    """Cloud provider types."""
    RUNPOD = "runpod"
    AWS = "aws"
    LAMBDA_LABS = "lambda_labs"
    VASTAI = "vastai"
    LOCAL = "local"
    CUSTOM = "custom"


class InstanceStatus(str, Enum):
    """Cloud instance status."""
    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class GPUInfo:
    """GPU information from cloud provider."""
    provider_instance_id: str
    name: str
    gpu_type: str
    gpu_count: int
    memory_gb: float
    price_per_hour: float
    datacenter_location: str | None = None
    available: bool = True
    max_price_per_hour: float | None = None


@dataclass
class Instance:
    """Cloud GPU instance."""
    instance_id: str
    provider_type: CloudProviderType
    provider_instance_id: str
    status: InstanceStatus
    gpu_type: str
    gpu_count: int
    memory_gb: float
    price_per_hour: float
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    endpoint: str | None = None
    ssh_key_fingerprint: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LaunchConfig:
    """Configuration for launching a cloud GPU instance."""
    name: str
    gpu_type_id: str
    count: int = 1
    max_price_per_hour: float | None = None
    image: str = "runpod/pytorch:2.1.0-python3.10"
    env: dict[str, str] | None = None
    ports: list[str] | None = None
    volume_mount: str | None = None
    docker_args: str | None = None
    cpu_count: int | None = None
    memory_gb: float | None = None


@dataclass
class CostEstimate:
    """Cost estimate for cloud resources."""
    provider_type: CloudProviderType
    gpu_type: str
    gpu_count: int
    price_per_hour: float
    estimated_monthly_cost: float
    currency: str = "USD"


class CloudProvider(ABC):
    """Abstract base class for cloud GPU providers."""
    
    provider_type: CloudProviderType
    provider_name: str
    
    def __init__(self, config: dict[str, Any]):
        self.config = config
    
    @abstractmethod
    async def list_available_gpus(self) -> list[GPUInfo]:
        """List available GPU instances from provider."""
        pass
    
    @abstractmethod
    async def launch_instance(self, config: LaunchConfig) -> Instance:
        """Launch a new GPU instance."""
        pass
    
    @abstractmethod
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop a GPU instance."""
        pass
    
    @abstractmethod
    async def start_instance(self, instance_id: str) -> Instance:
        """Start a stopped instance."""
        pass
    
    @abstractmethod
    async def get_instance(self, instance_id: str) -> Instance | None:
        """Get instance details."""
        pass
    
    @abstractmethod
    async def delete_instance(self, instance_id: str) -> bool:
        """Delete an instance."""
        pass
    
    @abstractmethod
    async def get_cost_estimate(self, gpu_type_id: str, hours: int = 1) -> CostEstimate:
        """Get cost estimate for a GPU type."""
        pass
    
    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Get provider health/status."""
        pass
    
    def supports_auto_scaling(self) -> bool:
        """Check if provider supports auto-scaling."""
        return False
    
    def supports_spot_instances(self) -> bool:
        """Check if provider supports spot/preemptible instances."""
        return False


class CloudProviderRegistry:
    """Registry for cloud GPU providers."""
    
    _providers: dict[CloudProviderType, type[CloudProvider]] = {}
    _instances: dict[str, CloudProvider] = {}
    
    @classmethod
    def register(cls, provider_type: CloudProviderType, provider_class: type[CloudProvider]) -> None:
        """Register a cloud provider."""
        cls._providers[provider_type] = provider_class
    
    @classmethod
    def create(cls, provider_type: CloudProviderType, config: dict[str, Any]) -> CloudProvider:
        """Create a provider instance."""
        if provider_type not in cls._providers:
            raise ValueError(f"Unknown provider type: {provider_type}")
        
        provider_class = cls._providers[provider_type]
        instance_id = f"{provider_type.value}-{uuid.uuid4().hex[:8]}"
        provider = provider_class(config)
        cls._instances[instance_id] = provider
        return provider
    
    @classmethod
    def get_registered_providers(cls) -> list[CloudProviderType]:
        """Get list of registered provider types."""
        return list(cls._providers.keys())
    
    @classmethod
    def list_instances(cls) -> dict[str, CloudProvider]:
        """List all provider instances."""
        return cls._instances.copy()
    
    @classmethod
    def unregister_instance(cls, instance_id: str) -> None:
        """Unregister a provider instance."""
        cls._instances.pop(instance_id, None)


def register_provider(provider_type: CloudProviderType):
    """Decorator to register a cloud provider."""
    def decorator(cls: type[CloudProvider]) -> type[CloudProvider]:
        CloudProviderRegistry.register(provider_type, cls)
        return cls
    return decorator
