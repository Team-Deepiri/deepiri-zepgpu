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


class FakeClientWhereFailAlsoFails(FakeTaskClient):
    """fail() itself raises, simulating a network blip while reporting."""

    async def fail(self, assignment_id: str, *, error: str) -> dict[str, Any]:
        self.calls.append(f"fail:{assignment_id}")
        raise RuntimeError("network down while reporting failure")


@pytest.mark.asyncio
async def test_worker_reraises_original_error_when_fail_report_itself_fails() -> None:
    """The runner's original error must win over the secondary error from
    reporting the failure, and the failure-report attempt + log event
    should still both be attempted rather than silently skipped."""
    client = FakeClientWhereFailAlsoFails()
    worker = NodeTaskWorker(
        client=client,  # type: ignore[arg-type]
        runner=FailingRunner(),  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="boom"):
        await worker.run_once()

    assert "fail:assignment-1" in client.calls
    assert "log:node_task_failed:assignment-1" in client.calls


class FakeMultiTaskClient:
    """Fake client that returns several pending assignments in one poll."""

    def __init__(self, *, assignments: list[dict[str, Any]]) -> None:
        self._assignments = assignments
        self.poll_calls: list[str] = []
        self.completed_ids: list[str] = []

    async def poll_pending(self, *, limit: int = 1) -> list[dict[str, Any]]:
        self.poll_calls.append(f"poll:{limit}")
        return list(self._assignments)

    async def accept(self, assignment_id: str) -> dict[str, Any]:
        return {"assignment_id": assignment_id}

    async def start(self, assignment_id: str) -> dict[str, Any]:
        return {"assignment_id": assignment_id}

    async def complete(
        self,
        assignment_id: str,
        *,
        result_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.completed_ids.append(assignment_id)
        return {"assignment_id": assignment_id, "status": "completed"}

    async def fail(self, assignment_id: str, *, error: str) -> dict[str, Any]:
        return {"assignment_id": assignment_id, "status": "failed", "error": error}

    async def log(self, assignment_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"assignment_id": assignment_id}


@pytest.mark.asyncio
async def test_worker_respects_poll_limit_and_processes_all_returned() -> None:
    """run_once should loop through every assignment poll_pending returns,
    not just the first one, and should request poll_limit from the client."""
    client = FakeMultiTaskClient(
        assignments=[
            {"assignment_id": "assignment-1", "task_id": "task-1"},
            {"assignment_id": "assignment-2", "task_id": "task-2"},
        ]
    )
    worker = NodeTaskWorker(client=client, poll_limit=5)  # type: ignore[arg-type]

    processed = await worker.run_once()

    assert processed == 2
    assert client.poll_calls == ["poll:5"]
    assert client.completed_ids == ["assignment-1", "assignment-2"]


@pytest.mark.asyncio
async def test_worker_default_poll_limit_is_one() -> None:
    """Regression guard: default construction should still poll for exactly
    one assignment unless poll_limit is explicitly raised."""
    client = FakeMultiTaskClient(assignments=[{"assignment_id": "a", "task_id": "t"}])
    worker = NodeTaskWorker(client=client)  # type: ignore[arg-type]

    await worker.run_once()

    assert client.poll_calls == ["poll:1"]
