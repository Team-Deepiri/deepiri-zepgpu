"""Tests for node agent CLI."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from deepiri_zepgpu.node_agent.agent import main
from deepiri_zepgpu.node_agent.config import NodeAgentConfig


@patch("deepiri_zepgpu.node_agent.agent.send_heartbeat")
@patch("deepiri_zepgpu.node_agent.agent.build_config")
def test_once_exits_after_single_heartbeat(mock_build: object, mock_send: object) -> None:
    mock_build.return_value = NodeAgentConfig(
        api_base_url="http://localhost:8000",
        room_id="22222222-2222-4222-8222-222222222222",
        peer_id="33333333-3333-4333-8333-333333333333",
        auth_token="token",
        simulation_mode=True,
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--simulate",
            "--api-base-url",
            "http://localhost:8000",
            "--room-id",
            "22222222-2222-4222-8222-222222222222",
            "--peer-id",
            "33333333-3333-4333-8333-333333333333",
            "--auth-token",
            "token",
            "--once",
        ],
    )

    assert result.exit_code == 0
    mock_send.assert_called_once()
