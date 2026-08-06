"""Configuration management."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration."""

    url: str = Field(default="postgresql+asyncpg://zepgpu:zepgpu@zepgpu-db:5432/zepgpu")
    sync_url: str = Field(default="postgresql://zepgpu:zepgpu@zepgpu-db:5432/zepgpu")
    pool_size: int = Field(default=10)
    max_overflow: int = Field(default=20)
    echo: bool = Field(default=False)


class RedisSettings(BaseSettings):
    """Redis configuration."""

    url: str = Field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    celery_broker_url: str = Field(
        default_factory=lambda: os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
    )
    celery_result_backend: str = Field(
        default_factory=lambda: os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
    )
    training_relay_ttl_seconds: int = Field(default=300, ge=30, le=86400)
    training_relay_max_transfer_bytes: int = Field(default=64 * 1024 * 1024, ge=1024)
    training_relay_max_chunk_bytes: int = Field(default=4 * 1024 * 1024, ge=1024)


class S3Settings(BaseSettings):
    """S3/MinIO configuration."""

    endpoint_url: str = Field(default="http://localhost:9000")
    access_key: str = Field(default="minioadmin")
    secret_key: str = Field(default="minioadmin")
    bucket_name: str = Field(default="deepiri-results")
    region: str = Field(default="us-east-1")
    presigned_expiry_seconds: int = Field(default=3600)


class APISettings(BaseSettings):
    """API server configuration."""

    model_config = SettingsConfigDict(env_prefix="ZEPGPU_API_", extra="ignore")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    workers: int = Field(default=4)
    reload: bool = Field(default=False)
    debug: bool = Field(default=False)
    title: str = Field(default="DeepIRI ZepGPU API")
    description: str = Field(default="Serverless GPU Framework")
    version: str = Field(default="0.1.0")
    coordinator_public_url: str = Field(default="http://localhost:8000")
    cors_origins: str = Field(default="http://localhost:3000,http://localhost:5173")

    def parsed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


class GPUSettings(BaseSettings):
    """GPU configuration."""

    visible_devices: str = Field(default="0,1")
    memory_reserve_mb: int = Field(default=1024)
    monitor_interval_seconds: float = Field(default=5.0)
    enable_nvml: bool = Field(default=True)


class AuthSettings(BaseSettings):
    """Authentication configuration."""

    # ≥32 bytes so HS256 (PyJWT) does not warn; override in every real deployment.
    secret_key: str = Field(default="changeme-in-production-use-a-real-secret")
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=1440)
    refresh_token_expire_days: int = Field(default=7)


class ScheduleSettings(BaseSettings):
    """Scheduled task configuration."""

    beat_schedule_db: str = Field(
        default_factory=lambda: os.getenv("CELERY_BEAT_SCHEDULE_DB", "redis://localhost:6379/3")
    )
    beat_sync_interval_seconds: int = Field(default=60)
    max_consecutive_failures: int = Field(default=5)
    default_schedule_enabled: bool = Field(default=True)


class CloudSettings(BaseSettings):
    """Cloud provider configuration."""

    enabled: bool = Field(default=False)
    auto_scale: bool = Field(default=False)
    max_cloud_gpus: int = Field(default=8)
    default_max_price: float | None = Field(default=None)
    providers: dict = Field(default_factory=dict)


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
    provider_token_expire_days: int = Field(default=90)
    default_provider_mode: str = Field(default="dialout")
    # New cloud rooms default to dial-out; existing DB rows stay wireguard via migration.
    default_transport_mode: str = Field(default="dialout")
    # Soft minimum agent version for "incompatible" health (empty = skip check).
    min_compatible_agent_version: str = Field(default="")
    # Phase 13 assignment lease / timeout controls (seconds).
    assignment_lease_seconds: int = Field(default=300, ge=30)
    accepted_start_timeout_seconds: int = Field(default=120, ge=10)
    # When None, running timeout falls back to the parent task.timeout_seconds.
    running_timeout_seconds: int | None = Field(default=None)
    assignment_sweep_interval_seconds: int = Field(default=30, ge=5)


class LedgerSettings(BaseSettings):
    """Permissioned compute ledger (PoA) configuration."""

    enabled: bool = Field(default=True)
    chain_id: str = Field(default="zepgpu-compute-v1")
    auto_seal: bool = Field(default=True)
    # Raw URL-safe base64 Ed25519 private key. If empty, derived from auth.secret_key.
    validator_private_key: str = Field(default="")
    record_local_completions: bool = Field(default=True)
    # Week 2: multi-validator quorum (1 = single-relay week-1 behavior)
    quorum_threshold: int = Field(default=1)
    # Comma-separated extra Ed25519 private keys for additional PoA validators (dev/demo)
    extra_validator_private_keys: str = Field(default="")
    # Auto-create per-VPN-network chains on network create
    isolate_vpn_networks: bool = Field(default=True)


class Settings(BaseSettings):
    """Main settings class."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",
    )

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    api: APISettings = Field(default_factory=APISettings)
    gpu: GPUSettings = Field(default_factory=GPUSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    schedule: ScheduleSettings = Field(default_factory=ScheduleSettings)
    cloud: CloudSettings = Field(default_factory=CloudSettings)
    vpn: VPNSettings = Field(default_factory=VPNSettings)
    ledger: LedgerSettings = Field(default_factory=LedgerSettings)

    app_name: str = Field(default="zepgpu")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    environment: Literal["development", "staging", "production"] = Field(default="development")

    max_concurrent_tasks: int = Field(default=10)
    default_timeout_seconds: int = Field(default=3600)
    default_gpu_memory_mb: int = Field(default=1024)

    task_callback_allowed_hosts: str = Field(default="")
    task_callback_allow_localhost: bool = Field(default=False)
    task_callback_connect_timeout_seconds: float = Field(default=2.0, ge=0.1, le=10.0)
    task_callback_read_timeout_seconds: float = Field(default=5.0, ge=0.1, le=15.0)
    task_callback_write_timeout_seconds: float = Field(default=5.0, ge=0.1, le=15.0)
    task_callback_pool_timeout_seconds: float = Field(default=2.0, ge=0.1, le=10.0)

    def parsed_task_callback_allowed_hosts(self) -> tuple[str, ...]:
        """Return the configured exact or wildcard callback host allowlist."""
        return tuple(
            host.strip() for host in self.task_callback_allowed_hosts.split(",") if host.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
