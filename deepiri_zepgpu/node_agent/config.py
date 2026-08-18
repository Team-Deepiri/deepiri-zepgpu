"""Node agent configuration loading and validation."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field, field_validator

from deepiri_zepgpu import __version__ as PACKAGE_VERSION

_REDACTED = "***REDACTED***"
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_AUTH_TOKEN_ENCRYPTED_KEY = "auth_token_encrypted"

DEFAULT_AGENT_DIR = Path.home() / ".zepgpu"
DEFAULT_AGENT_CONFIG_PATH = DEFAULT_AGENT_DIR / "agent.json"
DEFAULT_AGENT_KEY_PATH = DEFAULT_AGENT_DIR / "agent.key"
AGENT_VERSION = PACKAGE_VERSION


class NodeAgentConfig(BaseModel):
    api_base_url: str
    room_id: str
    peer_id: str
    auth_token: str
    heartbeat_interval_seconds: int = Field(default=10, ge=1)
    task_poll_interval_seconds: int = Field(default=5, ge=1)
    task_poll_limit: int = Field(default=1, ge=1, le=10)
    enable_task_worker: bool = False
    simulation_mode: bool = False
    endpoint: str | None = None
    node_name: str | None = None
    provider_mode: str = "dialout"
    agent_version: str = AGENT_VERSION
    token_expires_at: str | None = None
    transport_mode: str | None = None
    vpn_ip: str | None = None
    wireguard_interface: str | None = None
    wireguard_mock: bool = False

    @field_validator("api_base_url")
    @classmethod
    def validate_api_base_url(cls, value: str) -> str:
        return validate_coordinator_url(value)

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


def validate_coordinator_url(value: str, *, allow_insecure_localhost: bool = True) -> str:
    """Reject non-HTTPS coordinator URLs outside localhost/dev."""

    value = value.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise ValueError("coordinator URL must start with http:// or https://")

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if value.startswith("https://"):
        return value

    localhost_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    is_local = host in localhost_hosts or host.endswith(".localhost")
    if allow_insecure_localhost and is_local:
        return value

    raise ValueError(
        "Non-HTTPS coordinator URLs are only allowed for localhost/dev " f"(got host={host!r})"
    )


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
        "NODE_AGENT_TASK_POLL_LIMIT": "task_poll_limit",
        "NODE_AGENT_ENABLE_TASK_WORKER": "enable_task_worker",
        "NODE_AGENT_SIMULATION_MODE": "simulation_mode",
        "NODE_AGENT_ENDPOINT": "endpoint",
        "NODE_AGENT_NODE_NAME": "node_name",
        "NODE_AGENT_PROVIDER_MODE": "provider_mode",
        "NODE_AGENT_VERSION": "agent_version",
        "NODE_AGENT_TOKEN_EXPIRES_AT": "token_expires_at",
    }
    merged = dict(data)
    for env_key, field_name in env_map.items():
        raw = os.environ.get(env_key)
        if raw is None or raw == "":
            continue
        if field_name in {
            "heartbeat_interval_seconds",
            "task_poll_interval_seconds",
            "task_poll_limit",
        }:
            merged[field_name] = int(raw)
        elif field_name in {"simulation_mode", "enable_task_worker"}:
            merged[field_name] = _parse_bool(raw)
        else:
            merged[field_name] = raw
    return merged


def default_agent_path() -> Path:
    return Path(os.environ.get("ZEPGPU_AGENT_CONFIG", str(DEFAULT_AGENT_CONFIG_PATH))).expanduser()


def default_agent_key_path(config_path: Path | None = None) -> Path:
    """Local AES key lives next to agent.json (or under default ~/.zepgpu)."""

    if config_path is not None:
        return config_path.expanduser().parent / "agent.key"
    override = os.environ.get("ZEPGPU_AGENT_KEY")
    if override:
        return Path(override).expanduser()
    return DEFAULT_AGENT_KEY_PATH.expanduser()


def _load_or_create_agent_key(key_path: Path) -> bytes:
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        raw = key_path.read_bytes().strip()
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception:
            key = raw
        if len(key) != 32:
            raise ValueError(f"Agent key at {key_path} must be 32 bytes")
        return key

    key = os.urandom(32)
    key_path.write_bytes(base64.b64encode(key) + b"\n")
    with contextlib.suppress(OSError):
        key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return key


def _encrypt_auth_token(plaintext: str, *, key_path: Path) -> str:
    key = _load_or_create_agent_key(key_path)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def _decrypt_auth_token(encoded: str, *, key_path: Path) -> str:
    key = _load_or_create_agent_key(key_path)
    data = base64.b64decode(encoded)
    if len(data) < 13:
        raise ValueError("auth_token_encrypted is truncated")
    nonce, ciphertext = data[:12], data[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")


def _resolve_auth_token(payload: dict[str, Any], *, key_path: Path) -> dict[str, Any]:
    """Decrypt auth_token_encrypted when present; keep legacy plaintext auth_token."""

    data = dict(payload)
    encrypted = data.pop(_AUTH_TOKEN_ENCRYPTED_KEY, None)
    if isinstance(encrypted, str) and encrypted.strip():
        data["auth_token"] = _decrypt_auth_token(encrypted.strip(), key_path=key_path)
    return data


def load_config_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser()
    with config_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Config file must contain a JSON object")
    return _resolve_auth_token(payload, key_path=default_agent_key_path(config_path))


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


def load_agent_identity(path: str | Path | None = None) -> NodeAgentConfig:
    """Load persisted provider identity from ~/.zepgpu/agent.json."""

    config_path = Path(path).expanduser() if path else default_agent_path()
    if not config_path.exists():
        raise FileNotFoundError(f"No agent identity at {config_path}; run `zepgpu-node join` first")
    return build_config(config_path=config_path)


def save_agent_identity(
    config: NodeAgentConfig,
    path: str | Path | None = None,
) -> Path:
    """Persist provider identity with auth_token encrypted at rest."""

    config_path = Path(path).expanduser() if path else default_agent_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    key_path = default_agent_key_path(config_path)
    payload = config.model_dump()
    token = str(payload.pop("auth_token"))
    payload[_AUTH_TOKEN_ENCRYPTED_KEY] = _encrypt_auth_token(token, key_path=key_path)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with contextlib.suppress(OSError):
        config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return config_path


def clear_agent_identity(path: str | Path | None = None) -> bool:
    """Remove local credentials (logout/reset)."""

    config_path = Path(path).expanduser() if path else default_agent_path()
    key_path = default_agent_key_path(config_path)
    removed = False
    if config_path.exists():
        config_path.unlink()
        removed = True
    if key_path.exists():
        key_path.unlink()
        removed = True
    try:
        from deepiri_zepgpu.node_agent.inflight import clear_inflight, default_inflight_path

        inflight = default_inflight_path()
        if path is not None:
            inflight = Path(path).expanduser().parent / "inflight.json"
        if inflight.exists():
            clear_inflight(inflight)
            removed = True
    except Exception:
        pass
    return removed


def identity_status_dict(
    config: NodeAgentConfig,
    *,
    probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Redacted status payload for `zepgpu-node status`."""

    status = config.redacted_dict()
    if config.transport_mode == "wireguard":
        if config.wireguard_mock:
            status["tunnel_state"] = "mock"
        elif config.wireguard_interface:
            status["tunnel_state"] = "up"
        else:
            status["tunnel_state"] = "exported_conf"
    elif config.transport_mode == "overlay":
        status["tunnel_state"] = "overlay"
    else:
        status["tunnel_state"] = "dialout"
    if config.token_expires_at:
        try:
            expires = datetime.fromisoformat(config.token_expires_at.replace("Z", "+00:00"))
            status["token_expired"] = datetime.now(expires.tzinfo) > expires
        except ValueError:
            status["token_expired"] = None
    if probe is not None:
        status["coordinator_probe"] = probe
    return status


def validate_room_id(value: str) -> UUID:
    return UUID(value)
