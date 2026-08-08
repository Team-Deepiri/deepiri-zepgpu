"""Authoritative elastic DiLoCo coordinator/runtime integration.

The process-local coordinator is a cache of live aggregation state. Durable
checkpoints and TrainingOuterRound rows remain authoritative across process
restarts. If a process dies during an open outer round, the round is restarted
from the latest durable global state and workers may safely resubmit their
idempotent round update.
"""

from __future__ import annotations

import asyncio
import weakref
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.training_run import (
    TrainingOuterRound,
    TrainingOuterRoundState,
    TrainingRun,
    TrainingRunState,
    TrainingWorker,
    TrainingWorkerState,
)
from deepiri_zepgpu.database.repositories.training_run_repository import (
    TERMINAL_STATES,
    TrainingRunRepository,
)
from deepiri_zepgpu.training.binary import BinaryEnvelope
from deepiri_zepgpu.training.checkpoint import Phase18CheckpointMetadata
from deepiri_zepgpu.training.config import DistributedStrategy, TrainingRunConfig
from deepiri_zepgpu.training.diloco import (
    ElasticDiLoCoCoordinator,
    MembershipState,
    RoundState,
    UpdateDisposition,
    UpdateReceipt,
    decode_state_envelope,
    encode_state_envelope,
)


class Phase18RuntimeError(RuntimeError):
    pass


@dataclass(slots=True)
class Phase18RoundResult:
    receipt: UpdateReceipt
    state: RoundState
    round_number: int
    accepted_worker_ids: list[str]
    finalized: bool


@dataclass(slots=True)
class _RuntimeEntry:
    coordinator: ElasticDiLoCoCoordinator
    initial_state: dict[str, np.ndarray]
    registered_worker_ids: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_INACTIVE_WORKER_STATES = {
    TrainingWorkerState.RECONNECTING,
    TrainingWorkerState.STOPPING,
    TrainingWorkerState.STOPPED,
    TrainingWorkerState.ABORTED,
    TrainingWorkerState.COMPLETED,
    TrainingWorkerState.FAILED,
    TrainingWorkerState.CANCELLED,
}


class Phase18CoordinatorRuntime:
    """Production service boundary around the one ElasticDiLoCoCoordinator."""

    _entries: ClassVar[dict[str, _RuntimeEntry]] = {}
    _registry_locks: ClassVar[
        weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]
    ] = weakref.WeakKeyDictionary()

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.run_repository = TrainingRunRepository(session)

    @classmethod
    def _get_registry_lock(cls) -> asyncio.Lock:
        """Return the registry lock associated with the current event loop."""
        loop = asyncio.get_running_loop()
        lock = cls._registry_locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            cls._registry_locks[loop] = lock
        return lock

    @classmethod
    def discard(cls, run_id: str) -> None:
        cls._entries.pop(run_id, None)

    @classmethod
    def discard_all(cls) -> None:
        cls._entries.clear()

    async def register(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        encoded_initial_state: bytes,
    ) -> tuple[int, bool]:
        config = self._diloco_config(run)
        _, state = decode_state_envelope(
            encoded_initial_state,
            room_id=str(run.vpn_network_id),
            run_id=str(run.id),
            worker_id=str(worker.id),
            round_number=0,
            payload_types={"diloco_initial_state"},
        )
        entry = await self._entry(run, config, state)
        async with entry.lock:
            # Before the first finalized round, every worker must agree on the
            # same initial adapter state. After checkpoint recovery, registration
            # is only an identity/liveness handshake: the worker is required to
            # bootstrap the durable checkpoint before contributing a newer round,
            # so its pre-bootstrap local state does not need to equal the recovered
            # coordinator state.
            if entry.coordinator.current_round == 0 and (
                set(entry.initial_state) != set(state)
                or any(
                    not np.array_equal(entry.initial_state[name], state[name])
                    for name in entry.initial_state
                )
            ):
                raise Phase18RuntimeError("worker initial adapter state differs from the run")
            entry.registered_worker_ids.add(str(worker.id))
            member = entry.coordinator.members[str(worker.id)]
            bootstrap_required = entry.coordinator.current_round > 0
            if member.state != MembershipState.ACTIVE:
                entry.coordinator.request_join(str(worker.id))
            if not bootstrap_required:
                member.state = MembershipState.ACTIVE
                member.bootstrapped_round = 0
            await self._sync_membership(entry, run)
            await self.run_repository.record_run_event(
                run,
                kind="phase18_runtime_registered",
                payload={
                    "worker_id": str(worker.id),
                    "bootstrap_required": bootstrap_required,
                    "outer_round": entry.coordinator.current_round,
                },
            )
            return entry.coordinator.current_round, bootstrap_required

    async def submit_update(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        encoded_update: bytes,
        *,
        now: datetime | None = None,
    ) -> Phase18RoundResult:
        config = self._diloco_config(run)
        if run.state not in {
            TrainingRunState.RUNNING,
            TrainingRunState.SYNCING,
            TrainingRunState.CHECKPOINTING,
        }:
            raise Phase18RuntimeError("outer updates require a running Phase 18 run")
        entry = await self._existing_entry(run, config)
        current = self._aware(now or datetime.now(UTC))
        envelope = BinaryEnvelope.decode(
            encoded_update,
            expected_room_id=str(run.vpn_network_id),
            expected_run_id=str(run.id),
            expected_worker_id=str(worker.id),
        )
        async with entry.lock:
            await self._sync_membership(entry, run)
            coordinator = entry.coordinator
            active = coordinator.active_round
            next_round = coordinator.current_round + 1
            if active is None or active.state == RoundState.FINALIZED:
                if envelope.round < next_round:
                    receipt = coordinator.submit_encoded(encoded_update)
                    await self._persist_receipt(run, coordinator, receipt)
                    return Phase18RoundResult(
                        receipt=receipt,
                        state=RoundState.FINALIZED,
                        round_number=coordinator.current_round,
                        accepted_worker_ids=(sorted(active.updates) if active is not None else []),
                        finalized=True,
                    )
                if envelope.round != next_round:
                    raise Phase18RuntimeError(
                        f"outer update round {envelope.round} does not match next round {next_round}"
                    )
                coordinator.start_round(now=current)
                await self._persist_open_round(run, coordinator)
                if run.state == TrainingRunState.RUNNING:
                    await self.run_repository.transition(run, TrainingRunState.SYNCING)
            receipt = coordinator.submit_encoded(encoded_update)
            await self._persist_receipt(run, coordinator, receipt)
            metric = coordinator.finalize_round(now=current)
            if metric is not None:
                await self._persist_outcome(run, coordinator, now=current)
            active = coordinator.active_round
            if active is None:  # pragma: no cover - start_round created it
                raise Phase18RuntimeError("outer round state disappeared")
            return Phase18RoundResult(
                receipt=receipt,
                state=active.state,
                round_number=active.number,
                accepted_worker_ids=sorted(active.updates),
                finalized=active.state == RoundState.FINALIZED,
            )

    async def poll_round(
        self,
        run: TrainingRun,
        *,
        round_number: int,
        now: datetime | None = None,
    ) -> RoundState:
        config = self._diloco_config(run)
        entry = await self._existing_entry(run, config)
        current = self._aware(now or datetime.now(UTC))
        async with entry.lock:
            await self._sync_membership(entry, run)
            active = entry.coordinator.active_round
            if active is None or active.number != round_number:
                if round_number <= entry.coordinator.current_round:
                    return RoundState.FINALIZED
                raise Phase18RuntimeError("requested outer round is not active")
            metric = entry.coordinator.finalize_round(now=current)
            if metric is not None:
                await self._persist_outcome(run, entry.coordinator, now=current)
            return active.state

    async def global_state(
        self,
        run: TrainingRun,
        worker: TrainingWorker,
        *,
        round_number: int,
    ) -> bytes | None:
        config = self._diloco_config(run)
        entry = await self._existing_entry(run, config)
        async with entry.lock:
            if round_number > entry.coordinator.current_round:
                return None
            if round_number != entry.coordinator.current_round:
                raise Phase18RuntimeError("only the latest finalized state is available")
            member = entry.coordinator.members[str(worker.id)]
            if (
                member.state == MembershipState.ACTIVE
                and member.bootstrapped_round < round_number
                and entry.coordinator.latest_checkpoint is not None
            ):
                # A live deadline straggler did not contribute, but receiving
                # the finalized state explicitly bootstraps it for the next H
                # interval.  Accepted workers were advanced during finalize.
                entry.coordinator.bootstrap_worker(
                    str(worker.id), entry.coordinator.latest_checkpoint
                )
                worker.bootstrap_checkpoint = entry.coordinator.latest_checkpoint.model_dump(
                    mode="json"
                )
                worker.progress = {
                    **worker.progress,
                    "bootstrap_required": False,
                    "bootstrap_round": round_number,
                }
                await self.session.flush()
            return encode_state_envelope(
                room_id=str(run.vpn_network_id),
                run_id=str(run.id),
                worker_id=str(worker.id),
                round_number=round_number,
                state=entry.coordinator.global_state,
            )

    async def bootstrap(self, run: TrainingRun, worker: TrainingWorker) -> bytes:
        config = self._diloco_config(run)
        entry = await self._existing_entry(run, config)
        async with entry.lock:
            checkpoint = entry.coordinator.latest_checkpoint
            if checkpoint is None:
                raise Phase18RuntimeError("no finalized checkpoint is available")
            entry.coordinator.bootstrap_worker(str(worker.id), checkpoint)
            worker.state = TrainingWorkerState.RUNNING
            worker.error = None
            worker.bootstrap_checkpoint = checkpoint.model_dump(mode="json")
            worker.progress = {
                **worker.progress,
                "bootstrap_required": False,
                "bootstrap_round": checkpoint.outer_round,
            }
            await self.run_repository.record_run_event(
                run,
                kind="checkpoint_bootstrap",
                payload={"worker_id": str(worker.id), "outer_round": checkpoint.outer_round},
            )
            await self.session.flush()
            return encode_state_envelope(
                room_id=str(run.vpn_network_id),
                run_id=str(run.id),
                worker_id=str(worker.id),
                round_number=checkpoint.outer_round,
                state=entry.coordinator.global_state,
            )

    async def mark_worker_failed(
        self, run: TrainingRun, worker: TrainingWorker, *, reason: str
    ) -> None:
        self._diloco_config(run)
        entry = self._entries.get(str(run.id))
        if entry is None:
            # A process may fail before registering adapter state.  Persistence
            # already records that failure; there is no active aggregation to
            # update yet.
            return
        async with entry.lock:
            member = entry.coordinator.members[str(worker.id)]
            if member.state not in {MembershipState.FAILED, MembershipState.LEFT}:
                entry.coordinator.mark_failed(str(worker.id), reason=reason)
            active = entry.coordinator.active_round
            if active is not None and active.state == RoundState.OPEN:
                metric = entry.coordinator.finalize_round(now=datetime.now(UTC))
                if metric is not None:
                    await self._persist_outcome(run, entry.coordinator, now=datetime.now(UTC))

    async def _entry(
        self,
        run: TrainingRun,
        config: TrainingRunConfig,
        initial_state: dict[str, np.ndarray],
    ) -> _RuntimeEntry:
        run_id = str(run.id)
        existing = self._entries.get(run_id)
        if existing is not None:
            return existing
        async with self._get_registry_lock():
            existing = self._entries.get(run_id)
            if existing is not None:
                return existing
            worker_ids = sorted(str(item.id) for item in run.workers)
            coordinator = ElasticDiLoCoCoordinator(
                room_id=str(run.vpn_network_id),
                run_id=run_id,
                config=config,
                initial_state=initial_state,
                worker_ids=worker_ids,
                placement=run.placement_plan,
            )
            for worker_id in worker_ids:
                coordinator.mark_failed(worker_id, reason="worker has not registered")
            checkpoint = self._latest_checkpoint(run)
            if checkpoint is not None:
                coordinator.restore_checkpoint(checkpoint)
            entry = _RuntimeEntry(coordinator=coordinator, initial_state=initial_state)
            self._entries[run_id] = entry
            return entry

    async def _existing_entry(self, run: TrainingRun, config: TrainingRunConfig) -> _RuntimeEntry:
        entry = self._entries.get(str(run.id))
        if entry is not None:
            return entry
        checkpoint = self._latest_checkpoint(run)
        if checkpoint is None:
            raise Phase18RuntimeError("Phase 18 workers must register initial state first")
        state = {
            name: np.asarray(payload["values"], dtype=np.float32).reshape(payload["shape"])
            for name, payload in checkpoint.model_state.items()
        }
        return await self._entry(run, config, state)

    async def _sync_membership(self, entry: _RuntimeEntry, run: TrainingRun) -> None:
        for worker in run.workers:
            worker_id = str(worker.id)
            member = entry.coordinator.members[worker_id]
            if worker.state in _INACTIVE_WORKER_STATES:
                if member.state not in {MembershipState.FAILED, MembershipState.LEFT}:
                    entry.coordinator.mark_failed(
                        worker_id, reason=f"persisted worker state is {worker.state.value}"
                    )
            elif (
                worker_id in entry.registered_worker_ids
                and entry.coordinator.current_round == 0
                and member.state != MembershipState.ACTIVE
            ):
                entry.coordinator.request_join(worker_id)

    async def _persist_open_round(
        self, run: TrainingRun, coordinator: ElasticDiLoCoCoordinator
    ) -> None:
        active = coordinator.active_round
        if active is None:  # pragma: no cover - caller just started it
            raise Phase18RuntimeError("cannot persist a missing outer round")
        result = await self.session.execute(
            select(TrainingOuterRound).where(
                TrainingOuterRound.run_id == run.id,
                TrainingOuterRound.round_number == active.number,
            )
        )
        row = result.scalar_one_or_none()
        event_kind = "outer_round_started"
        event_payload: dict[str, object] = {
            "round": active.number,
            "expected_worker_ids": active.expected_worker_ids,
            "min_k": coordinator.job.min_k,
            "deadline_at": active.deadline_at.isoformat(),
            "policy": "all_active_or_deadline",
        }
        if row is None:
            row = TrainingOuterRound(
                run_id=run.id,
                round_number=active.number,
                state=TrainingOuterRoundState.OPEN,
                expected_workers=len(active.expected_worker_ids),
                min_k=coordinator.job.min_k,
                accepted_worker_ids=[],
                rejected_updates=[],
                metrics={"policy": "all_active_or_deadline"},
                optimizer_state=coordinator.outer_optimizer.state_dict(),
                deadline_at=active.deadline_at,
            )
            self.session.add(row)
        elif row.state == TrainingOuterRoundState.OPEN:
            # An OPEN row with no corresponding process-local active round means
            # the coordinator process lost its volatile aggregation session. The
            # database intentionally does not persist model-sized update tensors,
            # so claiming the old accepted_worker_ids were still aggregated would
            # be unsafe. Restart this same round number from the latest durable
            # global/checkpoint state and require idempotent worker resubmission.
            discarded_worker_ids = list(row.accepted_worker_ids)
            previous_recovery = row.metrics.get("recovery")
            recovery_count = (
                int(previous_recovery.get("count", 0)) + 1
                if isinstance(previous_recovery, dict)
                else 1
            )
            recovered_at = datetime.now(UTC)
            row.expected_workers = len(active.expected_worker_ids)
            row.min_k = coordinator.job.min_k
            row.accepted_worker_ids = []
            row.optimizer_state = coordinator.outer_optimizer.state_dict()
            row.deadline_at = active.deadline_at
            row.finalized_at = None
            row.metrics = {
                **row.metrics,
                "policy": "all_active_or_deadline",
                "recovery": {
                    "count": recovery_count,
                    "last_recovered_at": recovered_at.isoformat(),
                    "checkpoint_round": coordinator.current_round,
                    "discarded_accepted_worker_ids": discarded_worker_ids,
                    "policy": "restart_open_round_and_require_resubmission",
                },
            }
            event_kind = "outer_round_recovered"
            event_payload = {
                **event_payload,
                "checkpoint_round": coordinator.current_round,
                "discarded_accepted_worker_ids": discarded_worker_ids,
                "recovery_count": recovery_count,
            }
        else:
            raise Phase18RuntimeError("persisted outer round is already terminal")
        await self.run_repository.record_run_event(
            run,
            kind=event_kind,
            payload=event_payload,
        )
        await self.session.flush()

    async def _persist_receipt(
        self,
        run: TrainingRun,
        coordinator: ElasticDiLoCoCoordinator,
        receipt: UpdateReceipt,
    ) -> None:
        active = coordinator.active_round
        if active is None:  # pragma: no cover
            raise Phase18RuntimeError("cannot persist receipt without an active round")
        result = await self.session.execute(
            select(TrainingOuterRound)
            .where(
                TrainingOuterRound.run_id == run.id,
                TrainingOuterRound.round_number == active.number,
            )
            .with_for_update()
        )
        row = result.scalar_one()
        row.accepted_worker_ids = sorted(active.updates)
        row.rejected_updates = list(active.rejected)
        await self.run_repository.record_run_event(
            run,
            kind=(
                "outer_update_accepted"
                if receipt.disposition == UpdateDisposition.ACCEPTED
                else "outer_update_rejected"
            ),
            payload={
                "worker_id": receipt.worker_id,
                "round": receipt.round_number,
                "disposition": receipt.disposition.value,
                "reason": receipt.reason,
            },
        )
        await self.session.flush()

    async def _persist_outcome(
        self,
        run: TrainingRun,
        coordinator: ElasticDiLoCoCoordinator,
        *,
        now: datetime,
    ) -> None:
        active = coordinator.active_round
        if active is None:  # pragma: no cover
            raise Phase18RuntimeError("cannot persist missing outer round")
        result = await self.session.execute(
            select(TrainingOuterRound)
            .where(
                TrainingOuterRound.run_id == run.id,
                TrainingOuterRound.round_number == active.number,
            )
            .with_for_update()
        )
        row = result.scalar_one()
        row.accepted_worker_ids = sorted(active.updates)
        row.rejected_updates = list(active.rejected)
        row.optimizer_state = coordinator.outer_optimizer.state_dict()
        metric = coordinator.metrics[-1] if coordinator.metrics else None
        if active.state == RoundState.FINALIZED and metric is not None:
            row.state = TrainingOuterRoundState.FINALIZED
            row.finalized_at = now
            row.metrics = {
                **row.metrics,
                "runtime": {
                    "round_number": metric.round_number,
                    "state": metric.state.value,
                    "expected_workers": metric.expected_workers,
                    "accepted_workers": metric.accepted_workers,
                    "min_k": metric.min_k,
                    "straggler_worker_ids": metric.straggler_worker_ids,
                    "blocked_sync_seconds": metric.blocked_sync_seconds,
                    "uncompressed_bytes": metric.uncompressed_bytes,
                    "compressed_bytes": metric.compressed_bytes,
                    "compression_ratio": metric.compression_ratio,
                },
            }
            run.current_outer_round = coordinator.current_round
            checkpoint = coordinator.latest_checkpoint
            if checkpoint is None:  # pragma: no cover
                raise Phase18RuntimeError("finalized round did not create a checkpoint")
            checkpoint_json = checkpoint.model_dump(mode="json")
            run.artifacts = [
                item
                for item in run.artifacts
                if not (
                    item.get("kind") == "phase18_checkpoint"
                    and item.get("outer_round") == coordinator.current_round
                )
            ] + [
                {
                    "kind": "phase18_checkpoint",
                    "outer_round": coordinator.current_round,
                    "checkpoint": checkpoint_json,
                }
            ]
            for worker in run.workers:
                if str(worker.id) in active.updates:
                    worker.current_round = coordinator.current_round
                    worker.state = TrainingWorkerState.RUNNING
                    worker.progress = {**worker.progress, "round_status": "completed"}
                elif worker.state == TrainingWorkerState.RECONNECTING:
                    worker.bootstrap_checkpoint = checkpoint_json
            if run.state == TrainingRunState.SYNCING:
                await self.run_repository.transition(run, TrainingRunState.RUNNING)
            await self.run_repository.record_run_event(
                run,
                kind="outer_round_finalized",
                payload={
                    "round": coordinator.current_round,
                    "accepted_worker_ids": sorted(active.updates),
                    "straggler_worker_ids": metric.straggler_worker_ids,
                    "policy": "all_active_or_deadline",
                },
            )
        elif active.state == RoundState.PAUSED:
            row.state = TrainingOuterRoundState.PAUSED
            row.finalized_at = now
            row.metrics = {
                **row.metrics,
                "accepted_workers": len(active.updates),
                "min_k": coordinator.job.min_k,
            }
            await self.run_repository.record_run_event(
                run,
                kind="outer_round_paused",
                payload={
                    "round": active.number,
                    "accepted_workers": len(active.updates),
                    "min_k": coordinator.job.min_k,
                },
            )
        await self.session.flush()

    @staticmethod
    def _latest_checkpoint(run: TrainingRun) -> Phase18CheckpointMetadata | None:
        for artifact in reversed(run.artifacts):
            checkpoint = artifact.get("checkpoint")
            if artifact.get("kind") == "phase18_checkpoint" and isinstance(checkpoint, dict):
                return Phase18CheckpointMetadata.model_validate(checkpoint)
        return None

    @staticmethod
    def _diloco_config(run: TrainingRun) -> TrainingRunConfig:
        if run.state in TERMINAL_STATES:
            raise Phase18RuntimeError("training run is terminal")
        config = TrainingRunConfig.model_validate(run.config)
        if (
            config.schema_version != 3
            or config.phase18 is None
            or config.phase18.strategy != DistributedStrategy.DILOCO
        ):
            raise Phase18RuntimeError("run does not use the Phase 18 DiLoCo strategy")
        return config

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
