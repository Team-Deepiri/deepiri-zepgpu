"""Training run control plane and binary coordinator relay endpoints."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_db_session, get_required_user
from deepiri_zepgpu.api.server.routes.node_tasks import get_verified_peer
from deepiri_zepgpu.api.server.websocket_manager import manager
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.models import User
from deepiri_zepgpu.database.models.training_run import (
    TrainingGpuReservation,
    TrainingIsland,
    TrainingRun,
    TrainingRunState,
    TrainingWorker,
)
from deepiri_zepgpu.database.models.vpn_models import GpuShare, Peer, VpnNetwork
from deepiri_zepgpu.database.repositories.training_reservation_repository import (
    TrainingReservationError,
    TrainingReservationRepository,
)
from deepiri_zepgpu.database.repositories.training_run_repository import (
    TrainingRunRepository,
    TrainingRunTransitionError,
    TrainingWorkerEventConflict,
    TrainingWorkerEventValidationError,
)
from deepiri_zepgpu.training.binary import EnvelopeError
from deepiri_zepgpu.training.config import TrainingRunConfig
from deepiri_zepgpu.training.credentials import (
    RunCredential,
    credential_id_hash,
    issue_data_plane_secret,
    issue_room_mac_key,
    issue_run_credential,
    verify_run_credential,
)
from deepiri_zepgpu.training.diloco import DiLoCoError
from deepiri_zepgpu.training.elastic_diloco_runtime import (
    Phase18CoordinatorRuntime,
    Phase18RuntimeError,
)
from deepiri_zepgpu.training.launcher import DistributedTrainingLauncher, TrainingLaunchError
from deepiri_zepgpu.training.placement import PlacementPlan, PlacementPlanner, PlacementStatus
from deepiri_zepgpu.training.relay import RedisBinaryRelayStore, TransferConflictError
from deepiri_zepgpu.training.topology import ProviderCandidate, provider_candidate_from_models
from deepiri_zepgpu.vpn.repositories import VpnNetworkRepository

router = APIRouter(prefix="/training-runs", tags=["Training Runs"])
relay_store = RedisBinaryRelayStore(
    settings.redis.url,
    max_transfer_bytes=settings.redis.training_relay_max_transfer_bytes,
    max_chunk_bytes=settings.redis.training_relay_max_chunk_bytes,
    ttl_seconds=settings.redis.training_relay_ttl_seconds,
)


class CreateTrainingRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: UUID
    provider_ids: list[UUID] = Field(min_length=1)
    config: TrainingRunConfig

    @model_validator(mode="after")
    def validate_unique_providers(self) -> CreateTrainingRunRequest:
        if len(self.provider_ids) != len(set(self.provider_ids)):
            raise ValueError("provider_ids must be unique")
        if self.config.distributed.enabled and self.config.phase18 is None:
            # Phase 17 contract is exactly two workers. Later phases should relax
            # this via schema_version / phase-specific validation, not by widening
            # this gate silently.
            if self.config.distributed.worker_count != 2:
                raise ValueError("Phase 17 distributed runs require worker_count=2")
            if len(self.provider_ids) != 2:
                raise ValueError("Phase 17 distributed runs require exactly two provider_ids")
            if self.config.distributed.runtime.privileged:
                raise ValueError("privileged training containers are not allowed")
        return self


class TrainingWorkerResponse(BaseModel):
    id: str
    peer_id: str
    state: str
    current_round: int
    restart_count: int
    last_heartbeat_at: datetime | None
    progress: dict[str, Any]
    ready_at: datetime | None
    stopped_at: datetime | None
    error: str | None
    island_id: str | None = None
    global_rank: int | None = None
    island_rank: int | None = None
    world_size: int | None = None
    island_world_size: int | None = None
    assigned_devices: list[int] = Field(default_factory=list)
    bootstrap_checkpoint: dict[str, Any] | None = None


class TrainingRunResponse(BaseModel):
    id: str
    room_id: str
    user_id: str
    state: str
    config_version: int
    config: dict[str, Any]
    provider_ids: list[str]
    artifacts: list[dict[str, Any]]
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    startup_deadline_at: datetime | None
    placement_plan: dict[str, Any] | None = None
    launched_at: datetime | None = None
    current_outer_round: int = 0
    workers: list[TrainingWorkerResponse] = Field(default_factory=list)


def _response(run: TrainingRun) -> TrainingRunResponse:
    workers = list(run.workers) if "workers" in run.__dict__ else []
    return TrainingRunResponse(
        id=str(run.id),
        room_id=str(run.vpn_network_id),
        user_id=str(run.user_id),
        state=run.state.value,
        config_version=run.config_version,
        config=run.config,
        provider_ids=run.provider_ids,
        artifacts=run.artifacts,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        startup_deadline_at=run.startup_deadline_at,
        placement_plan=run.placement_plan,
        launched_at=run.launched_at,
        current_outer_round=run.current_outer_round,
        workers=[
            TrainingWorkerResponse(
                id=str(worker.id),
                peer_id=str(worker.peer_id),
                state=worker.state.value,
                current_round=worker.current_round,
                restart_count=worker.restart_count,
                last_heartbeat_at=worker.last_heartbeat_at,
                progress=worker.progress,
                ready_at=worker.ready_at,
                stopped_at=worker.stopped_at,
                error=worker.error,
                island_id=str(worker.island_id) if worker.island_id else None,
                global_rank=worker.global_rank,
                island_rank=worker.island_rank,
                world_size=worker.world_size,
                island_world_size=worker.island_world_size,
                assigned_devices=worker.assigned_devices,
                bootstrap_checkpoint=worker.bootstrap_checkpoint,
            )
            for worker in workers
        ],
    )


async def _require_room_member(db: AsyncSession, user_id: str, room_id: str) -> None:
    if not await VpnNetworkRepository(db).user_belongs_to_network(user_id, room_id):
        raise HTTPException(status_code=403, detail="Not a member of this room")


async def _owned_run(db: AsyncSession, run_id: str, user: User) -> TrainingRun:
    run = await TrainingRunRepository(db).get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Training run not found")
    if str(run.user_id) != str(user.id):
        raise HTTPException(status_code=403, detail="Training run belongs to another user")
    return run


async def get_verified_training_peer(
    peer_id: UUID = Query(),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> Peer:
    try:
        return await get_verified_peer(str(peer_id), authorization, db)
    except HTTPException as provider_error:
        if provider_error.status_code != 401 or not authorization:
            raise
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        credential = verify_run_credential(token, settings.auth.secret_key.encode("utf-8"))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid training credentials") from exc
    result = await db.execute(
        select(TrainingWorker)
        .join(TrainingRun, TrainingRun.id == TrainingWorker.run_id)
        .where(
            TrainingWorker.id == credential.worker_id,
            TrainingWorker.peer_id == peer_id,
            TrainingWorker.peer_id == credential.peer_id,
            TrainingRun.id == credential.run_id,
            TrainingRun.vpn_network_id == credential.room_id,
            TrainingWorker.credential_id_hash == credential_id_hash(credential.credential_id),
            TrainingWorker.credential_revoked_at.is_(None),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=401, detail="Training credential scope mismatch")
    peer = await db.get(Peer, peer_id)
    if peer is None:
        raise HTTPException(status_code=404, detail="Peer not found")
    peer.__dict__["_training_credential"] = credential
    return peer


def _verify_credential_scope(
    peer: Peer,
    *,
    room_id: str,
    run_id: str,
    worker_id: str | None = None,
) -> None:
    credential = getattr(peer, "_training_credential", None)
    if credential is None:
        return
    if credential.room_id != room_id or credential.run_id != run_id:
        raise HTTPException(status_code=403, detail="Training credential run scope mismatch")
    if worker_id is not None and credential.worker_id != worker_id:
        raise HTTPException(status_code=403, detail="Training credential worker scope mismatch")


class WorkerEventKind(str, Enum):
    READY = "ready"
    HEARTBEAT = "heartbeat"
    PROGRESS = "progress"
    LOG = "log"
    ROUND_STARTED = "round_started"
    ROUND_COMPLETED = "round_completed"
    ROUND_FAILED = "round_failed"
    CHECKPOINTING = "checkpointing"
    CHECKPOINT_COMPLETED = "checkpoint_completed"
    RECONNECTED = "reconnected"
    BOOTSTRAP_COMPLETED = "bootstrap_completed"
    SHUTDOWN = "shutdown"
    ABORTED = "aborted"
    COMPLETED = "completed"


class WorkerEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    kind: WorkerEventKind
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class CredentialResponse(BaseModel):
    credential: str
    expires_at: datetime
    worker_id: str
    run_id: str
    room_id: str
    config: dict[str, Any]


class WorkerStartupResponse(BaseModel):
    worker_id: str
    run_id: str
    room_id: str
    run_state: str
    worker_state: str
    config: dict[str, Any]
    placement_plan: dict[str, Any] | None = None
    island_id: str | None = None
    global_rank: int | None = None
    island_rank: int | None = None
    world_size: int | None = None
    island_world_size: int | None = None
    assigned_devices: list[int] = Field(default_factory=list)
    bootstrap_checkpoint: dict[str, Any] | None = None
    processes: list[dict[str, Any]] = Field(default_factory=list)


class ReadinessPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: UUID
    config: TrainingRunConfig
    provider_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_provider_scope(self) -> ReadinessPreviewRequest:
        if len(self.provider_ids) != len(set(self.provider_ids)):
            raise ValueError("provider_ids must be unique")
        if self.config.phase18 is None:
            raise ValueError("readiness preview requires a Phase 18 config")
        return self


class LaunchWorkerResponse(BaseModel):
    worker_id: str
    provider_id: str
    island_id: str
    global_rank: int
    island_rank: int
    world_size: int
    island_world_size: int
    assigned_devices: list[int]


class LaunchResponse(BaseModel):
    run_id: str
    launch_key: str
    idempotent: bool
    reservation_ids: list[str]
    workers: list[LaunchWorkerResponse]


class ReservationResponse(BaseModel):
    id: str
    worker_id: str | None
    island_id: str | None
    provider_id: str
    gpu_share_id: str
    state: str
    expires_at: datetime
    released_at: datetime | None
    release_reason: str | None


class Phase18RegistrationResponse(BaseModel):
    outer_round: int
    bootstrap_required: bool


class Phase18UpdateResponse(BaseModel):
    disposition: str
    reason: str
    round_number: int
    round_state: str
    accepted_worker_ids: list[str]
    finalized: bool


async def _provider_candidates(
    db: AsyncSession,
    *,
    room_id: UUID,
    provider_ids: list[UUID],
) -> list[ProviderCandidate]:
    query = select(Peer).where(Peer.vpn_network_id == room_id)
    if provider_ids:
        query = query.where(Peer.id.in_(provider_ids))
    result = await db.execute(query.order_by(Peer.id))
    peers = list(result.scalars().all())
    if provider_ids and {str(item.id) for item in peers} != {str(item) for item in provider_ids}:
        raise HTTPException(status_code=422, detail="Provider is not in the training room")
    peer_ids = [item.id for item in peers]
    shares_by_peer: dict[str, list[GpuShare]] = {str(item.id): [] for item in peers}
    if peer_ids:
        share_result = await db.execute(
            select(GpuShare)
            .where(GpuShare.vpn_network_id == room_id, GpuShare.peer_id.in_(peer_ids))
            .order_by(GpuShare.peer_id, GpuShare.device_index, GpuShare.id)
        )
        for share in share_result.scalars().all():
            shares_by_peer[str(share.peer_id)].append(share)
    return [provider_candidate_from_models(peer, shares_by_peer[str(peer.id)]) for peer in peers]


@router.post("/readiness", response_model=PlacementPlan)
async def preview_training_readiness(
    request: ReadinessPreviewRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> PlacementPlan:
    room_id = str(request.room_id)
    await _require_room_member(db, str(user.id), room_id)
    candidates = await _provider_candidates(
        db,
        room_id=request.room_id,
        provider_ids=request.provider_ids,
    )
    return PlacementPlanner().plan(room_id=room_id, config=request.config, providers=candidates)


@router.post("", response_model=TrainingRunResponse, status_code=201)
async def create_training_run(
    request: CreateTrainingRunRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> TrainingRunResponse:
    room_id = str(request.room_id)
    provider_ids = [str(provider_id) for provider_id in request.provider_ids]
    await _require_room_member(db, str(user.id), room_id)
    candidates = await _provider_candidates(
        db,
        room_id=request.room_id,
        provider_ids=request.provider_ids,
    )
    placement: PlacementPlan | None = None
    if request.config.phase18 is not None:
        placement = PlacementPlanner().plan(
            room_id=room_id, config=request.config, providers=candidates
        )
        if placement.status == PlacementStatus.INSUFFICIENT:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Phase 18 placement is insufficient",
                    "placement": placement.model_dump(mode="json"),
                },
            )
        provider_ids = placement.selected_provider_ids
    run = await TrainingRunRepository(db).create(
        room_id=room_id,
        user_id=str(user.id),
        config=request.config.to_public_dict(),
        provider_ids=provider_ids,
        placement_plan=placement.model_dump(mode="json") if placement is not None else None,
    )
    return _response(run)


@router.get("", response_model=list[TrainingRunResponse])
async def list_training_runs(
    room_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> list[TrainingRunResponse]:
    runs = await TrainingRunRepository(db).list_for_user(
        str(user.id), room_id=str(room_id) if room_id else None, limit=limit, offset=offset
    )
    return [_response(run) for run in runs]


class TrainingRunDashboardResponse(BaseModel):
    """Phase 19 training-run dashboard aggregate for UI/export."""

    run: TrainingRunResponse
    placement: dict[str, Any] | None = None
    islands: list[dict[str, Any]] = Field(default_factory=list)
    reservations: list[dict[str, Any]] = Field(default_factory=list)
    first_failure: str | None = None
    communication: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    export: dict[str, Any] = Field(default_factory=dict)


@router.get("/{run_id}", response_model=TrainingRunResponse)
async def inspect_training_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> TrainingRunResponse:
    return _response(await _owned_run(db, str(run_id), user))


@router.get("/{run_id}/dashboard", response_model=TrainingRunDashboardResponse)
async def training_run_dashboard(
    run_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> TrainingRunDashboardResponse:
    """Aggregate job, placement, islands, workers, failure, and checkpoint hints."""
    run = await _owned_run(db, str(run_id), user)
    run_resp = _response(run)
    islands_result = await db.execute(
        select(TrainingIsland).where(TrainingIsland.run_id == run.id).order_by(TrainingIsland.id)
    )
    islands = [
        {
            "id": str(island.id),
            "classification": island.classification,
            "provider_ids": island.provider_ids,
            "gpu_share_ids": island.gpu_share_ids,
            "strategy_eligibility": island.strategy_eligibility,
            "topology": island.topology,
            "explanation": island.explanation,
        }
        for island in islands_result.scalars().all()
    ]
    reservations_result = await db.execute(
        select(TrainingGpuReservation)
        .where(TrainingGpuReservation.run_id == run.id)
        .order_by(TrainingGpuReservation.id)
    )
    reservations = [
        {
            "id": str(item.id),
            "state": item.state.value if hasattr(item.state, "value") else str(item.state),
            "peer_id": str(item.peer_id) if item.peer_id else None,
            "gpu_share_id": str(item.gpu_share_id) if item.gpu_share_id else None,
            "island_id": str(item.island_id) if item.island_id else None,
            "worker_id": str(item.worker_id) if item.worker_id else None,
            "expires_at": (
                item.expires_at.isoformat() if getattr(item, "expires_at", None) else None
            ),
        }
        for item in reservations_result.scalars().all()
    ]
    first_failure = run.error
    if first_failure is None:
        for worker in run_resp.workers:
            if worker.error:
                first_failure = worker.error
                break
    checkpoints = [
        {
            "worker_id": worker.id,
            "peer_id": worker.peer_id,
            "bootstrap_checkpoint": worker.bootstrap_checkpoint,
            "restart_count": worker.restart_count,
        }
        for worker in run_resp.workers
        if worker.bootstrap_checkpoint is not None or worker.restart_count
    ]
    communication = {
        "current_outer_round": run_resp.current_outer_round,
        "worker_rounds": {worker.id: worker.current_round for worker in run_resp.workers},
        "worker_progress": {worker.id: worker.progress for worker in run_resp.workers},
    }
    export = {
        "run_id": run_resp.id,
        "room_id": run_resp.room_id,
        "state": run_resp.state,
        "current_outer_round": run_resp.current_outer_round,
        "island_count": len(islands),
        "worker_count": len(run_resp.workers),
        "reservation_count": len(reservations),
        "first_failure": first_failure,
        "artifacts": run_resp.artifacts,
    }
    return TrainingRunDashboardResponse(
        run=run_resp,
        placement=run.placement_plan,
        islands=islands,
        reservations=reservations,
        first_failure=first_failure,
        communication=communication,
        checkpoints=checkpoints,
        export=export,
    )


@router.get("/{run_id}/placement", response_model=PlacementPlan)
async def inspect_training_placement(
    run_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> PlacementPlan:
    run = await _owned_run(db, str(run_id), user)
    if run.placement_plan is None:
        raise HTTPException(status_code=404, detail="Training run has no placement plan")
    return PlacementPlan.model_validate(run.placement_plan)


@router.get("/{run_id}/islands", response_model=list[dict[str, Any]])
async def inspect_training_islands(
    run_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> list[dict[str, Any]]:
    run = await _owned_run(db, str(run_id), user)
    result = await db.execute(
        select(TrainingIsland).where(TrainingIsland.run_id == run.id).order_by(TrainingIsland.id)
    )
    return [
        {
            "id": str(island.id),
            "classification": island.classification,
            "provider_ids": island.provider_ids,
            "gpu_share_ids": island.gpu_share_ids,
            "strategy_eligibility": island.strategy_eligibility,
            "topology": island.topology,
            "explanation": island.explanation,
        }
        for island in result.scalars().all()
    ]


@router.get("/{run_id}/reservations", response_model=list[ReservationResponse])
async def inspect_training_reservations(
    run_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> list[ReservationResponse]:
    run = await _owned_run(db, str(run_id), user)
    result = await db.execute(
        select(TrainingGpuReservation)
        .where(TrainingGpuReservation.run_id == run.id)
        .order_by(TrainingGpuReservation.created_at, TrainingGpuReservation.id)
    )
    return [
        ReservationResponse(
            id=str(item.id),
            worker_id=str(item.worker_id) if item.worker_id else None,
            island_id=str(item.island_id) if item.island_id else None,
            provider_id=str(item.peer_id),
            gpu_share_id=str(item.gpu_share_id),
            state=item.state.value,
            expires_at=item.expires_at,
            released_at=item.released_at,
            release_reason=item.release_reason,
        )
        for item in result.scalars().all()
    ]


@router.post("/{run_id}/launch", response_model=LaunchResponse)
async def launch_training_run(
    run_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> LaunchResponse:
    run = await _owned_run(db, str(run_id), user)
    launcher = DistributedTrainingLauncher(
        db, credential_secret=settings.auth.secret_key.encode("utf-8")
    )
    try:
        result = await launcher.launch(run, reservation_owner=str(user.id))
    except TrainingLaunchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result.idempotent:
        workers_by_id = {str(item.id): item for item in run.workers}
        repository = TrainingRunRepository(db)
        for item in result.workers:
            if item.credential is None:
                raise HTTPException(status_code=500, detail="worker launch credential is missing")
            processes = [asdict(process) for process in item.processes]
            network = await db.get(VpnNetwork, run.vpn_network_id)
            transport_mode = str(getattr(network, "transport_mode", None) or "dialout")
            peer_row = await db.get(Peer, item.provider_id)
            peer_worker_ids = [
                str(other.id) for other in run.workers if str(other.id) != item.worker_id
            ]
            overlay_backend = "iroh" if transport_mode == "overlay" else None
            delivered = await manager.send_provider_message(
                item.provider_id,
                {
                    "type": "training_launch",
                    "schema_version": 1,
                    "base_url": str(request.base_url).rstrip("/"),
                    "room_id": str(run.vpn_network_id),
                    "run_id": str(run.id),
                    "worker_id": item.worker_id,
                    "provider_id": item.provider_id,
                    "credential": item.credential,
                    "credential_expires_at": (
                        item.credential_expires_at.isoformat()
                        if item.credential_expires_at is not None
                        else None
                    ),
                    "config": item.config,
                    "processes": processes,
                    "rendezvous": item.rendezvous,
                    "transport_mode": transport_mode,
                    "vpn_ip": getattr(peer_row, "vpn_ip", None),
                    "data_plane_secret": issue_data_plane_secret(
                        str(run.id), settings.auth.secret_key.encode("utf-8")
                    ),
                    "room_mac_key": issue_room_mac_key(
                        str(run.vpn_network_id), settings.auth.secret_key.encode("utf-8")
                    ),
                    "peer_worker_id": peer_worker_ids[0] if peer_worker_ids else None,
                    "peer_worker_ids": peer_worker_ids,
                    "overlay_backend": overlay_backend,
                },
            )
            worker = workers_by_id[item.worker_id]
            worker.progress = {
                **worker.progress,
                "phase18_processes": processes,
                "launch_delivery": "delivered" if delivered else "awaiting_provider_wss",
            }
            await repository.record_run_event(
                run,
                kind="provider_launch_dispatched",
                payload={
                    "worker_id": item.worker_id,
                    "provider_id": item.provider_id,
                    "delivered": delivered,
                    "process_count": len(processes),
                },
            )
        await db.flush()
    return LaunchResponse(
        run_id=result.run_id,
        launch_key=result.launch_key,
        idempotent=result.idempotent,
        reservation_ids=result.reservation_ids,
        workers=[
            LaunchWorkerResponse(
                worker_id=item.worker_id,
                provider_id=item.provider_id,
                island_id=item.island_id,
                global_rank=item.global_rank,
                island_rank=item.island_rank,
                world_size=item.world_size,
                island_world_size=item.island_world_size,
                assigned_devices=item.assigned_devices,
            )
            for item in result.workers
        ],
    )


async def _transition_action(
    run_id: str, action: str, db: AsyncSession, user: User
) -> TrainingRunResponse:
    run = await _owned_run(db, run_id, user)
    repository = TrainingRunRepository(db)
    try:
        if action == "start":
            updated = await repository.start(run)
        elif run.config_version >= 3:
            updated = await DistributedTrainingLauncher(
                db, credential_secret=settings.auth.secret_key.encode("utf-8")
            ).cancel(run)
            for provider_id in run.provider_ids:
                await manager.send_provider_message(
                    provider_id,
                    {"type": "training_cancel", "run_id": str(run.id)},
                )
            Phase18CoordinatorRuntime.discard(str(run.id))
        else:
            updated = await repository.abort(run)
    except TrainingRunTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _response(updated)


async def _require_relay_worker(
    db: AsyncSession, peer: Peer, room_id: str, run_id: str
) -> TrainingWorker:
    result = await db.execute(
        select(TrainingWorker)
        .join(TrainingRun, TrainingRun.id == TrainingWorker.run_id)
        .where(
            TrainingRun.id == run_id,
            TrainingRun.vpn_network_id == room_id,
            TrainingWorker.peer_id == peer.id,
        )
    )
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=403, detail="Peer is not assigned to this training run")
    _verify_credential_scope(
        peer,
        room_id=room_id,
        run_id=run_id,
        worker_id=str(worker.id),
    )
    return worker


async def _require_target_worker(
    db: AsyncSession, peer: Peer, run_id: str, worker_id: str
) -> TrainingWorker:
    result = await db.execute(
        select(TrainingWorker).where(
            TrainingWorker.id == worker_id,
            TrainingWorker.run_id == run_id,
            TrainingWorker.peer_id == peer.id,
        )
    )
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=403, detail="Peer does not own the target worker")
    _verify_credential_scope(
        peer,
        room_id=str(peer.vpn_network_id),
        run_id=run_id,
        worker_id=str(worker.id),
    )
    return worker


async def _assigned_worker(
    db: AsyncSession, run_id: str, worker_id: str, peer: Peer
) -> tuple[TrainingRun, TrainingWorker]:
    run = await TrainingRunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Training run not found")
    if str(run.vpn_network_id) != str(peer.vpn_network_id):
        raise HTTPException(status_code=403, detail="Training room scope mismatch")
    worker = next((item for item in run.workers if str(item.id) == worker_id), None)
    if worker is None or str(worker.peer_id) != str(peer.id):
        raise HTTPException(status_code=403, detail="Peer is not assigned to this worker")
    _verify_credential_scope(
        peer,
        room_id=str(run.vpn_network_id),
        run_id=str(run.id),
        worker_id=str(worker.id),
    )
    return run, worker


async def _get_run_worker(db: AsyncSession, run_id: str, worker_id: str) -> TrainingWorker:
    result = await db.execute(
        select(TrainingWorker).where(
            TrainingWorker.id == worker_id,
            TrainingWorker.run_id == run_id,
        )
    )
    worker = result.scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=422, detail="Target worker is not assigned to this run")
    return worker


async def _require_transfer_owner(
    db: AsyncSession, peer: Peer, room_id: str, transfer_id: str
) -> None:
    try:
        transfer_room_id, run_id, worker_id = await relay_store.scope(transfer_id)
    except EnvelopeError as exc:
        raise HTTPException(status_code=404, detail="Transfer not found") from exc
    if transfer_room_id != room_id:
        raise HTTPException(status_code=403, detail="Cross-room relay denied")
    worker = await _require_relay_worker(db, peer, room_id, run_id)
    if worker_id is not None and worker_id != str(worker.id):
        raise HTTPException(status_code=403, detail="Transfer belongs to another worker")


async def _read_bounded_chunk(request: Request) -> bytes:
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > relay_store.max_chunk_bytes:
            raise HTTPException(status_code=413, detail="Chunk exceeds size limit")
        body.extend(part)
    return bytes(body)


@router.post("/{run_id}/start", response_model=TrainingRunResponse)
async def start_training_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> TrainingRunResponse:
    return await _transition_action(str(run_id), "start", db, user)


@router.post("/{run_id}/workers/{worker_id}/credential", response_model=CredentialResponse)
async def issue_training_credential(
    run_id: UUID,
    worker_id: UUID,
    peer: Peer = Depends(get_verified_training_peer),
    db: AsyncSession = Depends(get_db_session),
) -> CredentialResponse:
    run, worker = await _assigned_worker(db, str(run_id), str(worker_id), peer)
    repository = TrainingRunRepository(db)
    if run.state == TrainingRunState.CREATED:
        await repository.prepare(run)
    elif run.state in {
        TrainingRunState.COMPLETED,
        TrainingRunState.FAILED,
        TrainingRunState.CANCELLED,
        TrainingRunState.TIMED_OUT,
    }:
        raise HTTPException(status_code=409, detail="Training run is terminal")
    credential_id = str(uuid.uuid4())
    expires_at = int(time.time()) + 900
    credential = RunCredential(
        room_id=str(run.vpn_network_id),
        run_id=str(run.id),
        worker_id=str(worker.id),
        peer_id=str(peer.id),
        credential_id=credential_id,
        expires_at=expires_at,
    )
    worker.credential_id_hash = credential_id_hash(credential_id)
    worker.credential_expires_at = datetime.fromtimestamp(expires_at, UTC)
    worker.credential_revoked_at = None
    await db.flush()
    return CredentialResponse(
        credential=issue_run_credential(credential, settings.auth.secret_key.encode()),
        expires_at=datetime.fromtimestamp(expires_at, UTC),
        worker_id=str(worker.id),
        run_id=str(run.id),
        room_id=str(run.vpn_network_id),
        config=run.config,
    )


@router.get("/{run_id}/workers/{worker_id}/startup", response_model=WorkerStartupResponse)
async def inspect_worker_startup(
    run_id: UUID,
    worker_id: UUID,
    peer: Peer = Depends(get_verified_training_peer),
    db: AsyncSession = Depends(get_db_session),
) -> WorkerStartupResponse:
    run, worker = await _assigned_worker(db, str(run_id), str(worker_id), peer)
    return WorkerStartupResponse(
        worker_id=str(worker.id),
        run_id=str(run.id),
        room_id=str(run.vpn_network_id),
        run_state=run.state.value,
        worker_state=worker.state.value,
        config=run.config,
        placement_plan=run.placement_plan,
        island_id=str(worker.island_id) if worker.island_id else None,
        global_rank=worker.global_rank,
        island_rank=worker.island_rank,
        world_size=worker.world_size,
        island_world_size=worker.island_world_size,
        assigned_devices=worker.assigned_devices,
        bootstrap_checkpoint=worker.bootstrap_checkpoint,
        processes=list(worker.progress.get("phase18_processes") or []),
    )


@router.get("/{run_id}/workers/{worker_id}/peers/{peer_worker_id}/data-plane")
async def inspect_peer_data_plane(
    run_id: UUID,
    worker_id: UUID,
    peer_worker_id: UUID,
    peer: Peer = Depends(get_verified_training_peer),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return a peer worker's published data-plane endpoint (no secrets)."""

    run, _worker = await _assigned_worker(db, str(run_id), str(worker_id), peer)
    peer_worker = next((item for item in run.workers if str(item.id) == str(peer_worker_id)), None)
    if peer_worker is None:
        raise HTTPException(status_code=404, detail="peer worker not found")
    payload = peer_worker.progress.get("data_plane")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=404, detail="peer data-plane not published yet")
    return {
        "host": payload.get("host"),
        "port": payload.get("port"),
        "kind": payload.get("kind") or "lan",
    }


@router.post("/{run_id}/workers/{worker_id}/events", response_model=TrainingRunResponse)
async def submit_worker_event(
    run_id: UUID,
    worker_id: UUID,
    event: WorkerEventRequest,
    peer: Peer = Depends(get_verified_training_peer),
    db: AsyncSession = Depends(get_db_session),
) -> TrainingRunResponse:
    run, worker = await _assigned_worker(db, str(run_id), str(worker_id), peer)
    try:
        await TrainingRunRepository(db).record_worker_event(
            run,
            worker,
            event_id=str(event.event_id),
            kind=event.kind.value,
            occurred_at=event.timestamp,
            payload=event.payload,
        )
        if run.config_version >= 3 and event.kind in {
            WorkerEventKind.READY,
            WorkerEventKind.HEARTBEAT,
            WorkerEventKind.PROGRESS,
        }:
            config = TrainingRunConfig.model_validate(run.config)
            if config.phase18 is None:  # pragma: no cover - guarded by config version
                raise TrainingReservationError("Phase 18 reservation config is missing")
            await TrainingReservationRepository(db).renew(
                run_id=str(run.id),
                worker_id=str(worker.id),
                owner=str(run.user_id),
                ttl_seconds=config.phase18.reservation_ttl_seconds,
            )
        if (
            run.config_version >= 3
            and event.kind == WorkerEventKind.ROUND_FAILED
            and run.state
            not in {
                TrainingRunState.COMPLETED,
                TrainingRunState.FAILED,
                TrainingRunState.CANCELLED,
                TrainingRunState.TIMED_OUT,
            }
        ):
            await Phase18CoordinatorRuntime(db).mark_worker_failed(
                run,
                worker,
                reason=str(event.payload.get("error_type") or "worker round failed"),
            )
        if run.config_version >= 3 and run.state in {
            TrainingRunState.COMPLETED,
            TrainingRunState.FAILED,
            TrainingRunState.CANCELLED,
            TrainingRunState.TIMED_OUT,
        }:
            Phase18CoordinatorRuntime.discard(str(run.id))
    except TrainingWorkerEventValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        TrainingRunTransitionError,
        TrainingWorkerEventConflict,
        TrainingReservationError,
        Phase18RuntimeError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _response(run)


async def _read_phase18_binary(request: Request) -> bytes:
    body = bytearray()
    limit = settings.redis.training_relay_max_transfer_bytes
    async for part in request.stream():
        if len(body) + len(part) > limit:
            raise HTTPException(status_code=413, detail="Phase 18 payload exceeds size limit")
        body.extend(part)
    if not body:
        raise HTTPException(status_code=422, detail="Phase 18 binary payload is empty")
    return bytes(body)


@router.post(
    "/{run_id}/workers/{worker_id}/phase18/register",
    response_model=Phase18RegistrationResponse,
)
async def register_phase18_worker(
    run_id: UUID,
    worker_id: UUID,
    request: Request,
    peer: Peer = Depends(get_verified_training_peer),
    db: AsyncSession = Depends(get_db_session),
) -> Phase18RegistrationResponse:
    run, worker = await _assigned_worker(db, str(run_id), str(worker_id), peer)
    try:
        outer_round, bootstrap_required = await Phase18CoordinatorRuntime(db).register(
            run, worker, await _read_phase18_binary(request)
        )
    except (DiLoCoError, EnvelopeError, Phase18RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Phase18RegistrationResponse(
        outer_round=outer_round, bootstrap_required=bootstrap_required
    )


@router.post(
    "/{run_id}/workers/{worker_id}/phase18/updates",
    response_model=Phase18UpdateResponse,
)
async def submit_phase18_update(
    run_id: UUID,
    worker_id: UUID,
    request: Request,
    peer: Peer = Depends(get_verified_training_peer),
    db: AsyncSession = Depends(get_db_session),
) -> Phase18UpdateResponse:
    run, worker = await _assigned_worker(db, str(run_id), str(worker_id), peer)
    try:
        result = await Phase18CoordinatorRuntime(db).submit_update(
            run, worker, await _read_phase18_binary(request)
        )
    except (DiLoCoError, EnvelopeError, Phase18RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Phase18UpdateResponse(
        disposition=result.receipt.disposition.value,
        reason=result.receipt.reason,
        round_number=result.round_number,
        round_state=result.state.value,
        accepted_worker_ids=result.accepted_worker_ids,
        finalized=result.finalized,
    )


@router.get("/{run_id}/workers/{worker_id}/phase18/rounds/{round_number}/state")
async def receive_phase18_global_state(
    run_id: UUID,
    worker_id: UUID,
    round_number: int,
    peer: Peer = Depends(get_verified_training_peer),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    run, worker = await _assigned_worker(db, str(run_id), str(worker_id), peer)
    runtime = Phase18CoordinatorRuntime(db)
    try:
        state = await runtime.poll_round(run, round_number=round_number)
        if state.value == "paused":
            raise HTTPException(status_code=409, detail="outer round paused below min_k")
        encoded = await runtime.global_state(run, worker, round_number=round_number)
    except Phase18RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if encoded is None:
        return Response(status_code=204)
    return Response(content=encoded, media_type="application/octet-stream")


@router.post("/{run_id}/workers/{worker_id}/phase18/bootstrap")
async def bootstrap_phase18_worker(
    run_id: UUID,
    worker_id: UUID,
    peer: Peer = Depends(get_verified_training_peer),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    run, worker = await _assigned_worker(db, str(run_id), str(worker_id), peer)
    try:
        encoded = await Phase18CoordinatorRuntime(db).bootstrap(run, worker)
    except Phase18RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(content=encoded, media_type="application/octet-stream")


@router.post("/{run_id}/abort", response_model=TrainingRunResponse)
async def abort_training_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> TrainingRunResponse:
    return await _transition_action(str(run_id), "abort", db, user)


def _verify_relay_scope(peer: Peer, room_id: str) -> None:
    if str(peer.vpn_network_id) != room_id:
        raise HTTPException(status_code=403, detail="Cross-room relay denied")


@router.post("/relay/{transfer_id}/begin", status_code=204)
async def begin_relay_transfer(
    transfer_id: UUID,
    room_id: UUID = Header(alias="ZepGPU-Room-ID"),
    run_id: UUID = Header(alias="ZepGPU-Run-ID"),
    target_worker_id: UUID = Header(alias="ZepGPU-Target-Worker-ID"),
    total_chunks: int = Header(alias="ZepGPU-Total-Chunks"),
    round_number: int = Header(alias="ZepGPU-Round", ge=0),
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_training_peer),
) -> Response:
    room_id_string = str(room_id)
    run_id_string = str(run_id)
    transfer_id_string = str(transfer_id)
    _verify_relay_scope(peer, room_id_string)
    worker = await _require_relay_worker(db, peer, room_id_string, run_id_string)
    await _get_run_worker(db, run_id_string, str(target_worker_id))
    await relay_store.cleanup()
    try:
        await relay_store.begin(
            transfer_id_string,
            room_id_string,
            run_id_string,
            total_chunks,
            worker_id=str(worker.id),
            target_worker_id=str(target_worker_id),
            round_number=round_number,
        )
    except TransferConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EnvelopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204)


@router.put("/relay/{transfer_id}/chunks/{chunk_index}", status_code=204)
async def upload_relay_chunk(
    transfer_id: UUID,
    chunk_index: int,
    request: Request,
    room_id: UUID = Header(alias="ZepGPU-Room-ID"),
    content_length: int | None = Header(default=None, alias="Content-Length"),
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_training_peer),
) -> Response:
    room_id_string = str(room_id)
    transfer_id_string = str(transfer_id)
    _verify_relay_scope(peer, room_id_string)
    await _require_transfer_owner(db, peer, room_id_string, transfer_id_string)
    if content_length is not None and content_length > relay_store.max_chunk_bytes:
        raise HTTPException(status_code=413, detail="Chunk exceeds size limit")
    try:
        await relay_store.put_chunk(
            transfer_id_string, chunk_index, await _read_bounded_chunk(request)
        )
    except TransferConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/relay/{transfer_id}/complete", status_code=204)
async def complete_relay_transfer(
    transfer_id: UUID,
    room_id: UUID = Header(alias="ZepGPU-Room-ID"),
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_training_peer),
) -> Response:
    room_id_string = str(room_id)
    transfer_id_string = str(transfer_id)
    _verify_relay_scope(peer, room_id_string)
    await _require_transfer_owner(db, peer, room_id_string, transfer_id_string)
    try:
        await relay_store.complete(transfer_id_string)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/relay/{transfer_id}/payload")
async def receive_relay_transfer(
    transfer_id: UUID,
    room_id: UUID = Header(alias="ZepGPU-Room-ID"),
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_training_peer),
) -> Response:
    room_id_string = str(room_id)
    transfer_id_string = str(transfer_id)
    _verify_relay_scope(peer, room_id_string)
    try:
        transfer_room_id, run_id, _ = await relay_store.scope(transfer_id_string)
        target_worker_id = await relay_store.target(transfer_id_string)
    except EnvelopeError as exc:
        raise HTTPException(status_code=404, detail="Transfer not found") from exc
    if transfer_room_id != room_id_string or target_worker_id is None:
        raise HTTPException(status_code=403, detail="Cross-room or untargeted relay denied")
    await _require_target_worker(db, peer, run_id, target_worker_id)
    try:
        envelope = await relay_store.receive(transfer_id_string, target_worker_id)
    except EnvelopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(content=envelope.encode(), media_type="application/octet-stream")


@router.get("/relay/{transfer_id}")
async def inspect_relay_transfer(
    transfer_id: UUID,
    room_id: UUID = Header(alias="ZepGPU-Room-ID"),
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_training_peer),
) -> dict[str, Any]:
    room_id_string = str(room_id)
    transfer_id_string = str(transfer_id)
    _verify_relay_scope(peer, room_id_string)
    await _require_transfer_owner(db, peer, room_id_string, transfer_id_string)
    return await relay_store.inspect(transfer_id_string)


@router.post("/relay/{transfer_id}/ack", status_code=204)
async def acknowledge_relay_transfer(
    transfer_id: UUID,
    room_id: UUID = Header(alias="ZepGPU-Room-ID"),
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_training_peer),
) -> Response:
    room_id_string = str(room_id)
    transfer_id_string = str(transfer_id)
    _verify_relay_scope(peer, room_id_string)
    try:
        transfer_room_id, run_id, _ = await relay_store.scope(transfer_id_string)
        target_worker_id = await relay_store.target(transfer_id_string)
    except EnvelopeError as exc:
        raise HTTPException(status_code=404, detail="Transfer not found") from exc
    if transfer_room_id != room_id_string or target_worker_id is None:
        raise HTTPException(status_code=403, detail="Cross-room or untargeted relay denied")
    await _require_target_worker(db, peer, run_id, target_worker_id)
    await relay_store.abort(transfer_id_string)
    return Response(status_code=204)


@router.delete("/relay/{transfer_id}", status_code=204)
async def abort_relay_transfer(
    transfer_id: UUID,
    room_id: UUID = Header(alias="ZepGPU-Room-ID"),
    db: AsyncSession = Depends(get_db_session),
    peer: Peer = Depends(get_verified_training_peer),
) -> Response:
    room_id_string = str(room_id)
    transfer_id_string = str(transfer_id)
    _verify_relay_scope(peer, room_id_string)
    await _require_transfer_owner(db, peer, room_id_string, transfer_id_string)
    await relay_store.abort(transfer_id_string)
    return Response(status_code=204)
