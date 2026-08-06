"""Node-agent task polling worker for remote execution MVP."""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Any

from deepiri_zepgpu.node_agent.inflight import (
    list_inflight_ids,
    remove_inflight,
    upsert_inflight,
)
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
        poll_limit: int = 1,
        max_failure_backoff_seconds: float = 60.0,
        inflight_path: str | Path | None = None,
        prefer_wss: bool = True,
    ) -> None:
        self.client = client
        self.runner = runner or NodeTaskRunner()
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_limit = poll_limit
        self.max_failure_backoff_seconds = max_failure_backoff_seconds
        self.inflight_path = inflight_path
        self.prefer_wss = prefer_wss
        self._running = False
        self._pushed: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._active_ids: set[str] = set()

    async def handle_provider_message(self, message: dict[str, Any]) -> None:
        """Handle WSS push (assignment / cancel / reconnecting)."""
        msg_type = message.get("type")
        if msg_type == "assignment":
            await self._pushed.put(message)
        elif msg_type == "cancel":
            assignment_id = str(message.get("assignment_id") or "")
            if assignment_id:
                await self._handle_cancel(assignment_id)
        elif msg_type == "reconnecting":
            await self._log_assignment_event(
                str(message.get("assignment_id") or "unknown"),
                event_type="reconnecting",
                message="Provider WSS reconnecting",
                payload={"delay_seconds": message.get("delay_seconds")},
            )

    async def reconcile_on_startup(self) -> list[dict[str, Any]]:
        """Reconcile local in-flight IDs with the coordinator after restart."""
        local_ids = list_inflight_ids(self.inflight_path)
        try:
            result = await self.client.reconcile(local_ids)
        except Exception:
            logger.exception("Reconcile failed; continuing with local state")
            return []

        outcomes = list(result.get("outcomes") or [])
        for item in outcomes:
            assignment_id = str(item.get("assignment_id") or "")
            action = item.get("action")
            if not assignment_id:
                continue
            if action in {"abandon", "fail_expired", "cancel"}:
                remove_inflight(assignment_id, path=self.inflight_path)
                self._active_ids.discard(assignment_id)
            elif action == "resume":
                upsert_inflight(
                    assignment_id,
                    status=str(item.get("status") or "accepted"),
                    claim_generation=item.get("claim_generation"),
                    lease_expires_at=item.get("lease_expires_at"),
                    path=self.inflight_path,
                )
                if item.get("cancel_requested"):
                    await self._handle_cancel(assignment_id)
        return outcomes

    async def run_once(self) -> int:
        """Poll once (and drain WSS queue) then process assignments."""
        processed = 0

        # Drain WSS pushes first.
        while not self._pushed.empty():
            message = await self._pushed.get()
            assignment = {
                "assignment_id": message.get("assignment_id"),
                "task_id": message.get("task_id"),
                "status": message.get("status"),
            }
            if assignment["assignment_id"]:
                await self.process_assignment(assignment)
                processed += 1

        try:
            poll = await self.client.poll(limit=self.poll_limit)
            assignments = list(poll.get("assignments") or [])
            cancels = list(poll.get("cancel_requested") or [])
        except Exception:
            # Fall back to legacy pending endpoint.
            logger.debug("Structured poll unavailable; using pending list", exc_info=True)
            assignments = await self.client.poll_pending(limit=self.poll_limit)
            cancels = [a for a in assignments if a.get("cancel_requested")]
            assignments = [a for a in assignments if not a.get("cancel_requested")]

        for cancel in cancels:
            assignment_id = str(cancel.get("assignment_id") or "")
            if assignment_id:
                await self._handle_cancel(assignment_id)

        for assignment in assignments:
            await self.process_assignment(assignment)
            processed += 1

        return processed

    async def process_assignment(self, assignment: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
        """Claim, start, execute, and complete one assigned task."""
        assignment_id = str(assignment["assignment_id"])
        if assignment_id in self._active_ids:
            return assignment
        if assignment.get("cancel_requested"):
            await self._handle_cancel(assignment_id)
            return assignment

        self._active_ids.add(assignment_id)
        upsert_inflight(
            assignment_id,
            status="assigned",
            task_id=str(assignment.get("task_id") or ""),
            path=self.inflight_path,
        )

        try:
            try:
                claimed = await self.client.claim(assignment_id)
            except AttributeError:
                claimed = await self.client.accept(assignment_id)
            except Exception as claim_exc:
                # Older coordinators may only expose /accept.
                if "404" in str(claim_exc) or "Not Found" in str(claim_exc):
                    claimed = await self.client.accept(assignment_id)
                else:
                    raise
            if claimed.get("cancel_requested") or claimed.get("status") == "cancelled":
                await self._handle_cancel(assignment_id)
                return claimed
            if claimed.get("status") in {"failed", "completed", "cancelled"}:
                remove_inflight(assignment_id, path=self.inflight_path)
                return claimed

            upsert_inflight(
                assignment_id,
                status=str(claimed.get("status") or "accepted"),
                task_id=str(claimed.get("task_id") or assignment.get("task_id") or ""),
                claim_generation=claimed.get("claim_generation"),
                lease_expires_at=(
                    claimed["lease_expires_at"]
                    if isinstance(claimed.get("lease_expires_at"), str)
                    else None
                ),
                path=self.inflight_path,
            )
            await self._log_assignment_event(
                assignment_id,
                event_type="node_task_accepted",
                message="Node agent claimed assignment",
            )

            # Keep accept() for older coordinators that only expose /accept.
            # claim already covers modern coordinators.

            started = await self.client.start(assignment_id)
            if started.get("cancel_requested") or started.get("status") in {
                "cancelled",
                "failed",
            }:
                remove_inflight(assignment_id, path=self.inflight_path)
                return started

            upsert_inflight(
                assignment_id,
                status="running",
                path=self.inflight_path,
            )
            await self._log_assignment_event(
                assignment_id,
                event_type="node_task_started",
                message="Node agent started assignment",
            )

            result_metadata = await self.runner.run_noop(started)
            completed = await self.client.complete(
                assignment_id,
                result_metadata=result_metadata,
            )
            await self._log_assignment_event(
                assignment_id,
                event_type="node_task_completed",
                message="Node agent completed assignment",
                payload={"result_metadata": result_metadata},
            )
            remove_inflight(assignment_id, path=self.inflight_path)
            return completed
        except Exception as exc:
            logger.exception("Node task execution failed: %s", assignment_id)

            try:
                await self.client.fail(assignment_id, error=str(exc))
            except Exception:
                logger.exception(
                    "Failed to report failure for node task assignment %s to "
                    "the coordinator; it will remain in its current state "
                    "until server-side AWOL/timeout reconciliation reclaims it.",
                    assignment_id,
                )

            await self._log_assignment_event(
                assignment_id,
                event_type="node_task_failed",
                message="Node agent failed assignment",
                payload={"error": str(exc)},
            )
            remove_inflight(assignment_id, path=self.inflight_path)
            raise
        finally:
            self._active_ids.discard(assignment_id)

    async def _handle_cancel(self, assignment_id: str) -> None:
        logger.info("Cancel requested for assignment %s", assignment_id)
        try:
            # Completing cancel on coordinator: report fail with cancel reason if still active.
            await self.client.fail(assignment_id, error="Cancelled by coordinator")
        except Exception:
            logger.debug("Cancel fail report skipped for %s", assignment_id, exc_info=True)
        remove_inflight(assignment_id, path=self.inflight_path)
        self._active_ids.discard(assignment_id)

    async def _log_assignment_event(
        self,
        assignment_id: str,
        *,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if assignment_id == "unknown":
            return
        try:
            await self.client.log(
                assignment_id,
                event_type=event_type,
                message=message,
                payload=payload or {},
            )
        except Exception:
            logger.exception("Failed to write node task log: %s", assignment_id)

    def _idle_sleep_seconds(self) -> float:
        """Backoff + jitter when no work exists."""
        base = self.poll_interval_seconds
        jitter = random.uniform(0, max(0.1, base * 0.5))
        return base + jitter

    async def run_forever(self) -> None:
        """Continuously poll for assignments until stopped."""
        self._running = True
        consecutive_failures = 0
        await self.reconcile_on_startup()

        while self._running:
            try:
                processed = await self.run_once()
                consecutive_failures = 0
                if processed:
                    sleep_seconds = self.poll_interval_seconds
                else:
                    sleep_seconds = self._idle_sleep_seconds()
            except Exception:
                consecutive_failures += 1
                sleep_seconds = min(
                    self.poll_interval_seconds * (2 ** min(consecutive_failures - 1, 6)),
                    self.max_failure_backoff_seconds,
                )
                sleep_seconds += random.uniform(0, sleep_seconds * 0.25)
                logger.exception(
                    "Node task worker iteration failed; consecutive_failures=%s, "
                    "retrying in %.2f seconds",
                    consecutive_failures,
                    sleep_seconds,
                )

            await asyncio.sleep(sleep_seconds)

    def stop(self) -> None:
        self._running = False
