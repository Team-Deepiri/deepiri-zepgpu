"""Tests for node agent heartbeat client."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from deepiri_zepgpu.node_agent.config import NodeAgentConfig
from deepiri_zepgpu.node_agent.heartbeat import (
    build_heartbeat_payload,
    heartbeat_url,
    send_heartbeat,
)

CONFIG = NodeAgentConfig(
    api_base_url="http://localhost:8000",
    room_id="22222222-2222-4222-8222-222222222222",
    peer_id="33333333-3333-4333-8333-333333333333",
    auth_token="super-secret-token",
    simulation_mode=True,
)


def test_builds_gpu_status_not_gpus() -> None:
    payload = build_heartbeat_payload(CONFIG)
    assert "gpu_status" in payload
    assert "gpus" not in payload
    assert payload["is_online"] is True
    assert len(payload["gpu_status"]) > 0
    assert payload["gpu_status"][0]["device_index"] == 0
    assert payload["provider_mode"] == "dialout"
    assert "agent_version" in payload
    assert "capabilities" in payload
    assert "runtime" in payload["capabilities"]
    assert "topology" in payload["capabilities"]


def test_heartbeat_url() -> None:
    assert heartbeat_url(CONFIG) == (
        "http://localhost:8000/api/v1/rooms/22222222-2222-4222-8222-222222222222"
        "/nodes/33333333-3333-4333-8333-333333333333/heartbeat"
    )


@patch("deepiri_zepgpu.node_agent.heartbeat.httpx.post")
def test_send_heartbeat_uses_bearer_header(mock_post: MagicMock) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "connected"}
    mock_post.return_value = mock_response

    send_heartbeat(CONFIG)

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer super-secret-token"
    assert "gpu_status" in kwargs["json"]


def test_dry_run_does_not_post_and_redacts_token(caplog: pytest.LogCaptureFixture) -> None:
    with (
        caplog.at_level(logging.INFO),
        patch("deepiri_zepgpu.node_agent.heartbeat.httpx.post") as mock_post,
    ):
        result = send_heartbeat(CONFIG, dry_run=True)
    assert result is None
    mock_post.assert_not_called()
    assert "super-secret-token" not in caplog.text
    assert "gpu_status" in caplog.text


@patch("deepiri_zepgpu.node_agent.heartbeat.httpx.post")
def test_retries_transient_503(mock_post: MagicMock) -> None:
    failing = MagicMock()
    failing.status_code = 503
    failing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "server error",
        request=httpx.Request("POST", heartbeat_url(CONFIG)),
        response=failing,
    )

    success = MagicMock()
    success.status_code = 200
    success.json.return_value = {"status": "connected"}

    mock_post.side_effect = [failing, success]

    send_heartbeat(CONFIG)
    assert mock_post.call_count == 2
