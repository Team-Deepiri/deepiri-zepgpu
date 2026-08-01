from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepiri_zepgpu.api.server.dependencies import (
    get_current_user,
    get_db_session,
    get_required_user,
)
from deepiri_zepgpu.api.server.main import app
from deepiri_zepgpu.api.server.routes import training_runs as training_routes
from deepiri_zepgpu.database.models.training_run import TrainingRun
from deepiri_zepgpu.database.models.user import User, UserRole
from deepiri_zepgpu.database.models.vpn_models import Peer, PeerOnlineStatus, VpnNetwork
from deepiri_zepgpu.training.binary import BinaryEnvelope
from deepiri_zepgpu.training.relay import RedisBinaryRelayStore
from deepiri_zepgpu.training.transport import (
    HttpRelayChannel,
    PcclDirectChannel,
    RelayAuthorizationError,
    TransferManager,
)
from deepiri_zepgpu.training.worker import HttpWorkerCoordinator, PersistentTrainingWorker
from deepiri_zepgpu.vpn.crypto import encrypt_value
from deepiri_zepgpu.vpn.repositories import VpnNetworkRepository

pytestmark = pytest.mark.integration

REDIS_URL = "redis://127.0.0.1:6380/0"


@dataclass(slots=True)
class TrainingContext:
    client: AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    owner: User
    room_id: str
    peer_ids: tuple[str, str]
    peer_tokens: tuple[str, str]


@pytest_asyncio.fixture
async def training_context(integration_engine, monkeypatch: pytest.MonkeyPatch):
    session_factory = async_sessionmaker(
        integration_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with integration_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE training_worker_events, training_workers, training_runs, "
                "vpn_peers, vpn_networks, users RESTART IDENTITY CASCADE"
            )
        )

    owner = User(
        id=uuid.uuid4(),
        username=f"training-{uuid.uuid4().hex[:8]}",
        email=f"training-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="unused",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    room = VpnNetwork(id=uuid.uuid4(), name="training-room", host_id=owner.id)
    owner_peer = Peer(
        id=uuid.uuid4(),
        user_id=owner.id,
        vpn_network_id=room.id,
        wireguard_public_key=f"owner-{uuid.uuid4()}",
        vpn_ip="10.8.0.2",
        last_seen=datetime.now(UTC),
        online_status=PeerOnlineStatus.ONLINE,
    )
    peer_tokens = ("provider-one-token", "provider-two-token")
    provider_peers = tuple(
        Peer(
            id=uuid.uuid4(),
            user_id=owner.id,
            vpn_network_id=room.id,
            wireguard_public_key=f"provider-{index}-{uuid.uuid4()}",
            vpn_ip=f"10.8.0.{index + 3}",
            last_seen=datetime.now(UTC),
            online_status=PeerOnlineStatus.ONLINE,
            is_gpu_host=True,
            auth_token_encrypted=encrypt_value(peer_tokens[index]),
        )
        for index in range(2)
    )
    async with session_factory() as session:
        session.add_all([owner, room, owner_peer, *provider_peers])
        await session.commit()

    async def override_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_user() -> User:
        return owner

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_required_user] = override_user
    app.dependency_overrides[get_current_user] = override_user
    relay_store = RedisBinaryRelayStore(
        REDIS_URL,
        max_transfer_bytes=1024 * 1024,
        max_chunk_bytes=64 * 1024,
        ttl_seconds=30,
    )
    monkeypatch.setattr(training_routes, "relay_store", relay_store)
    redis_client = Redis.from_url(REDIS_URL)
    await redis_client.flushdb()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield TrainingContext(
            client=client,
            session_factory=session_factory,
            owner=owner,
            room_id=str(room.id),
            peer_ids=(str(provider_peers[0].id), str(provider_peers[1].id)),
            peer_tokens=peer_tokens,
        )

    app.dependency_overrides.clear()
    await redis_client.flushdb()
    await relay_store.close()
    await redis_client.aclose()
    async with integration_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE training_worker_events, training_workers, training_runs, "
                "vpn_peers, vpn_networks, users RESTART IDENTITY CASCADE"
            )
        )


async def create_run(context: TrainingContext) -> dict:
    response = await context.client.post(
        "/api/v1/training-runs",
        json={
            "room_id": context.room_id,
            "provider_ids": list(context.peer_ids),
            "config": {
                "run_name": "phase16-integration",
                "smoke_run": True,
                "startup_timeout_seconds": 30,
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def issue_credentials(
    context: TrainingContext, run: dict
) -> tuple[dict[str, str], dict[str, str]]:
    workers = {worker["peer_id"]: worker["id"] for worker in run["workers"]}
    credentials: dict[str, str] = {}
    for peer_id, token in zip(context.peer_ids, context.peer_tokens, strict=True):
        response = await context.client.post(
            f"/api/v1/training-runs/{run['id']}/workers/{workers[peer_id]}/credential",
            params={"peer_id": peer_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        credentials[peer_id] = response.json()["credential"]
    return workers, credentials


async def event(
    context: TrainingContext,
    *,
    run_id: str,
    worker_id: str,
    peer_id: str,
    credential: str,
    kind: str,
    payload: dict | None = None,
    event_id: str | None = None,
):
    return await context.client.post(
        f"/api/v1/training-runs/{run_id}/workers/{worker_id}/events",
        params={"peer_id": peer_id},
        headers={"Authorization": f"Bearer {credential}"},
        json={
            "event_id": event_id or str(uuid.uuid4()),
            "kind": kind,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload or {},
        },
    )


@pytest.mark.asyncio
async def test_training_room_authorization_uses_one_targeted_peer_membership_query(
    training_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = training_context
    member = User(
        id=uuid.uuid4(),
        username=f"member-{uuid.uuid4().hex[:8]}",
        email=f"member-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="unused",
        role=UserRole.USER,
        is_active=True,
        is_verified=True,
    )
    unrelated = User(
        id=uuid.uuid4(),
        username=f"unrelated-{uuid.uuid4().hex[:8]}",
        email=f"unrelated-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="unused",
        role=UserRole.USER,
        is_active=True,
        is_verified=True,
    )
    member_peer = Peer(
        id=uuid.uuid4(),
        user_id=member.id,
        vpn_network_id=uuid.UUID(context.room_id),
        wireguard_public_key=f"member-{uuid.uuid4()}",
        vpn_ip="10.8.0.10",
        last_seen=datetime.now(UTC),
        online_status=PeerOnlineStatus.ONLINE,
    )
    async with context.session_factory() as session:
        session.add_all([member, unrelated, member_peer])
        await session.commit()

    original_check = VpnNetworkRepository.user_belongs_to_network
    targeted_calls: list[tuple[str, str]] = []

    async def tracked_check(
        repository: VpnNetworkRepository, user_id: str, network_id: str
    ) -> bool:
        targeted_calls.append((user_id, network_id))
        return await original_check(repository, user_id, network_id)

    list_user_networks = AsyncMock(side_effect=AssertionError("bulk network lookup used"))
    monkeypatch.setattr(VpnNetworkRepository, "user_belongs_to_network", tracked_check)
    monkeypatch.setattr(VpnNetworkRepository, "list_user_networks", list_user_networks)

    missing_room_id = str(uuid.uuid4())
    async with context.session_factory() as session:
        await training_routes._require_room_member(session, str(context.owner.id), context.room_id)
        await training_routes._require_room_member(session, str(member.id), context.room_id)
        with pytest.raises(HTTPException) as unrelated_error:
            await training_routes._require_room_member(session, str(unrelated.id), context.room_id)
        with pytest.raises(HTTPException) as missing_error:
            await training_routes._require_room_member(
                session, str(context.owner.id), missing_room_id
            )

    assert unrelated_error.value.status_code == 403
    assert missing_error.value.status_code == 403
    assert targeted_calls == [
        (str(context.owner.id), context.room_id),
        (str(member.id), context.room_id),
        (str(unrelated.id), context.room_id),
        (str(context.owner.id), missing_room_id),
    ]
    list_user_networks.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_backed_two_worker_lifecycle_and_scope(training_context) -> None:
    context = training_context
    run = await create_run(context)
    assert run["state"] == "created"
    assert len(run["workers"]) == 2
    workers, credentials = await issue_credentials(context, run)

    another_run = await create_run(context)
    another_workers = {worker["peer_id"]: worker["id"] for worker in another_run["workers"]}
    wrong_run = await context.client.get(
        f"/api/v1/training-runs/{another_run['id']}/workers/"
        f"{another_workers[context.peer_ids[0]]}/startup",
        params={"peer_id": context.peer_ids[0]},
        headers={"Authorization": f"Bearer {credentials[context.peer_ids[0]]}"},
    )
    assert wrong_run.status_code == 403

    wrong_worker = await context.client.get(
        f"/api/v1/training-runs/{run['id']}/workers/{workers[context.peer_ids[1]]}/startup",
        params={"peer_id": context.peer_ids[0]},
        headers={"Authorization": f"Bearer {credentials[context.peer_ids[0]]}"},
    )
    assert wrong_worker.status_code == 403
    tampered = credentials[context.peer_ids[0]][:-1] + "A"
    tampered_response = await context.client.get(
        f"/api/v1/training-runs/{run['id']}/workers/{workers[context.peer_ids[0]]}/startup",
        params={"peer_id": context.peer_ids[0]},
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert tampered_response.status_code == 401

    first_ready = await event(
        context,
        run_id=run["id"],
        worker_id=workers[context.peer_ids[0]],
        peer_id=context.peer_ids[0],
        credential=credentials[context.peer_ids[0]],
        kind="ready",
    )
    assert first_ready.status_code == 200
    assert first_ready.json()["state"] == "preparing"
    duplicate_ready = await event(
        context,
        run_id=run["id"],
        worker_id=workers[context.peer_ids[0]],
        peer_id=context.peer_ids[0],
        credential=credentials[context.peer_ids[0]],
        kind="ready",
    )
    assert duplicate_ready.status_code == 200
    second_ready = await event(
        context,
        run_id=run["id"],
        worker_id=workers[context.peer_ids[1]],
        peer_id=context.peer_ids[1],
        credential=credentials[context.peer_ids[1]],
        kind="ready",
    )
    assert second_ready.status_code == 200
    assert second_ready.json()["state"] == "ready"

    started = await context.client.post(f"/api/v1/training-runs/{run['id']}/start")
    assert started.status_code == 200
    assert started.json()["state"] == "running"

    for peer_id in context.peer_ids:
        heartbeat = await event(
            context,
            run_id=run["id"],
            worker_id=workers[peer_id],
            peer_id=peer_id,
            credential=credentials[peer_id],
            kind="heartbeat",
            payload={"progress": {"loss": 0.5}},
        )
        assert heartbeat.status_code == 200
        round_started = await event(
            context,
            run_id=run["id"],
            worker_id=workers[peer_id],
            peer_id=peer_id,
            credential=credentials[peer_id],
            kind="round_started",
            payload={"round": 1},
        )
        assert round_started.status_code == 200

    for peer_id in context.peer_ids:
        completed = await event(
            context,
            run_id=run["id"],
            worker_id=workers[peer_id],
            peer_id=peer_id,
            credential=credentials[peer_id],
            kind="round_completed",
            payload={"round": 1},
        )
        assert completed.status_code == 200
    assert completed.json()["state"] == "running"

    for peer_id in context.peer_ids:
        checkpointing = await event(
            context,
            run_id=run["id"],
            worker_id=workers[peer_id],
            peer_id=peer_id,
            credential=credentials[peer_id],
            kind="checkpointing",
        )
        assert checkpointing.status_code == 200
    for peer_id in context.peer_ids:
        checkpointed = await event(
            context,
            run_id=run["id"],
            worker_id=workers[peer_id],
            peer_id=peer_id,
            credential=credentials[peer_id],
            kind="checkpoint_completed",
        )
        assert checkpointed.status_code == 200
    assert checkpointed.json()["state"] == "running"

    reconnected = await event(
        context,
        run_id=run["id"],
        worker_id=workers[context.peer_ids[0]],
        peer_id=context.peer_ids[0],
        credential=credentials[context.peer_ids[0]],
        kind="reconnected",
    )
    assert reconnected.status_code == 200
    worker = next(
        item for item in reconnected.json()["workers"] if item["peer_id"] == context.peer_ids[0]
    )
    assert worker["restart_count"] == 1
    assert worker["current_round"] == 1
    assert worker["last_heartbeat_at"] is not None
    assert worker["progress"]["loss"] == 0.5

    aborted = await context.client.post(f"/api/v1/training-runs/{run['id']}/abort")
    assert aborted.status_code == 200
    assert aborted.json()["state"] == "cancelled"
    assert {worker["state"] for worker in aborted.json()["workers"]} == {"cancelled"}
    revoked = await context.client.get(
        f"/api/v1/training-runs/{run['id']}/workers/{workers[context.peer_ids[0]]}/startup",
        params={"peer_id": context.peer_ids[0]},
        headers={"Authorization": f"Bearer {credentials[context.peer_ids[0]]}"},
    )
    assert revoked.status_code == 401


@pytest.mark.asyncio
async def test_startup_timeout_and_first_failure_are_persisted(training_context) -> None:
    context = training_context
    run = await create_run(context)
    workers, credentials = await issue_credentials(context, run)
    async with context.session_factory() as session:
        record = await session.get(TrainingRun, uuid.UUID(run["id"]))
        assert record is not None
        record.startup_deadline_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    inspected = await context.client.get(f"/api/v1/training-runs/{run['id']}")
    assert inspected.status_code == 200
    assert inspected.json()["state"] == "timed_out"
    assert inspected.json()["error"] == "training worker readiness deadline expired"
    terminal = await event(
        context,
        run_id=run["id"],
        worker_id=workers[context.peer_ids[0]],
        peer_id=context.peer_ids[0],
        credential=credentials[context.peer_ids[0]],
        kind="ready",
    )
    assert terminal.status_code == 401


@pytest.mark.asyncio
async def test_first_worker_failure_cancels_peers_and_preserves_cause(training_context) -> None:
    context = training_context
    run = await create_run(context)
    workers, credentials = await issue_credentials(context, run)
    for peer_id in context.peer_ids:
        response = await event(
            context,
            run_id=run["id"],
            worker_id=workers[peer_id],
            peer_id=peer_id,
            credential=credentials[peer_id],
            kind="ready",
        )
        assert response.status_code == 200
    assert (
        await context.client.post(f"/api/v1/training-runs/{run['id']}/start")
    ).status_code == 200
    failure = await event(
        context,
        run_id=run["id"],
        worker_id=workers[context.peer_ids[0]],
        peer_id=context.peer_ids[0],
        credential=credentials[context.peer_ids[0]],
        kind="round_failed",
        payload={"round": 1, "error_type": "FirstFailure"},
    )
    assert failure.status_code == 200
    failed = failure.json()
    assert failed["state"] == "failed"
    assert failed["error"] == "FirstFailure"
    assert {worker["state"] for worker in failed["workers"]} == {
        "failed",
        "cancelled",
    }
    conflicting = await event(
        context,
        run_id=run["id"],
        worker_id=workers[context.peer_ids[1]],
        peer_id=context.peer_ids[1],
        credential=credentials[context.peer_ids[1]],
        kind="round_failed",
        payload={"round": 1, "error_type": "SecondFailure"},
    )
    assert conflicting.status_code == 401
    inspected = await context.client.get(f"/api/v1/training-runs/{run['id']}")
    assert inspected.json()["error"] == "FirstFailure"


@pytest.mark.asyncio
async def test_worker_event_validation_and_conflict_statuses(training_context) -> None:
    context = training_context
    run = await create_run(context)
    workers, credentials = await issue_credentials(context, run)
    for peer_id in context.peer_ids:
        assert (
            await event(
                context,
                run_id=run["id"],
                worker_id=workers[peer_id],
                peer_id=peer_id,
                credential=credentials[peer_id],
                kind="ready",
            )
        ).status_code == 200
    assert (
        await context.client.post(f"/api/v1/training-runs/{run['id']}/start")
    ).status_code == 200

    source_peer = context.peer_ids[0]
    common = {
        "run_id": run["id"],
        "worker_id": workers[source_peer],
        "peer_id": source_peer,
        "credential": credentials[source_peer],
        "kind": "round_started",
    }
    for malformed_payload in ({}, {"round": 0}, {"round": -1}, {"round": True}):
        response = await event(context, payload=malformed_payload, **common)
        assert response.status_code == 422, response.text

    assert (await event(context, payload={"round": 1}, **common)).status_code == 200
    conflict = await event(context, payload={"round": 1}, **common)
    assert conflict.status_code == 409
    assert "monotonically" in conflict.json()["detail"]


@pytest.mark.asyncio
async def test_http_relay_fallback_target_download_and_redis_sharing(training_context) -> None:
    context = training_context
    run = await create_run(context)
    workers, credentials = await issue_credentials(context, run)
    source_peer, target_peer = context.peer_ids
    envelope = BinaryEnvelope(
        room_id=context.room_id,
        run_id=run["id"],
        worker_id=workers[source_peer],
        transfer_id=str(uuid.uuid4()),
        round=3,
        payload_type="gradient",
        shape=(4,),
        dtype="float32",
        compression="none",
        payload=b"phase16-binary-gradient",
    )
    source_relay = HttpRelayChannel(
        base_url="http://test",
        peer_id=source_peer,
        credential=credentials[source_peer],
        chunk_size=11,
        client=context.client,
    )
    manager = TransferManager(direct=PcclDirectChannel(), relay=source_relay, max_retries=1)
    delivered, metric = await manager.send(envelope, workers[target_peer])
    assert delivered is None
    assert metric.path == "relay"
    assert metric.bytes == len(envelope.encode())
    assert metric.duration_seconds >= 0

    with pytest.raises(RelayAuthorizationError):
        await source_relay.download(
            envelope.transfer_id,
            room_id=context.room_id,
            run_id=run["id"],
            source_worker_id=workers[source_peer],
            round_number=3,
        )
    target_relay = HttpRelayChannel(
        base_url="http://test",
        peer_id=target_peer,
        credential=credentials[target_peer],
        client=context.client,
    )
    assert (
        await target_relay.download(
            envelope.transfer_id,
            room_id=context.room_id,
            run_id=run["id"],
            source_worker_id=workers[source_peer],
            round_number=3,
        )
        == envelope
    )
    with pytest.raises(ValueError, match="unknown transfer"):
        await training_routes.relay_store.scope(envelope.transfer_id)


@pytest.mark.asyncio
async def test_two_persistent_workers_use_coordinator_across_rounds(training_context) -> None:
    context = training_context
    run = await create_run(context)
    workers, credentials = await issue_credentials(context, run)
    persistent_workers = []
    for peer_id, provider_token in zip(context.peer_ids, context.peer_tokens, strict=True):
        coordinator = HttpWorkerCoordinator(
            base_url="http://test",
            run_id=run["id"],
            peer_id=peer_id,
            client=context.client,
        )
        worker = PersistentTrainingWorker(
            worker_id=workers[peer_id],
            provider_token=provider_token,
            run_credential=credentials[peer_id],
            coordinator=coordinator,
        )
        await worker.start()
        persistent_workers.append(worker)
    inspected = await context.client.get(f"/api/v1/training-runs/{run['id']}")
    assert inspected.json()["state"] == "ready"
    started = await context.client.post(f"/api/v1/training-runs/{run['id']}/start")
    assert started.json()["state"] == "running"

    async def complete(round_number: int) -> dict[str, int]:
        return {"round": round_number}

    for round_number in (1, 2):
        for worker in persistent_workers:
            assert await worker.run_round(
                round_number,
                lambda round_number=round_number: complete(round_number),
            ) == {"round": round_number}
            await worker.progress({"round": round_number, "loss": 1 / round_number})
        state = await context.client.get(f"/api/v1/training-runs/{run['id']}")
        assert state.json()["state"] == "running"
        assert {item["current_round"] for item in state.json()["workers"]} == {round_number}

    for worker in persistent_workers:
        await worker.shutdown()
    aborted = await context.client.post(f"/api/v1/training-runs/{run['id']}/abort")
    assert aborted.json()["state"] == "cancelled"


@pytest.mark.asyncio
async def test_redis_backend_idempotency_corruption_limits_and_ttl() -> None:
    redis_client = Redis.from_url(REDIS_URL)
    await redis_client.flushdb()
    source = RedisBinaryRelayStore(
        REDIS_URL, max_transfer_bytes=4096, max_chunk_bytes=2048, ttl_seconds=1
    )
    second_process = RedisBinaryRelayStore(
        REDIS_URL, max_transfer_bytes=4096, max_chunk_bytes=2048, ttl_seconds=1
    )
    room_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    worker_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    envelope = BinaryEnvelope(
        room_id=room_id,
        run_id=run_id,
        worker_id=worker_id,
        transfer_id=str(uuid.uuid4()),
        round=7,
        payload_type="adapter_delta",
        shape=(3,),
        dtype="float16",
        compression="none",
        payload=b"abc",
    )
    encoded = envelope.encode()
    await source.begin(
        envelope.transfer_id,
        room_id,
        run_id,
        1,
        worker_id=worker_id,
        target_worker_id=target_id,
        round_number=7,
    )
    await source.put_chunk(envelope.transfer_id, 0, encoded)
    await source.put_chunk(envelope.transfer_id, 0, encoded)
    with pytest.raises(ValueError, match="conflicting duplicate chunk"):
        await source.put_chunk(envelope.transfer_id, 0, b"different")
    assert await second_process.complete(envelope.transfer_id) == envelope
    assert await second_process.complete(envelope.transfer_id) == envelope
    assert await second_process.receive(envelope.transfer_id, target_id) == envelope
    with pytest.raises(ValueError, match="another target worker"):
        await second_process.receive(envelope.transfer_id, str(uuid.uuid4()))
    with pytest.raises(ValueError, match="already completed"):
        await source.begin(
            envelope.transfer_id,
            room_id,
            run_id,
            1,
            worker_id=worker_id,
            target_worker_id=target_id,
            round_number=7,
        )
    with pytest.raises(ValueError, match="not accepting chunks"):
        await source.put_chunk(envelope.transfer_id, 0, encoded)

    corrupted = BinaryEnvelope(
        room_id=room_id,
        run_id=run_id,
        worker_id=worker_id,
        transfer_id=str(uuid.uuid4()),
        round=8,
        payload_type="gradient",
        shape=(1,),
        dtype="float32",
        compression="none",
        payload=b"checksum",
    )
    corrupted_bytes = bytearray(corrupted.encode())
    corrupted_bytes[-1] ^= 1
    await source.begin(
        corrupted.transfer_id,
        room_id,
        run_id,
        1,
        worker_id=worker_id,
        target_worker_id=target_id,
        round_number=8,
    )
    await source.put_chunk(corrupted.transfer_id, 0, bytes(corrupted_bytes))
    with pytest.raises(ValueError, match="checksum"):
        await second_process.complete(corrupted.transfer_id)

    for scope_name, begin_overrides in (
        ("room", {"room_id": str(uuid.uuid4())}),
        ("run", {"run_id": str(uuid.uuid4())}),
        ("worker", {"worker_id": str(uuid.uuid4())}),
        ("round", {"round_number": 10}),
    ):
        scoped = BinaryEnvelope(
            room_id=room_id,
            run_id=run_id,
            worker_id=worker_id,
            transfer_id=str(uuid.uuid4()),
            round=9,
            payload_type="gradient",
            shape=(1,),
            dtype="float32",
            compression="none",
            payload=b"scope",
        )
        begin_scope = {
            "room_id": room_id,
            "run_id": run_id,
            "worker_id": worker_id,
            "round_number": 9,
            **begin_overrides,
        }
        await source.begin(
            scoped.transfer_id,
            begin_scope["room_id"],
            begin_scope["run_id"],
            1,
            worker_id=begin_scope["worker_id"],
            target_worker_id=target_id,
            round_number=begin_scope["round_number"],
        )
        await source.put_chunk(scoped.transfer_id, 0, scoped.encode())
        with pytest.raises(ValueError, match=scope_name):
            await source.complete(scoped.transfer_id)
        assert await source.abort(scoped.transfer_id)

    abandoned = str(uuid.uuid4())
    await source.begin(abandoned, room_id, run_id, 1, round_number=1)
    await asyncio.sleep(1.1)
    with pytest.raises(ValueError, match="unknown transfer"):
        await second_process.scope(abandoned)
    with pytest.raises(ValueError, match="unknown transfer"):
        await second_process.scope(envelope.transfer_id)
    assert await source.cleanup() == 0
    await redis_client.flushdb()
    await source.close()
    await second_process.close()
    await redis_client.aclose()


def test_relay_routes_use_native_async_io() -> None:
    assert not hasattr(training_routes, "run_in_threadpool")
