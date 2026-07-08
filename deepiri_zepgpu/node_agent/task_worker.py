"""Node-agent task polling worker for remote execution MVP."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deepiri_zepgpu.node_agent.task_client import NodeTaskClient
from deepiri_zepgpu.node_agent.task_runner import NodeTaskRunner

logger = logging.getLogger(__name__)


class NodeTaskWorker:
    """Polls assigned node tasks and executes the Phase 5 no-op path."""

    def __init__(
        self,
        *,
        client: NodeTaskClient,
        runner: NodeTaskRunner | None = None,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self.client = client
        self.runner = runner or NodeTaskRunner()
        self.poll_interval_seconds = poll_interval_seconds
        self._running = False

    async def run_once(self) -> int:
        """Poll once and process available assignments.

        Returns the number of assignments processed.
        """
        assignments = await self.client.poll_pending(limit=1)
        processed = 0

        for assignment in assignments:
            await self.process_assignment(assignment)
            processed += 1

        return processed

    async def process_assignment(self, assignment: dict[str, Any]) -> dict[str, Any]:
        """Accept, start, execute, and complete one assigned task."""
        assignment_id = str(assignment["assignment_id"])

        try:
            await self.client.accept(assignment_id)
            started = await self.client.start(assignment_id)
            result_metadata = await self.runner.run_noop(started)
            return await self.client.complete(
                assignment_id,
                result_metadata=result_metadata,
            )
        except Exception as exc:
            logger.exception("Node task execution failed: %s", assignment_id)
            await self.client.fail(assignment_id, error=str(exc))
            raise

    async def run_forever(self) -> None:
        """Continuously poll for assignments until stopped."""
        self._running = True

        while self._running:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Node task worker iteration failed")

            await asyncio.sleep(self.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False
