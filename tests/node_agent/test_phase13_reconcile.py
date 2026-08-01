"""Phase 13 agent inflight + reconcile + WSS message handling tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deepiri_zepgpu.node_agent import inflight
from deepiri_zepgpu.node_agent.task_worker import NodeTaskWorker


def test_inflight_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "inflight.json"
    inflight.upsert_inflight(
        "a1",
        status="running",
        task_id="t1",
        claim_generation=2,
        lease_expires_at="2099-01-01T00:00:00+00:00",
        path=path,
    )
    assert inflight.list_inflight_ids(path) == ["a1"]
    state = inflight.load_inflight(path)
    assert state["assignments"]["a1"]["status"] == "running"
    assert state["assignments"]["a1"]["claim_generation"] == 2
    inflight.remove_inflight("a1", path=path)
    assert inflight.list_inflight_ids(path) == []


class FakeTaskClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._pending: list[dict[str, Any]] = [
            {"assignment_id": "assignment-1", "task_id": "task-1"}
        ]
        self.reconcile_result: dict[str, Any] = {"outcomes": []}

    async def poll(self, *, limit: int = 1) -> dict[str, Any]:
        self.calls.append(f"poll:{limit}")
        return {"assignments": list(self._pending), "cancel_requested": []}

    async def poll_pending(self, *, limit: int = 1) -> list[dict[str, Any]]:
        self.calls.append(f"pending:{limit}")
        return list(self._pending)

    async def reconcile(self, assignment_ids: list[str]) -> dict[str, Any]:
        self.calls.append(f"reconcile:{','.join(assignment_ids)}")
        return self.reconcile_result

    async def claim(self, assignment_id: str) -> dict[str, Any]:
        self.calls.append(f"claim:{assignment_id}")
        return {
            "assignment_id": assignment_id,
            "task_id": "task-1",
            "status": "accepted",
            "claim_generation": 1,
            "lease_expires_at": "2099-01-01T00:00:00+00:00",
        }

    async def accept(self, assignment_id: str) -> dict[str, Any]:
        self.calls.append(f"accept:{assignment_id}")
        return {"assignment_id": assignment_id, "task_id": "task-1", "status": "accepted"}

    async def start(self, assignment_id: str) -> dict[str, Any]:
        self.calls.append(f"start:{assignment_id}")
        return {"assignment_id": assignment_id, "task_id": "task-1", "status": "running"}

    async def complete(
        self,
        assignment_id: str,
        *,
        result_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(f"complete:{assignment_id}")
        return {"assignment_id": assignment_id, "status": "completed"}

    async def fail(self, assignment_id: str, *, error: str) -> dict[str, Any]:
        self.calls.append(f"fail:{assignment_id}")
        return {"assignment_id": assignment_id, "status": "failed", "error": error}

    async def log(self, assignment_id: str, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append(f"log:{assignment_id}")
        return {"assignment_id": assignment_id}


@pytest.mark.asyncio
async def test_worker_claims_and_completes(tmp_path: Path) -> None:
    client = FakeTaskClient()
    worker = NodeTaskWorker(client=client, inflight_path=tmp_path / "inflight.json")  # type: ignore[arg-type]
    processed = await worker.run_once()
    assert processed == 1
    assert "claim:assignment-1" in client.calls
    assert "complete:assignment-1" in client.calls
    assert inflight.list_inflight_ids(tmp_path / "inflight.json") == []


@pytest.mark.asyncio
async def test_worker_reconcile_clears_expired(tmp_path: Path) -> None:
    path = tmp_path / "inflight.json"
    inflight.upsert_inflight("stale-1", status="running", path=path)
    client = FakeTaskClient()
    client.reconcile_result = {
        "outcomes": [
            {
                "assignment_id": "stale-1",
                "action": "fail_expired",
                "terminal_reason": "lease_expired",
            }
        ]
    }
    worker = NodeTaskWorker(client=client, inflight_path=path)  # type: ignore[arg-type]
    outcomes = await worker.reconcile_on_startup()
    assert outcomes[0]["action"] == "fail_expired"
    assert inflight.list_inflight_ids(path) == []


@pytest.mark.asyncio
async def test_worker_handles_wss_cancel(tmp_path: Path) -> None:
    path = tmp_path / "inflight.json"
    inflight.upsert_inflight("assignment-9", status="running", path=path)
    client = FakeTaskClient()
    worker = NodeTaskWorker(client=client, inflight_path=path)  # type: ignore[arg-type]
    await worker.handle_provider_message({"type": "cancel", "assignment_id": "assignment-9"})
    assert "fail:assignment-9" in client.calls
    assert inflight.list_inflight_ids(path) == []


@pytest.mark.asyncio
async def test_worker_processes_wss_assignment_push(tmp_path: Path) -> None:
    client = FakeTaskClient()
    client._pending = []
    worker = NodeTaskWorker(client=client, inflight_path=tmp_path / "inflight.json")  # type: ignore[arg-type]
    await worker.handle_provider_message(
        {
            "type": "assignment",
            "assignment_id": "assignment-1",
            "task_id": "task-1",
            "status": "assigned",
        }
    )
    processed = await worker.run_once()
    assert processed == 1
    assert "claim:assignment-1" in client.calls
