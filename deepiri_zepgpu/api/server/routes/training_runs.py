"""Training run control plane and binary coordinator relay endpoints."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from deepiri_zepgpu.api.server.dependencies import get_db_session, get_required_user
from deepiri_zepgpu.api.server.routes.node_tasks import get_verified_peer
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.models import User
from deepiri_zepgpu.database.models.training_run import (
    TrainingRun,
    TrainingRunState,
    TrainingWorker,
)
from deepiri_zepgpu.database.models.vpn_models import Peer
from deepiri_zepgpu.database.repositories.training_run_repository import (
    TrainingRunRepository,
    TrainingRunTransitionError,
    TrainingWorkerEventConflict,
)
from deepiri_zepgpu.training.binary import EnvelopeError
from deepiri_zepgpu.training.config import TrainingRunConfig
from deepiri_zepgpu.training.credentials import (
    RunCredential,
    credential_id_hash,
    issue_run_credential,
    verify_run_credential,
)
from deepiri_zepgpu.training.relay import RedisBinaryRelayStore, TransferConflictError
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
            )
            for worker in workers
        ],
    )


async def _require_room_member(db: AsyncSession, user_id: str, room_id: str) -> None:
    networks = await VpnNetworkRepository(db).list_user_networks(user_id)
    if not any(str(network.id) == room_id for network in networks):
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


@router.post("", response_model=TrainingRunResponse, status_code=201)
async def create_training_run(
    request: CreateTrainingRunRequest,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> TrainingRunResponse:
    room_id = str(request.room_id)
    provider_ids = [str(provider_id) for provider_id in request.provider_ids]
    await _require_room_member(db, str(user.id), room_id)
    if request.provider_ids:
        providers = await db.execute(
            select(Peer.id).where(
                Peer.vpn_network_id == request.room_id, Peer.id.in_(request.provider_ids)
            )
        )
        found = {str(value) for value in providers.scalars().all()}
        if found != set(provider_ids):
            raise HTTPException(status_code=422, detail="Provider is not in the training room")
    run = await TrainingRunRepository(db).create(
        room_id=room_id,
        user_id=str(user.id),
        config=request.config.model_dump(mode="json"),
        provider_ids=provider_ids,
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


@router.get("/{run_id}", response_model=TrainingRunResponse)
async def inspect_training_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_required_user),
) -> TrainingRunResponse:
    return _response(await _owned_run(db, str(run_id), user))


async def _transition_action(
    run_id: str, action: str, db: AsyncSession, user: User
) -> TrainingRunResponse:
    run = await _owned_run(db, run_id, user)
    repository = TrainingRunRepository(db)
    try:
        updated = await (repository.start(run) if action == "start" else repository.abort(run))
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


async def _relay_call(method: str, *args: Any, **kwargs: Any) -> Any:
    return await run_in_threadpool(getattr(relay_store, method), *args, **kwargs)


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
        transfer_room_id, run_id, worker_id = await _relay_call("scope", transfer_id)
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
    )


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
    except (TrainingRunTransitionError, TrainingWorkerEventConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _response(run)


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
    await _relay_call("cleanup")
    try:
        await _relay_call(
            "begin",
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
        await _relay_call(
            "put_chunk", transfer_id_string, chunk_index, await _read_bounded_chunk(request)
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
        await _relay_call("complete", transfer_id_string)
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
        transfer_room_id, run_id, _ = await _relay_call("scope", transfer_id_string)
        target_worker_id = await _relay_call("target", transfer_id_string)
    except EnvelopeError as exc:
        raise HTTPException(status_code=404, detail="Transfer not found") from exc
    if transfer_room_id != room_id_string or target_worker_id is None:
        raise HTTPException(status_code=403, detail="Cross-room or untargeted relay denied")
    await _require_target_worker(db, peer, run_id, target_worker_id)
    try:
        envelope = await _relay_call("receive", transfer_id_string, target_worker_id)
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
    return await _relay_call("inspect", transfer_id_string)


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
        transfer_room_id, run_id, _ = await _relay_call("scope", transfer_id_string)
        target_worker_id = await _relay_call("target", transfer_id_string)
    except EnvelopeError as exc:
        raise HTTPException(status_code=404, detail="Transfer not found") from exc
    if transfer_room_id != room_id_string or target_worker_id is None:
        raise HTTPException(status_code=403, detail="Cross-room or untargeted relay denied")
    await _require_target_worker(db, peer, run_id, target_worker_id)
    await _relay_call("abort", transfer_id_string)
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
    await _relay_call("abort", transfer_id_string)
    return Response(status_code=204)
