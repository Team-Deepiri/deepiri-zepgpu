"""Tests for node-agent task polling worker."""

from __future__ import annotations

from typing import Any

import pytest

from deepiri_zepgpu.node_agent.task_worker import NodeTaskWorker


class FakeTaskClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def poll_pending(self, *, limit: int = 1) -> list[dict[str, Any]]:
        self.calls.append(f"poll:{limit}")
        return [
            {
                "assignment_id": "assignment-1",
                "task_id": "task-1",
            }
        ]

    async def accept(self, assignment_id: str) -> dict[str, Any]:
        self.calls.append(f"accept:{assignment_id}")
        return {"assignment_id": assignment_id, "task_id": "task-1"}

    async def start(self, assignment_id: str) -> dict[str, Any]:
        self.calls.append(f"start:{assignment_id}")
        return {"assignment_id": assignment_id, "task_id": "task-1"}

    async def complete(
        self,
        assignment_id: str,
        *,
        result_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(f"complete:{assignment_id}")
        return {
            "assignment_id": assignment_id,
            "task_id": "task-1",
            "status": "completed",
            "result_metadata": result_metadata,
        }

    async def fail(self, assignment_id: str, *, error: str) -> dict[str, Any]:
        self.calls.append(f"fail:{assignment_id}")
        return {"assignment_id": assignment_id, "status": "failed", "error": error}

    async def log(
        self,
        assignment_id: str,
        *,
        event_type: str,
        message: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(f"log:{event_type}:{assignment_id}")
        return {
            "assignment_id": assignment_id,
            "event_type": event_type,
            "message": message,
            "payload": payload,
        }


@pytest.mark.asyncio
async def test_worker_processes_pending_noop_assignment() -> None:
    client = FakeTaskClient()
    worker = NodeTaskWorker(client=client)  # type: ignore[arg-type]

    processed = await worker.run_once()

    assert processed == 1
    assert client.calls == [
        "poll:1",
        "accept:assignment-1",
        "log:node_task_accepted:assignment-1",
        "start:assignment-1",
        "log:node_task_started:assignment-1",
        "complete:assignment-1",
        "log:node_task_completed:assignment-1",
    ]


class FailingRunner:
    async def run_noop(self, assignment: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_worker_reports_failed_assignment_when_runner_fails() -> None:
    client = FakeTaskClient()
    worker = NodeTaskWorker(
        client=client,  # type: ignore[arg-type]
        runner=FailingRunner(),  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="boom"):
        await worker.run_once()

    assert client.calls == [
        "poll:1",
        "accept:assignment-1",
        "log:node_task_accepted:assignment-1",
        "start:assignment-1",
        "log:node_task_started:assignment-1",
        "fail:assignment-1",
        "log:node_task_failed:assignment-1",
    ]
