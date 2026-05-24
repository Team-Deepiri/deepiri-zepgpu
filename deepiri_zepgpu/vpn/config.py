"""VPN configuration and settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class VPNSettings(BaseSettings):
    """VPN/Peer GPU sharing configuration."""

    relay_host: str = Field(default="localhost")
    relay_port: int = Field(default=51820)
    relay_public_port: int = Field(default=51820)
    vpn_cidr: str = Field(default="10.8.0.0/24")
    vpn_name: str = Field(default="zepgpu-vpn")
    heartbeat_interval_seconds: int = Field(default=30)
    heartbeat_timeout_seconds: int = Field(default=90)
    default_max_gpu_hours_per_day: float = Field(default=4.0)
    default_max_concurrent_tasks: int = Field(default=1)
    peer_server_port: int = Field(default=9092)
    gpu_advertise_port: int = Field(default=9091)
    wg_config_dir: str = Field(default="~/.zepgpu/wireguard")
    invite_code_length: int = Field(default=8)
    invite_expiry_days: int = Field(default=7)
    invite_max_uses: int = Field(default=10)
    relay_api_url: str = Field(default="http://localhost:8000")
    encryption_key: str = Field(default="changeme-vpn-encryption-key")

    model_config = {
        "env_prefix": "VPN_",
        "extra": "ignore",
    }

    def get_config_dir(self) -> Path:
        return Path(self.wg_config_dir).expanduser()


@lru_cache()
def get_vpn_settings() -> VPNSettings:
    return VPNSettings()


vpn_settings = get_vpn_settings()
