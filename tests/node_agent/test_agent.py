"""Tests for node agent runtime wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deepiri_zepgpu.node_agent.agent import run_agent
from deepiri_zepgpu.node_agent.config import NodeAgentConfig

CONFIG = NodeAgentConfig(
    api_base_url="http://localhost:8000",
    room_id="22222222-2222-4222-8222-222222222222",
    peer_id="33333333-3333-4333-8333-333333333333",
    auth_token="super-secret-token",
    simulation_mode=True,
)


@patch("deepiri_zepgpu.node_agent.agent.run_task_worker_once")
@patch("deepiri_zepgpu.node_agent.agent.send_heartbeat")
def test_run_agent_skips_task_worker_by_default(
    mock_send_heartbeat: MagicMock,
    mock_run_task_worker_once: MagicMock,
) -> None:
    run_agent(CONFIG, once=True)

    mock_send_heartbeat.assert_called_once_with(CONFIG, dry_run=False)
    mock_run_task_worker_once.assert_not_called()


@patch("deepiri_zepgpu.node_agent.agent.run_task_worker_once")
@patch("deepiri_zepgpu.node_agent.agent.send_heartbeat")
def test_run_agent_runs_task_worker_when_enabled(
    mock_send_heartbeat: MagicMock,
    mock_run_task_worker_once: MagicMock,
) -> None:
    config = CONFIG.model_copy(update={"enable_task_worker": True})
    mock_run_task_worker_once.return_value = 1

    run_agent(config, once=True)

    mock_send_heartbeat.assert_called_once_with(config, dry_run=False)
    mock_run_task_worker_once.assert_called_once_with(config)


@patch("deepiri_zepgpu.node_agent.agent.run_task_worker_once")
@patch("deepiri_zepgpu.node_agent.agent.send_heartbeat")
def test_dry_run_skips_task_worker(
    mock_send_heartbeat: MagicMock,
    mock_run_task_worker_once: MagicMock,
) -> None:
    config = CONFIG.model_copy(update={"enable_task_worker": True})

    run_agent(config, once=True, dry_run=True)

    mock_send_heartbeat.assert_called_once_with(config, dry_run=True)
    mock_run_task_worker_once.assert_not_called()
