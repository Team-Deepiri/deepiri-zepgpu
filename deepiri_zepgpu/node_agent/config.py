"""Node agent configuration loading and validation."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_REDACTED = "***REDACTED***"
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class NodeAgentConfig(BaseModel):
    api_base_url: str
    room_id: str
    peer_id: str
    auth_token: str
    heartbeat_interval_seconds: int = Field(default=10, ge=1)
    task_poll_interval_seconds: int = Field(default=5, ge=1)
    enable_task_worker: bool = False
    simulation_mode: bool = False
    endpoint: str | None = None

    @field_validator("api_base_url")
    @classmethod
    def validate_api_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("api_base_url must start with http:// or https://")
        return value

    @field_validator("room_id", "peer_id")
    @classmethod
    def validate_uuid(cls, value: str) -> str:
        if not _UUID_PATTERN.match(value.strip()):
            raise ValueError(f"Invalid UUID: {value}")
        return value.strip()

    @field_validator("auth_token")
    @classmethod
    def validate_auth_token(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("auth_token must not be empty")
        return token

    def redacted_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        data["auth_token"] = _REDACTED
        return data

    def __repr__(self) -> str:
        return f"NodeAgentConfig({self.redacted_dict()})"

    def __str__(self) -> str:
        return self.__repr__()


def _parse_bool(raw: str) -> bool:
    return raw.lower() in ("1", "true", "yes", "on")


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    env_map = {
        "NODE_AGENT_API_BASE_URL": "api_base_url",
        "NODE_AGENT_ROOM_ID": "room_id",
        "NODE_AGENT_PEER_ID": "peer_id",
        "NODE_AGENT_AUTH_TOKEN": "auth_token",
        "NODE_AGENT_HEARTBEAT_INTERVAL_SECONDS": "heartbeat_interval_seconds",
        "NODE_AGENT_TASK_POLL_INTERVAL_SECONDS": "task_poll_interval_seconds",
        "NODE_AGENT_ENABLE_TASK_WORKER": "enable_task_worker",
        "NODE_AGENT_SIMULATION_MODE": "simulation_mode",
        "NODE_AGENT_ENDPOINT": "endpoint",
    }
    merged = dict(data)
    for env_key, field_name in env_map.items():
        raw = os.environ.get(env_key)
        if raw is None or raw == "":
            continue
        if field_name in {"heartbeat_interval_seconds", "task_poll_interval_seconds"}:
            merged[field_name] = int(raw)
        elif field_name in {"simulation_mode", "enable_task_worker"}:
            merged[field_name] = _parse_bool(raw)
        else:
            merged[field_name] = raw
    return merged


def load_config_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    with config_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Config file must contain a JSON object")
    return payload


def build_config(
    *,
    config_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> NodeAgentConfig:
    data: dict[str, Any] = {}
    if config_path is not None:
        data.update(load_config_file(config_path))
    if overrides:
        data.update({k: v for k, v in overrides.items() if v is not None})
    data = _apply_env_overrides(data)
    return NodeAgentConfig.model_validate(data)


def validate_room_id(value: str) -> UUID:
    return UUID(value)
