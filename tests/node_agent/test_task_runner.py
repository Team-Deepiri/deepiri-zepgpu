"""Tests for node-agent task runner."""

from __future__ import annotations

import pytest

from deepiri_zepgpu.node_agent.task_runner import NodeTaskRunner


@pytest.mark.asyncio
async def test_noop_runner_returns_result_metadata() -> None:
    runner = NodeTaskRunner()

    result = await runner.run_noop(
        {
            "assignment_id": "assignment-1",
            "task_id": "task-1",
        }
    )

    assert result["kind"] == "noop"
    assert result["status"] == "ok"
    assert result["message"] == "remote noop completed"
    assert result["assignment_id"] == "assignment-1"
    assert result["task_id"] == "task-1"
