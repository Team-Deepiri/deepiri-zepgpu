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
    TrainingOuterRound,
    TrainingOuterRoundState,
    TrainingRun,
    TrainingRunEvent,
    TrainingRunState,
    TrainingWorker,
    TrainingWorkerEvent,
    TrainingWorkerState,
)
from deepiri_zepgpu.training.config import TrainingRunConfig, filter_secrets

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
        placement_plan: dict[str, Any] | None = None,
    ) -> TrainingRun:
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider_ids must be unique")
        # Persist the public config contract (no runtime.environment / secret keys).
        public_config = TrainingRunConfig.model_validate(config).to_public_dict()
        run = TrainingRun(
            id=uuid.uuid4(),
            vpn_network_id=room_id,
            user_id=user_id,
            state=TrainingRunState.CREATED,
            config_version=int(public_config.get("schema_version", 1)),
            config=public_config,
            provider_ids=provider_ids,
            artifacts=[],
            placement_plan=filter_secrets(placement_plan) if placement_plan is not None else None,
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
        if not self._run_membership_completed(run):
            return run
        locked = await self._lock_run(run.id)
        try:
            if locked.state not in TERMINAL_STATES and self._run_membership_completed(locked):
                await self.transition(locked, TrainingRunState.COMPLETED)
                await self.session.refresh(locked)
        finally:
            self._overlay_run(run, locked)
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
            await self.reconcile_completed_workers(run)
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
        if state in TERMINAL_STATES and run.config_version >= 3:
            from deepiri_zepgpu.database.repositories.training_reservation_repository import (
                TrainingReservationRepository,
            )

            await TrainingReservationRepository(self.session).release_terminal(
                run_id=str(run.id), reason=f"training run became {state.value}"
            )
        return run

    async def record_run_event(
        self, run: TrainingRun, *, kind: str, payload: dict[str, Any]
    ) -> TrainingRunEvent:
        event = TrainingRunEvent(
            id=uuid.uuid4(),
            run_id=run.id,
            kind=kind,
            payload=filter_secrets(payload),
        )
        self.session.add(event)
        await self.session.flush()
        return event

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

    async def enforce_startup_deadline(
        self, run: TrainingRun, *, now: datetime | None = None
    ) -> TrainingRun:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        deadline = run.startup_deadline_at
        if run.state == TrainingRunState.PREPARING and deadline is not None and deadline <= current:
            await self.transition(
                run,
                TrainingRunState.TIMED_OUT,
                error="training worker readiness deadline expired",
            )
            for worker in run.workers:
                if worker.state not in TERMINAL_WORKER_STATES:
                    worker.state = TrainingWorkerState.CANCELLED
                    worker.stopped_at = current
                worker.credential_revoked_at = current
            await self.session.flush()
        elif (
            run.config_version >= 3
            and run.state
            in {
                TrainingRunState.RUNNING,
                TrainingRunState.SYNCING,
                TrainingRunState.CHECKPOINTING,
            }
            and run.started_at is not None
        ):
            phase18 = run.config.get("phase18")
            maximum_runtime = (
                phase18.get("maximum_runtime_seconds") if isinstance(phase18, dict) else None
            )
            if (
                isinstance(maximum_runtime, int)
                and maximum_runtime > 0
                and run.started_at + timedelta(seconds=maximum_runtime) <= current
            ):
                await self.transition(
                    run,
                    TrainingRunState.TIMED_OUT,
                    error="maximum Phase 18 training runtime expired",
                )
                for worker in run.workers:
                    if worker.state not in TERMINAL_WORKER_STATES:
                        worker.state = TrainingWorkerState.CANCELLED
                        worker.stopped_at = current
                    worker.credential_revoked_at = current
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
        # Lock first so concurrent ready/complete/idempotent retries serialize.
        locked_run = await self._lock_run(run.id)
        # Re-check idempotency under the run lock (avoids TOCTOU vs unique event_id).
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
        await self.session.refresh(locked_run)
        await self.session.refresh(locked_worker)
        self._overlay_run(run, locked_run)
        self._overlay_worker(worker, locked_worker)
        return True

    @staticmethod
    def _overlay_run(destination: TrainingRun, source: TrainingRun) -> None:
        for name in (
            "state",
            "error",
            "updated_at",
            "started_at",
            "completed_at",
            "startup_deadline_at",
            "placement_plan",
            "launch_key",
            "launched_at",
            "current_outer_round",
        ):
            setattr(destination, name, getattr(source, name))
        destination.workers = source.workers

    @staticmethod
    def _overlay_worker(destination: TrainingWorker, source: TrainingWorker) -> None:
        for name in (
            "state",
            "current_round",
            "progress",
            "last_heartbeat_at",
            "ready_at",
            "stopped_at",
            "restart_count",
            "error",
            "credential_revoked_at",
            "island_id",
            "global_rank",
            "island_rank",
            "world_size",
            "island_world_size",
            "assigned_devices",
            "bootstrap_checkpoint",
        ):
            setattr(destination, name, getattr(source, name))

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
            "bootstrap_completed": self._handle_bootstrap_completed_event,
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
        if run.config_version >= 3 and run.state in {
            TrainingRunState.READY,
            TrainingRunState.RUNNING,
        }:
            worker.state = (
                TrainingWorkerState.RUNNING
                if run.state == TrainingRunState.RUNNING
                else TrainingWorkerState.READY
            )
            worker.ready_at = worker.ready_at or now
            worker.last_heartbeat_at = now
            return
        if run.state == TrainingRunState.CREATED:
            await self.prepare(run)
        if run.state != TrainingRunState.PREPARING:
            raise TrainingRunTransitionError("worker readiness is only valid while preparing")
        worker.state = TrainingWorkerState.READY
        worker.ready_at = worker.ready_at or now
        worker.last_heartbeat_at = now
        ready_count = sum(item.state == TrainingWorkerState.READY for item in run.workers)
        required = self._minimum_workers(run)
        if run.workers and ready_count >= required:
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
        if run.config_version >= 3:
            # Schema-v3 worker events are lifecycle observations.  The
            # Phase18CoordinatorRuntime is the only component allowed to create
            # or finalize TrainingOuterRound rows.
            existing = await self.session.execute(
                select(TrainingOuterRound).where(
                    TrainingOuterRound.run_id == run.id,
                    TrainingOuterRound.round_number == round_number,
                )
            )
            outer_round = existing.scalar_one_or_none()
            if outer_round is not None and outer_round.state != TrainingOuterRoundState.OPEN:
                raise TrainingWorkerEventConflict("outer round is already closed")
        if run.state == TrainingRunState.RUNNING:
            await self.transition(run, TrainingRunState.SYNCING)

    async def _handle_round_completed_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        round_number = self._event_round(payload)
        if run.config_version < 3 and (
            round_number != worker.current_round or worker.state != TrainingWorkerState.SYNCING
        ):
            raise TrainingWorkerEventConflict("round completion does not match active round")
        outer_round: TrainingOuterRound | None = None
        if run.config_version >= 3:
            outer_result = await self.session.execute(
                select(TrainingOuterRound)
                .where(
                    TrainingOuterRound.run_id == run.id,
                    TrainingOuterRound.round_number == round_number,
                )
                .with_for_update()
            )
            outer_round = outer_result.scalar_one_or_none()
            if outer_round is None:
                raise TrainingWorkerEventConflict(
                    "authoritative Phase 18 outer round state is missing"
                )
            if (
                outer_round.state != TrainingOuterRoundState.FINALIZED
                or str(worker.id) not in outer_round.accepted_worker_ids
            ):
                rejection = {
                    "worker_id": str(worker.id),
                    "round": round_number,
                    "reason": (
                        f"authoritative outer round is {outer_round.state.value} "
                        "or did not accept this worker"
                    ),
                }
                outer_round.rejected_updates = [*outer_round.rejected_updates, rejection]
                worker.state = TrainingWorkerState.RECONNECTING
                worker.progress = {
                    **worker.progress,
                    "round_status": "late_rejected",
                    "bootstrap_required": True,
                    "bootstrap_round": run.current_outer_round,
                }
                await self.record_run_event(run, kind="outer_update_rejected", payload=rejection)
                return
            worker.current_round = round_number
            worker.state = TrainingWorkerState.RUNNING
            worker.progress = {**worker.progress, "round_status": "completed"}
            return
        worker.state = TrainingWorkerState.RUNNING
        worker.progress = {**worker.progress, "round_status": "completed"}
        completed_count = sum(
            item.current_round == round_number and item.progress.get("round_status") == "completed"
            for item in run.workers
        )
        if completed_count >= self._minimum_workers(run):
            run.current_outer_round = max(run.current_outer_round, round_number)
            if outer_round is not None:
                outer_round.state = TrainingOuterRoundState.FINALIZED
                outer_round.finalized_at = datetime.now(UTC)
            await self.transition(run, TrainingRunState.RUNNING)

    async def _handle_round_failed_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        supervisor_failure = (
            run.config_version >= 3
            and payload.get("source") == "provider_process_supervisor"
            and "round" not in payload
        )
        round_number = worker.current_round if supervisor_failure else self._event_round(payload)
        worker.current_round = max(worker.current_round, round_number)
        worker.state = (
            TrainingWorkerState.RECONNECTING
            if run.config_version >= 3
            else TrainingWorkerState.FAILED
        )
        worker.error = worker.error or str(
            payload.get("error") or payload.get("error_type") or "worker round failed"
        )
        worker.stopped_at = now
        if run.config_version >= 3:
            active_count = sum(
                item.state
                not in {
                    TrainingWorkerState.RECONNECTING,
                    TrainingWorkerState.FAILED,
                    TrainingWorkerState.CANCELLED,
                    TrainingWorkerState.ABORTED,
                    TrainingWorkerState.STOPPED,
                }
                for item in run.workers
            )
            if active_count >= self._minimum_workers(run):
                return
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
        del now
        if worker.state != TrainingWorkerState.CHECKPOINTING:
            raise TrainingRunTransitionError("worker is not checkpointing")
        if run.config_version >= 3:
            checkpoint = payload.get("checkpoint")
            if checkpoint is not None and not isinstance(checkpoint, dict):
                raise TrainingWorkerEventValidationError("checkpoint metadata must be an object")
            if isinstance(checkpoint, dict):
                checkpoint_round = checkpoint.get("outer_round", run.current_outer_round)
                if (
                    not isinstance(checkpoint_round, int)
                    or isinstance(checkpoint_round, bool)
                    or checkpoint_round != run.current_outer_round
                ):
                    raise TrainingWorkerEventConflict(
                        "checkpoint is not from the latest finalized outer round"
                    )
                clean_checkpoint = filter_secrets(checkpoint)
                worker.bootstrap_checkpoint = clean_checkpoint
                run.artifacts = [
                    item
                    for item in run.artifacts
                    if not (
                        item.get("kind") == "phase18_checkpoint"
                        and item.get("outer_round") == checkpoint_round
                    )
                ] + [
                    {
                        "kind": "phase18_checkpoint",
                        "outer_round": checkpoint_round,
                        "checkpoint": clean_checkpoint,
                    }
                ]
                for member in run.workers:
                    if member.state == TrainingWorkerState.RECONNECTING:
                        member.bootstrap_checkpoint = clean_checkpoint
                await self.record_run_event(
                    run,
                    kind="checkpoint_available",
                    payload={"outer_round": checkpoint_round},
                )
        worker.state = TrainingWorkerState.RUNNING
        # Peers may already be COMPLETED if they finished the final checkpoint+complete
        # race; treat them as done so the run can leave CHECKPOINTING.
        done_or_running = {
            TrainingWorkerState.RUNNING,
            TrainingWorkerState.COMPLETED,
            TrainingWorkerState.STOPPED,
        }
        if run.config_version >= 3:
            active_after_checkpoint = sum(item.state in done_or_running for item in run.workers)
            if (
                active_after_checkpoint >= self._minimum_workers(run)
                and run.state == TrainingRunState.CHECKPOINTING
            ):
                await self.transition(run, TrainingRunState.RUNNING)
        elif all(item.state in done_or_running for item in run.workers):
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
        if run.config_version >= 3 and run.current_outer_round > 0:
            worker.state = TrainingWorkerState.RECONNECTING
            latest_checkpoint = next(
                (
                    item.get("checkpoint")
                    for item in reversed(run.artifacts)
                    if item.get("kind") == "phase18_checkpoint"
                    and item.get("outer_round") == run.current_outer_round
                    and isinstance(item.get("checkpoint"), dict)
                ),
                None,
            )
            worker.bootstrap_checkpoint = latest_checkpoint
            worker.progress = {
                **worker.progress,
                "bootstrap_required": True,
                "bootstrap_round": run.current_outer_round,
            }
        else:
            worker.state = (
                TrainingWorkerState.READY
                if run.state in {TrainingRunState.PREPARING, TrainingRunState.READY}
                else TrainingWorkerState.RUNNING
            )

    @staticmethod
    async def _handle_bootstrap_completed_event(
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        if run.config_version < 3:
            raise TrainingWorkerEventValidationError("bootstrap_completed is Phase 18 only")
        if worker.state != TrainingWorkerState.RECONNECTING:
            raise TrainingRunTransitionError("worker is not awaiting checkpoint bootstrap")
        outer_round = payload.get("outer_round")
        if not isinstance(outer_round, int) or isinstance(outer_round, bool):
            raise TrainingWorkerEventValidationError(
                "checkpoint bootstrap requires an integer outer_round"
            )
        if outer_round != run.current_outer_round:
            raise TrainingWorkerEventConflict("worker bootstrap is not from the latest outer round")
        checkpoint = payload.get("checkpoint")
        if checkpoint is not None and not isinstance(checkpoint, dict):
            raise TrainingWorkerEventValidationError(
                "checkpoint bootstrap metadata must be an object"
            )
        worker.bootstrap_checkpoint = filter_secrets(checkpoint) if checkpoint else None
        worker.state = TrainingWorkerState.RUNNING
        worker.last_heartbeat_at = now
        worker.error = None
        worker.progress = {
            **worker.progress,
            "bootstrap_required": False,
            "bootstrap_round": outer_round,
        }

    async def _handle_shutdown_event(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        payload: dict[str, Any],
        now: datetime,
    ) -> None:
        del payload
        worker.state = TrainingWorkerState.STOPPED
        worker.stopped_at = now
        if run.config_version >= 3:
            active_count = sum(
                item.state
                not in {
                    TrainingWorkerState.STOPPED,
                    TrainingWorkerState.RECONNECTING,
                    TrainingWorkerState.FAILED,
                    TrainingWorkerState.CANCELLED,
                    TrainingWorkerState.ABORTED,
                }
                for item in run.workers
            )
            if active_count < self._minimum_workers(run):
                await self.fail(
                    run,
                    error="active membership fell below min_k after worker leave",
                    failed_worker=worker,
                )

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
        if self._run_membership_completed(run):
            await self.transition(run, TrainingRunState.COMPLETED)

    @staticmethod
    def _event_round(payload: dict[str, Any]) -> int:
        value = payload.get("round")
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise TrainingWorkerEventValidationError("event requires a positive round")
        return value

    @staticmethod
    def _minimum_workers(run: TrainingRun) -> int:
        if run.config_version < 3:
            return len(run.workers)
        phase18 = run.config.get("phase18")
        if not isinstance(phase18, dict):
            return len(run.workers)
        value = phase18.get("min_k", len(run.workers))
        return int(value) if isinstance(value, int) and value > 0 else len(run.workers)

    @classmethod
    def _run_membership_completed(cls, run: TrainingRun) -> bool:
        if not run.workers:
            return False
        if run.config_version < 3:
            return all(item.state == TrainingWorkerState.COMPLETED for item in run.workers)
        completed = sum(item.state == TrainingWorkerState.COMPLETED for item in run.workers)
        inactive = {
            TrainingWorkerState.COMPLETED,
            TrainingWorkerState.STOPPED,
            TrainingWorkerState.RECONNECTING,
            TrainingWorkerState.FAILED,
            TrainingWorkerState.CANCELLED,
            TrainingWorkerState.ABORTED,
        }
        return completed >= cls._minimum_workers(run) and all(
            item.state in inactive for item in run.workers
        )

    async def add_artifact(self, run: TrainingRun, artifact: dict[str, Any]) -> TrainingRun:
        run.artifacts = [*run.artifacts, filter_secrets(artifact)]
        await self.session.flush()
        return run
