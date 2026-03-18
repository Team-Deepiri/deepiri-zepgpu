"""Configuration management."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
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
    
    url: str = Field(default="redis://localhost:6379/0")
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/2")


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
    
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    workers: int = Field(default=4)
    reload: bool = Field(default=False)
    debug: bool = Field(default=False)
    title: str = Field(default="DeepIRI ZepGPU API")
    description: str = Field(default="Serverless GPU Framework")
    version: str = Field(default="0.1.0")


class GPUSettings(BaseSettings):
    """GPU configuration."""
    
    visible_devices: str = Field(default="0,1")
    memory_reserve_mb: int = Field(default=1024)
    monitor_interval_seconds: float = Field(default=5.0)
    enable_nvml: bool = Field(default=True)


class AuthSettings(BaseSettings):
    """Authentication configuration."""
    
    secret_key: str = Field(default="changeme-in-production")
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=1440)
    refresh_token_expire_days: int = Field(default=7)


class Settings(BaseSettings):
    """Main settings class."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    api: APISettings = Field(default_factory=APISettings)
    gpu: GPUSettings = Field(default_factory=GPUSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    
    app_name: str = Field(default="zepgpu")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    environment: Literal["development", "staging", "production"] = Field(default="development")
    
    max_concurrent_tasks: int = Field(default=10)
    default_timeout_seconds: int = Field(default=3600)
    default_gpu_memory_mb: int = Field(default=1024)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
