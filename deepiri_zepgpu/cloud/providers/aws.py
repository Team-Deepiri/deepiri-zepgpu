"""AWS EC2 GPU provider implementation."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import ClientError

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


AWS_GPU_INSTANCE_TYPES = {
    "g4dn.xlarge": {"name": "NVIDIA T4", "gpu_count": 1, "memory_gb": 16},
    "g4dn.2xlarge": {"name": "NVIDIA T4", "gpu_count": 1, "memory_gb": 32},
    "g4dn.4xlarge": {"name": "NVIDIA T4", "gpu_count": 1, "memory_gb": 64},
    "g4dn.8xlarge": {"name": "NVIDIA T4", "gpu_count": 1, "memory_gb": 32},
    "g4dn.16xlarge": {"name": "NVIDIA T4", "gpu_count": 4, "memory_gb": 64},
    "p3.2xlarge": {"name": "NVIDIA V100", "gpu_count": 1, "memory_gb": 61},
    "p3.8xlarge": {"name": "NVIDIA V100", "gpu_count": 4, "memory_gb": 244},
    "p3.16xlarge": {"name": "NVIDIA V100", "gpu_count": 8, "memory_gb": 488},
    "p4d.24xlarge": {"name": "NVIDIA A100", "gpu_count": 8, "memory_gb": 1152},
    "g5.xlarge": {"name": "NVIDIA A10G", "gpu_count": 1, "memory_gb": 16},
    "g5.2xlarge": {"name": "NVIDIA A10G", "gpu_count": 1, "memory_gb": 32},
    "g5.4xlarge": {"name": "NVIDIA A10G", "gpu_count": 1, "memory_gb": 64},
    "g5.8xlarge": {"name": "NVIDIA A10G", "gpu_count": 1, "memory_gb": 128},
    "g5.16xlarge": {"name": "NVIDIA A10G", "gpu_count": 4, "memory_gb": 256},
    "g5.48xlarge": {"name": "NVIDIA A10G", "gpu_count": 8, "memory_gb": 1152},
}


@register_provider(CloudProviderType.AWS)
class AWSProvider(CloudProvider):
    """AWS EC2 GPU provider."""
    
    provider_type = CloudProviderType.AWS
    provider_name = "AWS EC2"
    
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.region = config.get("region", "us-east-1")
        self.access_key = config.get("aws_access_key_id", "")
        self.secret_key = config.get("aws_secret_access_key", "")
        
        session_kwargs = {"region_name": self.region}
        if self.access_key and self.secret_key:
            session_kwargs["aws_access_key_id"] = self.access_key
            session_kwargs["aws_secret_access_key"] = self.secret_key
        
        self.ec2 = boto3.client("ec2", **session_kwargs)
        self.ec2_resource = boto3.resource("ec2", **session_kwargs)
    
    async def list_available_gpus(self) -> list[GPUInfo]:
        """List available GPU instance types from AWS."""
        gpus = []
        
        for instance_type, specs in AWS_GPU_INSTANCE_TYPES.items():
            try:
                response = self.ec2.describe_instance_types(
                    InstanceTypes=[instance_type]
                )
                instance_data = response.get("InstanceTypes", [{}])[0]
                price = self._get_instance_price(instance_type)
                
                gpus.append(GPUInfo(
                    provider_instance_id=instance_type,
                    name=f"{specs['name']} ({instance_type})",
                    gpu_type=instance_type,
                    gpu_count=specs["gpu_count"],
                    memory_gb=specs["memory_gb"],
                    price_per_hour=price,
                    available=True,
                ))
            except Exception:
                continue
        
        return gpus
    
    def _get_instance_price(self, instance_type: str) -> float:
        """Get on-demand price for instance type."""
        try:
            response = self.ec2.describe_spot_price_history(
                InstanceTypes=[instance_type],
                ProductDescriptions=["Linux/UNIX"],
                MaxResults=1,
            )
            prices = response.get("SpotPriceHistory", [])
            if prices:
                return float(prices[0].get("SpotPrice", 0))
        except Exception:
            pass
        return 0.0
    
    async def launch_instance(self, config: LaunchConfig) -> Instance:
        """Launch an AWS GPU instance."""
        try:
            instance_type = config.gpu_type_id
            specs = AWS_GPU_INSTANCE_TYPES.get(instance_type, {})
            
            instance_params = {
                "ImageId": config.env.get("ami_id", "ami-0c55b159cbfafe1f0") if config.env else "ami-0c55b159cbfafe1f0",
                "InstanceType": instance_type,
                "KeyName": config.env.get("key_name", "") if config.env else "",
                "MinCount": 1,
                "MaxCount": config.count,
                "TagSpecifications": [
                    {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": config.name}]}
                ],
            }
            
            if config.max_price_per_hour:
                instance_params["InstanceMarketOptions"] = {
                    "MarketType": "spot",
                    "SpotOptions": {
                        "MaxPrice": str(config.max_price_per_hour),
                        "InstanceInterruptionBehavior": "terminate",
                    },
                }
            
            response = self.ec2.run_instances(**instance_params)
            instances = response.get("Instances", [])
            
            if not instances:
                raise RuntimeError("Failed to launch instance")
            
            instance_data = instances[0]
            return Instance(
                instance_id=instance_data.get("InstanceId", ""),
                provider_type=self.provider_type,
                provider_instance_id=instance_data.get("InstanceId", ""),
                status=InstanceStatus.PENDING,
                gpu_type=instance_type,
                gpu_count=specs.get("gpu_count", 1),
                memory_gb=specs.get("memory_gb", 0),
                price_per_hour=config.max_price_per_hour or 0,
                endpoint=instance_data.get("PublicIpAddress"),
            )
        except ClientError as e:
            raise RuntimeError(f"Failed to launch AWS instance: {e}")
    
    async def stop_instance(self, instance_id: str) -> bool:
        """Stop an AWS instance."""
        try:
            self.ec2.stop_instances(InstanceIds=[instance_id])
            return True
        except ClientError:
            return False
    
    async def start_instance(self, instance_id: str) -> Instance:
        """Start a stopped AWS instance."""
        try:
            self.ec2.start_instances(InstanceIds=[instance_id])
            return await self.get_instance(instance_id) or Instance(
                instance_id=instance_id,
                provider_type=self.provider_type,
                provider_instance_id=instance_id,
                status=InstanceStatus.STARTING,
                gpu_type="",
                gpu_count=0,
                memory_gb=0,
                price_per_hour=0,
            )
        except ClientError:
            raise RuntimeError(f"Failed to start instance {instance_id}")
    
    async def get_instance(self, instance_id: str) -> Instance | None:
        """Get AWS instance details."""
        try:
            response = self.ec2.describe_instances(InstanceIds=[instance_id])
            reservations = response.get("Reservations", [])
            
            if not reservations:
                return None
            
            instances = reservations[0].get("Instances", [])
            if not instances:
                return None
            
            instance_data = instances[0]
            instance_type = instance_data.get("InstanceType", "")
            specs = AWS_GPU_INSTANCE_TYPES.get(instance_type, {})
            
            status_map = {
                "pending": InstanceStatus.PENDING,
                "running": InstanceStatus.RUNNING,
                "shutting-down": InstanceStatus.STOPPING,
                "stopped": InstanceStatus.STOPPED,
                "stopping": InstanceStatus.STOPPING,
            }
            
            return Instance(
                instance_id=instance_data.get("InstanceId", ""),
                provider_type=self.provider_type,
                provider_instance_id=instance_data.get("InstanceId", ""),
                status=status_map.get(instance_data.get("State", {}).get("Name", ""), InstanceStatus.PENDING),
                gpu_type=instance_type,
                gpu_count=specs.get("gpu_count", 0),
                memory_gb=specs.get("memory_gb", 0),
                price_per_hour=0,
                endpoint=instance_data.get("PublicIpAddress"),
                started_at=instance_data.get("LaunchTime"),
            )
        except ClientError:
            return None
    
    async def delete_instance(self, instance_id: str) -> bool:
        """Delete an AWS instance."""
        try:
            self.ec2.terminate_instances(InstanceIds=[instance_id])
            return True
        except ClientError:
            return False
    
    async def get_cost_estimate(self, gpu_type_id: str, hours: int = 1) -> CostEstimate:
        """Get cost estimate for an instance type."""
        specs = AWS_GPU_INSTANCE_TYPES.get(gpu_type_id, {})
        price_per_hour = self._get_instance_price(gpu_type_id)
        
        return CostEstimate(
            provider_type=self.provider_type,
            gpu_type=gpu_type_id,
            gpu_count=specs.get("gpu_count", 1),
            price_per_hour=price_per_hour,
            estimated_monthly_cost=price_per_hour * 24 * 30 * specs.get("gpu_count", 1),
        )
    
    async def get_status(self) -> dict[str, Any]:
        """Get AWS EC2 health status."""
        try:
            self.ec2.describe_instances(MaxResults=1)
            return {"status": "healthy", "provider": self.provider_name, "region": self.region}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e), "provider": self.provider_name}
    
    def supports_auto_scaling(self) -> bool:
        """AWS supports auto-scaling."""
        return True
    
    def supports_spot_instances(self) -> bool:
        """AWS supports spot instances."""
        return True
