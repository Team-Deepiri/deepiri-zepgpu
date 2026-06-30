"""Tests for node agent configuration."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from deepiri_zepgpu.node_agent.config import NodeAgentConfig, build_config


def test_loads_json_config(tmp_path: Path) -> None:
    config_file = tmp_path / "node-agent.json"
    config_file.write_text(
        json.dumps(
            {
                "api_base_url": "http://localhost:8000",
                "room_id": "22222222-2222-4222-8222-222222222222",
                "peer_id": "33333333-3333-4333-8333-333333333333",
                "auth_token": "secret-token",
                "heartbeat_interval_seconds": 15,
            }
        ),
        encoding="utf-8",
    )

    config = build_config(config_path=config_file)
    assert config.api_base_url == "http://localhost:8000"
    assert config.heartbeat_interval_seconds == 15


def test_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_file = tmp_path / "node-agent.json"
    config_file.write_text(
        json.dumps(
            {
                "api_base_url": "http://localhost:8000",
                "room_id": "22222222-2222-4222-8222-222222222222",
                "peer_id": "33333333-3333-4333-8333-333333333333",
                "auth_token": "secret-token",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NODE_AGENT_HEARTBEAT_INTERVAL_SECONDS", "20")
    monkeypatch.setenv("NODE_AGENT_SIMULATION_MODE", "true")

    config = build_config(config_path=config_file)
    assert config.heartbeat_interval_seconds == 20
    assert config.simulation_mode is True


def test_rejects_invalid_url() -> None:
    with pytest.raises(Exception):
        NodeAgentConfig.model_validate(
            {
                "api_base_url": "not-a-url",
                "room_id": "22222222-2222-4222-8222-222222222222",
                "peer_id": "33333333-3333-4333-8333-333333333333",
                "auth_token": "secret-token",
            }
        )


def test_repr_and_logs_never_contain_raw_token(caplog: pytest.LogCaptureFixture) -> None:
    config = NodeAgentConfig(
        api_base_url="http://localhost:8000",
        room_id="22222222-2222-4222-8222-222222222222",
        peer_id="33333333-3333-4333-8333-333333333333",
        auth_token="super-secret-token",
    )

    rendered = repr(config)
    assert "super-secret-token" not in rendered
    assert "***REDACTED***" in rendered

    with caplog.at_level(logging.INFO):
        logging.info("Config: %s", config)
    assert "super-secret-token" not in caplog.text
