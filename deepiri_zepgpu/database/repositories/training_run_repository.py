"""Persistence and state transitions for training runs and workers."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepiri_zepgpu.database.models.training_run import (
    TrainingRun,
    TrainingRunState,
    TrainingWorker,
    TrainingWorkerEvent,
    TrainingWorkerState,
)
from deepiri_zepgpu.training.config import filter_secrets

TERMINAL_STATES = {
    TrainingRunState.COMPLETED,
    TrainingRunState.FAILED,
    TrainingRunState.CANCELLED,
    TrainingRunState.TIMED_OUT,
}
TERMINAL_WORKER_STATES = {
    TrainingWorkerState.ABORTED,
    TrainingWorkerState.COMPLETED,
    TrainingWorkerState.FAILED,
    TrainingWorkerState.CANCELLED,
}

_TRANSITIONS: dict[TrainingRunState, set[TrainingRunState]] = {
    TrainingRunState.CREATED: {TrainingRunState.PREPARING, TrainingRunState.CANCELLED},
    TrainingRunState.PREPARING: {
        TrainingRunState.READY,
        TrainingRunState.FAILED,
        TrainingRunState.CANCELLED,
        TrainingRunState.TIMED_OUT,
    },
    TrainingRunState.READY: {
        TrainingRunState.RUNNING,
        TrainingRunState.FAILED,
        TrainingRunState.CANCELLED,
        TrainingRunState.TIMED_OUT,
    },
    TrainingRunState.RUNNING: {
        TrainingRunState.SYNCING,
        TrainingRunState.CHECKPOINTING,
        TrainingRunState.COMPLETED,
        TrainingRunState.FAILED,
        TrainingRunState.CANCELLED,
        TrainingRunState.TIMED_OUT,
    },
    TrainingRunState.SYNCING: {
        TrainingRunState.RUNNING,
        TrainingRunState.CHECKPOINTING,
        TrainingRunState.FAILED,
        TrainingRunState.CANCELLED,
        TrainingRunState.TIMED_OUT,
    },
    TrainingRunState.CHECKPOINTING: {
        TrainingRunState.RUNNING,
        TrainingRunState.COMPLETED,
        TrainingRunState.FAILED,
        TrainingRunState.CANCELLED,
        TrainingRunState.TIMED_OUT,
    },
}


class TrainingRunTransitionError(ValueError):
    pass


class TrainingWorkerEventConflict(ValueError):
    pass


class TrainingWorkerEventValidationError(ValueError):
    pass


class TrainingRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        room_id: str,
        user_id: str,
        config: dict[str, Any],
        provider_ids: list[str],
    ) -> TrainingRun:
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider_ids must be unique")
        run = TrainingRun(
            id=uuid.uuid4(),
            vpn_network_id=room_id,
            user_id=user_id,
            state=TrainingRunState.CREATED,
            config_version=int(config.get("schema_version", 1)),
            config=filter_secrets(config),
            provider_ids=provider_ids,
            artifacts=[],
            workers=[TrainingWorker(peer_id=provider_id) for provider_id in provider_ids],
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def get(self, run_id: str) -> TrainingRun | None:
        result = await self.session.execute(
            select(TrainingRun)
            .options(selectinload(TrainingRun.workers))
            .where(TrainingRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if run is not None:
            await self.enforce_startup_deadline(run)
            await self.reconcile_completed_workers(run)
        return run

    async def reconcile_completed_workers(self, run: TrainingRun) -> TrainingRun:
        """Heal runs stuck after concurrent checkpoint/complete races."""
        if run.state in TERMINAL_STATES or not run.workers:
            return run
        if all(item.state == TrainingWorkerState.COMPLETED for item in run.workers):
            await self.transition(run, TrainingRunState.COMPLETED)
        return run

    async def get_worker(self, run_id: str, worker_id: str) -> TrainingWorker | None:
        result = await self.session.execute(
            select(TrainingWorker).where(
                TrainingWorker.id == worker_id,
                TrainingWorker.run_id == run_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: str, *, room_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> Sequence[TrainingRun]:
        query = (
            select(TrainingRun)
            .options(selectinload(TrainingRun.workers))
            .where(TrainingRun.user_id == user_id)
        )
        if room_id:
            query = query.where(TrainingRun.vpn_network_id == room_id)
        result = await self.session.execute(
            query.order_by(TrainingRun.created_at.desc()).limit(limit).offset(offset)
        )
        runs = result.scalars().all()
        for run in runs:
            await self.enforce_startup_deadline(run)
        return runs

    async def transition(
        self,
        run: TrainingRun,
        state: TrainingRunState,
        *,
        error: str | None = None,
    ) -> TrainingRun:
        current = TrainingRunState(run.state)
        if current == state:
            if error and not run.error:
                run.error = error
                await self.session.flush()
            return run
        if current in TERMINAL_STATES or state not in _TRANSITIONS.get(current, set()):
            raise TrainingRunTransitionError(f"cannot transition {current.value} to {state.value}")
        now = datetime.now(UTC)
        run.state = state
        run.updated_at = now
        if state == TrainingRunState.RUNNING and run.started_at is None:
            run.started_at = now
        if state in TERMINAL_STATES:
            run.completed_at = now
        if error and not run.error:
            run.error = error
        await self.session.flush()
        return run

    async def prepare(self, run: TrainingRun) -> TrainingRun:
        if run.state == TrainingRunState.CREATED:
            timeout = int(run.config.get("startup_timeout_seconds", 300))
            run.startup_deadline_at = datetime.now(UTC) + timedelta(seconds=timeout)
            await self.transition(run, TrainingRunState.PREPARING)
        elif run.state != TrainingRunState.PREPARING:
            raise TrainingRunTransitionError(f"cannot prepare run in {run.state.value}")
        return run

    async def start(self, run: TrainingRun) -> TrainingRun:
        await self.enforce_startup_deadline(run)
        if run.state != TrainingRunState.READY:
            raise TrainingRunTransitionError("all assigned workers must be ready before start")
        updated = await self.transition(run, TrainingRunState.RUNNING)
        for worker in run.workers:
            if worker.state == TrainingWorkerState.READY:
                worker.state = TrainingWorkerState.RUNNING
        await self.session.flush()
        return updated

    async def abort(self, run: TrainingRun) -> TrainingRun:
        if run.state == TrainingRunState.CANCELLED:
            return run
        updated = await self.transition(run, TrainingRunState.CANCELLED)
        now = datetime.now(UTC)
        for worker in run.workers:
            if worker.state not in TERMINAL_WORKER_STATES:
                worker.state = TrainingWorkerState.CANCELLED
                worker.stopped_at = now
            worker.credential_revoked_at = now
        await self.session.flush()
        return updated

    async def fail(
        self, run: TrainingRun, *, error: str, failed_worker: TrainingWorker
    ) -> TrainingRun:
        updated = await self.transition(run, TrainingRunState.FAILED, error=error)
        now = datetime.now(UTC)
        for worker in run.workers:
            if worker is not failed_worker and worker.state not in TERMINAL_WORKER_STATES:
                worker.state = TrainingWorkerState.CANCELLED
                worker.stopped_at = now
            worker.credential_revoked_at = now
        await self.session.flush()
        return updated

    async def enforce_startup_deadline(self, run: TrainingRun) -> TrainingRun:
        deadline = run.startup_deadline_at
        if (
            run.state == TrainingRunState.PREPARING
            and deadline is not None
            and deadline <= datetime.now(UTC)
        ):
            await self.transition(
                run,
                TrainingRunState.TIMED_OUT,
                error="training worker readiness deadline expired",
            )
            now = datetime.now(UTC)
            for worker in run.workers:
                if worker.state not in TERMINAL_WORKER_STATES:
                    worker.state = TrainingWorkerState.CANCELLED
                    worker.stopped_at = now
                worker.credential_revoked_at = now
            await self.session.flush()
        return run

    async def _lock_run(self, run_id: uuid.UUID | str) -> TrainingRun:
        """Serialize collective worker transitions (ready / round / complete)."""
        result = await self.session.execute(
            select(TrainingRun)
            .options(selectinload(TrainingRun.workers))
            .where(TrainingRun.id == run_id)
            .with_for_update()
        )
        locked = result.scalar_one_or_none()
        if locked is None:
            raise TrainingRunTransitionError("training run not found while locking")
        return locked

    async def record_worker_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        *,
        event_id: str,
        kind: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> bool:
        existing_result = await self.session.execute(
            select(TrainingWorkerEvent).where(TrainingWorkerEvent.event_id == event_id)
        )
        existing = existing_result.scalar_one_or_none()
        clean_payload = filter_secrets(payload)
        if existing is not None:
            if (
                str(existing.run_id) != str(run.id)
                or str(existing.worker_id) != str(worker.id)
                or existing.kind != kind
                or existing.payload != clean_payload
            ):
                raise TrainingWorkerEventConflict("conflicting duplicate worker event")
            return False
        # Lock after the idempotency check so concurrent ready/complete events serialize.
        locked_run = await self._lock_run(run.id)
        locked_worker = next(
            (item for item in locked_run.workers if str(item.id) == str(worker.id)), None
        )
        if locked_worker is None:
            raise TrainingRunTransitionError("worker is not assigned to this run")
        if locked_run.state in TERMINAL_STATES or locked_worker.state in TERMINAL_WORKER_STATES:
            raise TrainingRunTransitionError("terminal training state is immutable")
        event = TrainingWorkerEvent(
            id=uuid.uuid4(),
            run_id=locked_run.id,
            worker_id=locked_worker.id,
            event_id=uuid.UUID(event_id),
            kind=kind,
            occurred_at=occurred_at,
            payload=clean_payload,
        )
        self.session.add(event)
        await self._apply_worker_event(locked_run, locked_worker, kind, clean_payload)
        await self.session.flush()
        # Keep the caller's instances coherent for the HTTP response mapper.
        run.state = locked_run.state
        run.error = locked_run.error
        run.updated_at = locked_run.updated_at
        run.started_at = locked_run.started_at
        run.completed_at = locked_run.completed_at
        run.startup_deadline_at = locked_run.startup_deadline_at
        worker.state = locked_worker.state
        worker.current_round = locked_worker.current_round
        worker.progress = locked_worker.progress
        worker.last_heartbeat_at = locked_worker.last_heartbeat_at
        worker.ready_at = locked_worker.ready_at
        worker.stopped_at = locked_worker.stopped_at
        worker.restart_count = locked_worker.restart_count
        worker.error = locked_worker.error
        # Refresh relationship view used by _response(run).
        run.workers = locked_run.workers
        return True

    async def _apply_worker_event(
        self, run: TrainingRun, worker: TrainingWorker, kind: str, payload: dict[str, Any]
    ) -> None:
        now = datetime.now(UTC)
        handlers = {
            "ready": self._handle_ready_event,
            "heartbeat": self._handle_heartbeat_event,
            "progress": self._handle_progress_event,
            "log": self._handle_log_event,
            "round_started": self._handle_round_started_event,
            "round_completed": self._handle_round_completed_event,
            "round_failed": self._handle_round_failed_event,
            "checkpointing": self._handle_checkpointing_event,
            "checkpoint_completed": self._handle_checkpoint_completed_event,
            "reconnected": self._handle_reconnect_event,
            "shutdown": self._handle_shutdown_event,
            "aborted": self._handle_abort_event,
            "completed": self._handle_completed_event,
        }
        handler = handlers.get(kind)
        if handler is None:
            raise TrainingWorkerEventValidationError(f"unsupported worker event: {kind}")
        await handler(run, worker, payload, now)

    async def _handle_ready_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del payload
        if worker.state == TrainingWorkerState.READY and run.state in {
            TrainingRunState.PREPARING,
            TrainingRunState.READY,
        }:
            worker.last_heartbeat_at = now
            return
        if run.state == TrainingRunState.CREATED:
            await self.prepare(run)
        if run.state != TrainingRunState.PREPARING:
            raise TrainingRunTransitionError("worker readiness is only valid while preparing")
        worker.state = TrainingWorkerState.READY
        worker.ready_at = worker.ready_at or now
        worker.last_heartbeat_at = now
        if run.workers and all(item.state == TrainingWorkerState.READY for item in run.workers):
            await self.transition(run, TrainingRunState.READY)

    @staticmethod
    async def _handle_heartbeat_event(
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del run
        worker.last_heartbeat_at = now
        progress = payload.get("progress", payload)
        if isinstance(progress, dict):
            worker.progress = {**worker.progress, **progress}

    async def _handle_progress_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        await self._handle_heartbeat_event(run, worker, payload, now)

    @staticmethod
    async def _handle_log_event(
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del run, payload
        worker.last_heartbeat_at = now

    async def _handle_round_started_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del now
        round_number = self._event_round(payload)
        if run.state not in {TrainingRunState.RUNNING, TrainingRunState.SYNCING}:
            raise TrainingRunTransitionError("round cannot start unless run is running")
        if round_number <= worker.current_round:
            raise TrainingWorkerEventConflict("round must increase monotonically")
        worker.current_round = round_number
        worker.state = TrainingWorkerState.SYNCING
        worker.progress = {**worker.progress, "round_status": "started"}
        if run.state == TrainingRunState.RUNNING:
            await self.transition(run, TrainingRunState.SYNCING)

    async def _handle_round_completed_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del now
        round_number = self._event_round(payload)
        if round_number != worker.current_round or worker.state != TrainingWorkerState.SYNCING:
            raise TrainingWorkerEventConflict("round completion does not match active round")
        worker.state = TrainingWorkerState.RUNNING
        worker.progress = {**worker.progress, "round_status": "completed"}
        if all(
            item.current_round == round_number and item.progress.get("round_status") == "completed"
            for item in run.workers
        ):
            await self.transition(run, TrainingRunState.RUNNING)

    async def _handle_round_failed_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        round_number = self._event_round(payload)
        worker.current_round = max(worker.current_round, round_number)
        worker.state = TrainingWorkerState.FAILED
        worker.error = worker.error or str(payload.get("error_type", "worker round failed"))
        worker.stopped_at = now
        await self.fail(run, error=worker.error, failed_worker=worker)

    async def _handle_checkpointing_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del payload, now
        if run.state not in {
            TrainingRunState.RUNNING,
            TrainingRunState.SYNCING,
            TrainingRunState.CHECKPOINTING,
        }:
            raise TrainingRunTransitionError("checkpointing requires an active run")
        worker.state = TrainingWorkerState.CHECKPOINTING
        await self.transition(run, TrainingRunState.CHECKPOINTING)

    async def _handle_checkpoint_completed_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del payload, now
        if worker.state != TrainingWorkerState.CHECKPOINTING:
            raise TrainingRunTransitionError("worker is not checkpointing")
        worker.state = TrainingWorkerState.RUNNING
        # Peers may already be COMPLETED if they finished the final checkpoint+complete
        # race; treat them as done so the run can leave CHECKPOINTING.
        done_or_running = {
            TrainingWorkerState.RUNNING,
            TrainingWorkerState.COMPLETED,
            TrainingWorkerState.STOPPED,
        }
        if all(item.state in done_or_running for item in run.workers):
            if all(item.state == TrainingWorkerState.COMPLETED for item in run.workers):
                await self.transition(run, TrainingRunState.COMPLETED)
            elif run.state == TrainingRunState.CHECKPOINTING:
                await self.transition(run, TrainingRunState.RUNNING)

    @staticmethod
    async def _handle_reconnect_event(
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del payload
        worker.restart_count += 1
        worker.last_heartbeat_at = now
        worker.state = (
            TrainingWorkerState.READY
            if run.state in {TrainingRunState.PREPARING, TrainingRunState.READY}
            else TrainingWorkerState.RUNNING
        )

    @staticmethod
    async def _handle_shutdown_event(
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del run, payload
        worker.state = TrainingWorkerState.STOPPED
        worker.stopped_at = now

    async def _handle_abort_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del payload
        worker.state = TrainingWorkerState.ABORTED
        worker.stopped_at = now
        worker.credential_revoked_at = now
        await self.abort(run)

    async def _handle_completed_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del payload
        worker.state = TrainingWorkerState.COMPLETED
        worker.stopped_at = now
        if all(item.state == TrainingWorkerState.COMPLETED for item in run.workers):
            await self.transition(run, TrainingRunState.COMPLETED)

    @staticmethod
    def _event_round(payload: dict[str, Any]) -> int:
        value = payload.get("round")
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise TrainingWorkerEventValidationError("event requires a positive round")
        return value

    async def add_artifact(self, run: TrainingRun, artifact: dict[str, Any]) -> TrainingRun:
        run.artifacts = [*run.artifacts, filter_secrets(artifact)]
        await self.session.flush()
        return run
