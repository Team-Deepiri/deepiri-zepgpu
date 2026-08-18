"""Idempotent Phase 18 distributed launcher over persisted placement plans."""

from __future__ import annotations

import hashlib
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.training_run import (
    TrainingGpuReservation,
    TrainingIsland,
    TrainingReservationState,
    TrainingRun,
    TrainingRunState,
    TrainingWorker,
)
from deepiri_zepgpu.database.models.vpn_models import Peer
from deepiri_zepgpu.database.repositories.training_reservation_repository import (
    TrainingReservationRepository,
)
from deepiri_zepgpu.database.repositories.training_run_repository import TrainingRunRepository
from deepiri_zepgpu.training.config import TrainingRunConfig
from deepiri_zepgpu.training.credentials import (
    RunCredential,
    credential_id_hash,
    issue_run_credential,
)
from deepiri_zepgpu.training.island_runtime import IslandRankAssignment
from deepiri_zepgpu.training.placement import PlacementPlan, PlacementStatus


def _find_free_local_port() -> int:
    """Return an available local TCP port chosen by the OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class TrainingLaunchError(RuntimeError):
    pass


@dataclass(slots=True)
class WorkerLaunchSpec:
    worker_id: str
    provider_id: str
    island_id: str
    global_rank: int
    island_rank: int
    world_size: int
    island_world_size: int
    assigned_devices: list[int]
    processes: list[IslandRankAssignment]
    credential: str | None
    credential_expires_at: datetime | None
    config: dict[str, Any]
    rendezvous: dict[str, str | int] | None = None


@dataclass(slots=True)
class LaunchResult:
    run_id: str
    launch_key: str
    idempotent: bool
    reservation_ids: list[str]
    workers: list[WorkerLaunchSpec]


class DistributedTrainingLauncher:
    def __init__(self, session: AsyncSession, *, credential_secret: bytes) -> None:
        self.session = session
        self.credential_secret = credential_secret
        self.run_repository = TrainingRunRepository(session)
        self.reservation_repository = TrainingReservationRepository(session)

    async def launch(  # noqa: C901
        self,
        run: TrainingRun,
        *,
        reservation_owner: str,
        now: datetime | None = None,
    ) -> LaunchResult:
        config = TrainingRunConfig.model_validate(run.config)
        if config.phase18 is None or config.schema_version != 3:
            raise TrainingLaunchError("Phase 18 launcher requires a schema-version 3 run")
        if run.placement_plan is None:
            raise TrainingLaunchError("run has no persisted placement plan")
        plan = PlacementPlan.model_validate(run.placement_plan)
        if plan.status == PlacementStatus.INSUFFICIENT:
            raise TrainingLaunchError("persisted placement plan is insufficient")
        launch_key = hashlib.sha256(f"{run.id}:{plan.plan_id}".encode()).hexdigest()

        locked = await self.run_repository._lock_run(run.id)
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        await self.run_repository.enforce_startup_deadline(locked, now=current)
        if locked.state in {
            TrainingRunState.COMPLETED,
            TrainingRunState.FAILED,
            TrainingRunState.CANCELLED,
            TrainingRunState.TIMED_OUT,
        }:
            raise TrainingLaunchError(f"cannot launch terminal run in state {locked.state.value}")
        created_at = locked.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        readiness_deadline = created_at + timedelta(
            seconds=config.phase18.readiness_timeout_seconds
        )
        if locked.state == TrainingRunState.CREATED and current >= readiness_deadline:
            raise TrainingLaunchError("training placement readiness deadline expired")
        if locked.launch_key is not None:
            if locked.launch_key != launch_key:
                raise TrainingLaunchError(
                    "run was already launched from a different placement plan"
                )
            specs = self._worker_specs(locked, plan, credentials={})
            reservations = await self._active_reservations(str(locked.id))
            return LaunchResult(
                run_id=str(locked.id),
                launch_key=launch_key,
                idempotent=True,
                reservation_ids=[str(item.id) for item in reservations],
                workers=specs,
            )
        selected_providers = sorted(plan.selected_provider_ids)
        existing_providers = sorted(str(worker.peer_id) for worker in locked.workers)
        if existing_providers != selected_providers:
            raise TrainingLaunchError(
                "persisted workers do not match the selected placement providers"
            )

        islands = await self._persist_islands(locked, plan)
        try:
            reservations = await self.reservation_repository.reserve_plan(
                run=locked,
                plan=plan,
                owner=reservation_owner,
                ttl_seconds=config.phase18.reservation_ttl_seconds,
            )
            assignments = self._assign_ranks(locked.workers, plan)
            rendezvous = await self._build_rendezvous(plan)
            for worker in locked.workers:
                worker_assignments = assignments[str(worker.peer_id)]
                first = worker_assignments[0]
                worker.island_id = first.island_id
                worker.global_rank = first.global_rank
                worker.island_rank = first.island_rank
                worker.world_size = first.world_size
                worker.island_world_size = first.island_world_size
                worker.assigned_devices = [item.device_index for item in worker_assignments]
                worker.progress = {
                    **worker.progress,
                    "phase18_rendezvous": rendezvous.get(first.island_id),
                }
            workers_by_peer = {str(item.peer_id): item for item in locked.workers}
            for reservation in reservations:
                reservation.worker_id = workers_by_peer[str(reservation.peer_id)].id

                if reservation.island_id is None:
                    selected = next(
                        item
                        for item in plan.selected_gpus
                        if item.gpu_share_id == str(reservation.gpu_share_id)
                    )
                    reservation.island_id = islands[selected.island_id].id
            credentials = self._issue_credentials(locked, now=now)
            locked.launch_key = launch_key
            locked.launched_at = current
            if locked.state == TrainingRunState.CREATED:
                await self.run_repository.prepare(locked)
            await self.run_repository.record_run_event(
                locked,
                kind="placement_selected",
                payload={
                    "plan_id": plan.plan_id,
                    "status": plan.status.value,
                    "island_ids": plan.selected_island_ids,
                    "selected_gpu_count": len(plan.selected_gpus),
                    "warnings": plan.warnings,
                },
            )
            await self.run_repository.record_run_event(
                locked,
                kind="launch_prepared",
                payload={
                    "launch_key": launch_key,
                    "worker_count": len(locked.workers),
                    "reservation_count": len(reservations),
                },
            )
            await self.session.flush()
        except Exception as exc:
            # Reservation savepoints are all-or-none. Any post-reservation failure is
            # followed by ownership-scoped cleanup, then the first failure is retained.
            cleanup_errors: list[str] = []
            try:
                await self.reservation_repository.release_terminal(
                    run_id=str(locked.id), reason="Phase 18 launch failed"
                )
            except Exception as cleanup_exc:  # pragma: no cover - database failure path
                cleanup_errors.append(str(cleanup_exc))
            try:
                if locked.state in {
                    TrainingRunState.CREATED,
                    TrainingRunState.PREPARING,
                    TrainingRunState.READY,
                }:
                    if locked.state == TrainingRunState.CREATED:
                        await self.run_repository.prepare(locked)
                    await self.run_repository.transition(
                        locked, TrainingRunState.FAILED, error=f"launch failed: {exc}"
                    )
            except Exception as transition_exc:  # pragma: no cover - database failure path
                cleanup_errors.append(str(transition_exc))
            detail = f"launch failed: {exc}"
            if cleanup_errors:
                detail += f" (cleanup errors: {'; '.join(cleanup_errors)})"
            raise TrainingLaunchError(detail) from exc
        self.run_repository._overlay_run(run, locked)
        return LaunchResult(
            run_id=str(locked.id),
            launch_key=launch_key,
            idempotent=False,
            reservation_ids=[str(item.id) for item in reservations],
            workers=self._worker_specs(locked, plan, credentials=credentials),
        )

    async def cancel(self, run: TrainingRun, *, reason: str = "cancelled by owner") -> TrainingRun:
        await self.run_repository.record_run_event(run, kind="cancellation_requested", payload={})
        result = await self.run_repository.abort(run)
        await self.run_repository.record_run_event(
            result, kind="terminal_cleanup", payload={"reason": reason}
        )
        return result

    async def enforce_deadlines(self, run: TrainingRun) -> TrainingRun:
        return await self.run_repository.enforce_startup_deadline(run)

    async def _persist_islands(
        self, run: TrainingRun, plan: PlacementPlan
    ) -> dict[str, TrainingIsland]:
        selected = set(plan.selected_island_ids)
        existing_result = await self.session.execute(
            select(TrainingIsland).where(TrainingIsland.run_id == run.id)
        )
        existing = {str(item.id): item for item in existing_result.scalars().all()}
        for island in plan.candidate_islands:
            if island.island_id not in selected:
                continue
            if island.island_id in existing:
                continue
            record = TrainingIsland(
                id=uuid.UUID(island.island_id),
                run_id=run.id,
                classification=island.classification,
                provider_ids=island.provider_ids,
                gpu_share_ids=island.gpu_share_ids,
                strategy_eligibility=island.eligibility.model_dump(mode="json"),
                topology=island.model_dump(mode="json"),
                explanation=island.explanation,
            )
            self.session.add(record)
            existing[island.island_id] = record
        await self.session.flush()
        for island_id in sorted(selected):
            await self.run_repository.record_run_event(
                run, kind="island_created", payload={"island_id": island_id}
            )
        return existing

    def _assign_ranks(
        self, workers: list[TrainingWorker], plan: PlacementPlan
    ) -> dict[str, list[IslandRankAssignment]]:
        workers_by_provider = {str(worker.peer_id): worker for worker in workers}
        ordered = sorted(
            plan.selected_gpus,
            key=lambda item: (
                item.island_id,
                item.provider_id,
                item.device_index,
                item.gpu_share_id,
            ),
        )
        island_sizes: dict[str, int] = {}
        for item in ordered:
            island_sizes[item.island_id] = island_sizes.get(item.island_id, 0) + 1
        island_offsets: dict[str, int] = {}
        output: dict[str, list[IslandRankAssignment]] = {
            provider_id: [] for provider_id in workers_by_provider
        }
        for global_rank, item in enumerate(ordered):
            island_rank = island_offsets.get(item.island_id, 0)
            island_offsets[item.island_id] = island_rank + 1
            worker = workers_by_provider[item.provider_id]
            output[item.provider_id].append(
                IslandRankAssignment(
                    worker_id=str(worker.id),
                    provider_id=item.provider_id,
                    gpu_share_id=item.gpu_share_id,
                    device_index=item.device_index,
                    global_rank=global_rank,
                    island_rank=island_rank,
                    world_size=len(ordered),
                    island_world_size=island_sizes[item.island_id],
                    island_id=item.island_id,
                )
            )
        if any(not assignments for assignments in output.values()):
            raise TrainingLaunchError("every selected worker requires at least one GPU assignment")
        return output

    def _issue_credentials(
        self, run: TrainingRun, *, now: datetime | None
    ) -> dict[str, tuple[str, datetime]]:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        expires_epoch = int(current.timestamp()) + 900
        expires_at = datetime.fromtimestamp(expires_epoch, UTC)
        result: dict[str, tuple[str, datetime]] = {}
        for worker in sorted(run.workers, key=lambda item: str(item.peer_id)):
            credential_id = str(uuid.uuid4())
            credential = RunCredential(
                room_id=str(run.vpn_network_id),
                run_id=str(run.id),
                worker_id=str(worker.id),
                peer_id=str(worker.peer_id),
                credential_id=credential_id,
                expires_at=expires_epoch,
            )
            token = issue_run_credential(credential, self.credential_secret)
            worker.credential_id_hash = credential_id_hash(credential_id)
            worker.credential_expires_at = expires_at
            worker.credential_revoked_at = None
            result[str(worker.id)] = (token, expires_at)
        return result

    async def _build_rendezvous(self, plan: PlacementPlan) -> dict[str, dict[str, str | int]]:
        """Create island-local rendezvous addresses for NCCL workers."""

        output: dict[str, dict[str, str | int]] = {}
        selected = set(plan.selected_island_ids)

        for island in sorted(
            plan.candidate_islands,
            key=lambda item: item.island_id,
        ):
            if island.island_id not in selected:
                continue

            if island.classification == "same_host":
                master_addr = "127.0.0.1"
                master_port = _find_free_local_port()

            elif island.classification == "lan":
                leader_id = sorted(island.provider_ids)[0]
                result = await self.session.execute(select(Peer.vpn_ip).where(Peer.id == leader_id))
                leader_addr = result.scalar_one_or_none()
                if not leader_addr:
                    raise TrainingLaunchError(
                        "LAN island leader has no room/VPN address " "for process-group rendezvous"
                    )

                master_addr = str(leader_addr)

                # Multi-host rendezvous cannot safely use a locally probed
                # ephemeral port because every participating provider must
                # agree on the same port. Retain the deterministic Phase 18
                # LAN rendezvous range.
                master_port = (
                    20_000
                    + int(
                        hashlib.sha256(island.island_id.encode()).hexdigest()[:8],
                        16,
                    )
                    % 10_000
                )

            else:
                # WAN workers are independent DiLoCo participants and do not
                # share an NCCL/FSDP process-group rendezvous.
                continue

            output[island.island_id] = {
                "master_addr": master_addr,
                "master_port": master_port,
            }

        return output

    def _worker_specs(
        self,
        run: TrainingRun,
        plan: PlacementPlan,
        *,
        credentials: dict[str, tuple[str, datetime]],
    ) -> list[WorkerLaunchSpec]:
        assignments = self._assign_ranks(run.workers, plan)
        specs: list[WorkerLaunchSpec] = []
        for worker in sorted(run.workers, key=lambda item: str(item.peer_id)):
            processes = assignments[str(worker.peer_id)]
            first = processes[0]
            token_info = credentials.get(str(worker.id))
            specs.append(
                WorkerLaunchSpec(
                    worker_id=str(worker.id),
                    provider_id=str(worker.peer_id),
                    island_id=first.island_id,
                    global_rank=first.global_rank,
                    island_rank=first.island_rank,
                    world_size=first.world_size,
                    island_world_size=first.island_world_size,
                    assigned_devices=[item.device_index for item in processes],
                    processes=processes,
                    credential=token_info[0] if token_info else None,
                    credential_expires_at=token_info[1] if token_info else None,
                    config=run.config,
                    rendezvous=(
                        dict(worker.progress["phase18_rendezvous"])
                        if isinstance(worker.progress.get("phase18_rendezvous"), dict)
                        else None
                    ),
                )
            )
        return specs

    async def _active_reservations(self, run_id: str) -> list[TrainingGpuReservation]:
        result = await self.session.execute(
            select(TrainingGpuReservation).where(
                TrainingGpuReservation.run_id == run_id,
                TrainingGpuReservation.state == TrainingReservationState.ACTIVE,
            )
        )
        return list(result.scalars().all())
