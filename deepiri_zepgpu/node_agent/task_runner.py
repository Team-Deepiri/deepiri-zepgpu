"""Safe MVP task runner for node-agent remote execution."""

from __future__ import annotations

from typing import Any


class NodeTaskRunner:
    """Runs assigned node tasks.

    Phase 5 intentionally supports only a safe no-op execution path.
    """

    async def run_noop(self, assignment: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "noop",
            "status": "ok",
            "message": "remote noop completed",
            "assignment_id": assignment.get("assignment_id"),
            "task_id": assignment.get("task_id"),
        }
