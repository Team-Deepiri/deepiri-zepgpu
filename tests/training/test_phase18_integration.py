"""Phase 18 control-plane integration against migrated PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepiri_zepgpu.api.server.dependencies import get_db_session, get_required_user
from deepiri_zepgpu.api.server.main import app
from deepiri_zepgpu.database.models.training_run import (
    TrainingGpuReservation,
    TrainingOuterRound,
    TrainingReservationState,
    TrainingRun,
)
from deepiri_zepgpu.database.models.user import User, UserRole
from deepiri_zepgpu.database.models.vpn_models import (
    GpuShare,
    GpuShareState,
    Peer,
    PeerOnlineStatus,
    VpnNetwork,
)
from deepiri_zepgpu.training.config import TrainingRunConfig
from deepiri_zepgpu.training.diloco import DiLoCoWorkerRuntime
from deepiri_zepgpu.training.phase18_runtime import Phase18CoordinatorRuntime

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def phase18_client(integration_engine):
    factory = async_sessionmaker(integration_engine, expire_on_commit=False, class_=AsyncSession)
    async with integration_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE training_run_events, training_outer_rounds, "
                "training_gpu_reservations, training_worker_events, training_workers, "
                "training_islands, training_runs, gpu_shares, vpn_peers, vpn_networks, "
                "users RESTART IDENTITY CASCADE"
            )
        )
    now = datetime.now(UTC)
    owner = User(
        id=uuid.uuid4(),
        username=f"p18-api-{uuid.uuid4().hex[:8]}",
        email=f"p18-api-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="unused",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    room = VpnNetwork(id=uuid.uuid4(), name="phase18-api", host_id=owner.id)
    owner_peer = Peer(
        id=uuid.uuid4(),
        user_id=owner.id,
        vpn_network_id=room.id,
        wireguard_public_key=f"owner-{uuid.uuid4()}",
        vpn_ip="10.8.0.2",
        last_seen=now,
        online_status=PeerOnlineStatus.ONLINE,
    )
    providers = [
        Peer(
            id=uuid.uuid4(),
            user_id=owner.id,
            vpn_network_id=room.id,
            wireguard_public_key=f"provider-{uuid.uuid4()}",
            vpn_ip=f"10.8.0.{index + 3}",
            last_seen=now,
            online_status=PeerOnlineStatus.ONLINE,
            is_gpu_host=True,
            health_state="healthy",
            capabilities_json={
                "runtime": {
                    "cuda_version": "13.0",
                    "pytorch_version": "2.13.0",
                    "nccl_version": "2.27",
                },
                "topology": {},
            },
            capabilities_reported_at=now,
            path_type="direct",
            path_class="wan",
            coordinator_rtt_ms=50,
            path_measurement_kind="measured",
        )
        for index in range(3)
    ]
    shares = [
        GpuShare(
            id=uuid.uuid4(),
            peer_id=provider.id,
            vpn_network_id=room.id,
            device_index=0,
            total_memory_mb=24_576,
            available_memory_mb=24_576,
            state=GpuShareState.IDLE,
            is_active=True,
        )
        for provider in providers
    ]
    async with factory() as session:
        session.add_all([owner, room, owner_peer, *providers, *shares])
        await session.commit()

    async def override_db():
        async with factory() as session:
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, str(room.id), [str(item.id) for item in providers], factory
    app.dependency_overrides.clear()


def phase18_payload(room_id: str, provider_ids: list[str]) -> dict:
    return {
        "room_id": room_id,
        "provider_ids": provider_ids,
        "config": {
            "run_name": "phase18-api",
            "phase18": {
                "requested_node_count": 2,
                "gpus_per_node": 1,
                "total_gpus": 2,
                "minimum_vram_per_gpu_mb": 1024,
                "diloco_h": 4,
                "min_k": 1,
                "sync_deadline_seconds": 10,
                "checkpoint_interval_rounds": 1,
                "maximum_runtime_seconds": 600,
            },
        },
    }


@pytest.mark.asyncio
async def test_readiness_create_launch_inspect_and_cancel(phase18_client) -> None:
    client, room_id, provider_ids, _factory = phase18_client
    provider_ids = provider_ids[:2]
    payload = phase18_payload(room_id, provider_ids)
    preview = await client.post("/api/v1/training-runs/readiness", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "capable"

    created = await client.post("/api/v1/training-runs", json=payload)
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["config_version"] == 3
    assert run["placement_plan"]["selected_provider_ids"] == sorted(provider_ids)

    launched = await client.post(f"/api/v1/training-runs/{run['id']}/launch")
    assert launched.status_code == 200, launched.text
    assert launched.json()["idempotent"] is False
    assert len(launched.json()["reservation_ids"]) == 2
    repeated = await client.post(f"/api/v1/training-runs/{run['id']}/launch")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["idempotent"] is True

    placement = await client.get(f"/api/v1/training-runs/{run['id']}/placement")
    islands = await client.get(f"/api/v1/training-runs/{run['id']}/islands")
    reservations = await client.get(f"/api/v1/training-runs/{run['id']}/reservations")
    assert placement.status_code == 200
    assert len(islands.json()) == 2
    assert {item["state"] for item in reservations.json()} == {"active"}
    assert all("reservation_owner" not in item for item in reservations.json())

    cancelled = await client.post(f"/api/v1/training-runs/{run['id']}/abort")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled"
    reservations = await client.get(f"/api/v1/training-runs/{run['id']}/reservations")
    assert {item["state"] for item in reservations.json()} == {"released"}


@pytest.mark.asyncio
async def test_creation_rejects_partial_but_insufficient_placement(phase18_client) -> None:
    client, room_id, provider_ids, _factory = phase18_client
    payload = phase18_payload(room_id, provider_ids[:2])
    payload["config"]["phase18"].update({"requested_node_count": 3, "total_gpus": 3, "min_k": 2})
    response = await client.post("/api/v1/training-runs", json=payload)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["message"] == "Phase 18 placement is insufficient"
    assert detail["placement"]["status"] == "insufficient"
    assert len(detail["placement"]["selected_gpus"]) == 2
    assert detail["placement"]["actionable_reasons"]


@pytest.mark.asyncio
async def test_worker_heartbeat_renews_its_reservation_lease(phase18_client, monkeypatch) -> None:
    client, room_id, provider_ids, _factory = phase18_client
    dispatched: dict[str, dict] = {}

    async def capture_launch(peer_id: str, message: dict) -> bool:
        dispatched[peer_id] = message
        return True

    from deepiri_zepgpu.api.server.websocket_manager import manager

    monkeypatch.setattr(manager, "send_provider_message", capture_launch)
    payload = phase18_payload(room_id, provider_ids[:2])
    created = await client.post("/api/v1/training-runs", json=payload)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    launched = await client.post(f"/api/v1/training-runs/{run_id}/launch")
    assert launched.status_code == 200, launched.text
    before = await client.get(f"/api/v1/training-runs/{run_id}/reservations")
    expiry_by_provider = {
        item["provider_id"]: datetime.fromisoformat(item["expires_at"]) for item in before.json()
    }
    item = next(iter(dispatched.values()))
    await _worker_event(
        client,
        run_id=run_id,
        worker_id=item["worker_id"],
        peer_id=item["provider_id"],
        credential=item["credential"],
        kind="heartbeat",
        payload={"progress": {"completed_local_steps": 1}},
    )
    after = await client.get(f"/api/v1/training-runs/{run_id}/reservations")
    renewed = next(
        reservation
        for reservation in after.json()
        if reservation["provider_id"] == item["provider_id"]
    )
    assert datetime.fromisoformat(renewed["expires_at"]) > expiry_by_provider[item["provider_id"]]


def _worker_headers(credential: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {credential}"}


async def _worker_event(
    client: AsyncClient,
    *,
    run_id: str,
    worker_id: str,
    peer_id: str,
    credential: str,
    kind: str,
    payload: dict | None = None,
) -> dict:
    response = await client.post(
        f"/api/v1/training-runs/{run_id}/workers/{worker_id}/events",
        params={"peer_id": peer_id},
        headers=_worker_headers(credential),
        json={
            "event_id": str(uuid.uuid4()),
            "kind": kind,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload or {},
        },
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


@pytest.mark.asyncio
async def test_phase18_three_worker_runtime_failure_rejoin_and_cleanup(
    phase18_client, monkeypatch
) -> None:
    """CPU e2e: API→placement→lease→launch→runtime→checkpoint→cleanup."""

    client, room_id, provider_ids, factory = phase18_client
    dispatched: dict[str, dict] = {}

    async def capture_launch(peer_id: str, message: dict) -> bool:
        dispatched[peer_id] = message
        return True

    from deepiri_zepgpu.api.server.websocket_manager import manager

    monkeypatch.setattr(manager, "send_provider_message", capture_launch)
    payload = {
        "room_id": room_id,
        "provider_ids": provider_ids,
        "config": {
            "run_name": "phase18-runtime-e2e",
            "device": "cpu",
            "precision": "fp32",
            "distributed": {"max_rounds": 2},
            "phase18": {
                "requested_node_count": 3,
                "gpus_per_node": 1,
                "total_gpus": 3,
                "minimum_vram_per_gpu_mb": 1024,
                "diloco_h": 3,
                "min_k": 2,
                "sync_deadline_seconds": 10,
                "checkpoint_interval_rounds": 1,
                "maximum_runtime_seconds": 600,
                "runtime_requirements": {"requires_cuda": False},
            },
        },
    }
    preview = await client.post("/api/v1/training-runs/readiness", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "capable"
    created = await client.post("/api/v1/training-runs", json=payload)
    assert created.status_code == 201, created.text
    run = created.json()
    run_id = run["id"]
    launched = await client.post(f"/api/v1/training-runs/{run_id}/launch")
    assert launched.status_code == 200, launched.text
    assert len(launched.json()["reservation_ids"]) == 3
    assert set(dispatched) == set(provider_ids)
    assert all(item["type"] == "training_launch" for item in dispatched.values())
    assert all(len(item["processes"]) == 1 for item in dispatched.values())

    launch_by_worker = {message["worker_id"]: message for message in dispatched.values()}
    workers = sorted(launch_by_worker.values(), key=lambda item: item["worker_id"])
    for item in workers:
        await _worker_event(
            client,
            run_id=run_id,
            worker_id=item["worker_id"],
            peer_id=item["provider_id"],
            credential=item["credential"],
            kind="ready",
        )
    started = await client.post(f"/api/v1/training-runs/{run_id}/start")
    assert started.status_code == 200, started.text
    assert started.json()["state"] == "running"

    config = TrainingRunConfig.model_validate(payload["config"])
    initial = {"adapter": np.zeros((8,), dtype=np.float32)}
    local_runtimes: dict[str, DiLoCoWorkerRuntime] = {}
    for item in workers:
        local = DiLoCoWorkerRuntime(
            room_id=room_id,
            run_id=run_id,
            worker_id=item["worker_id"],
            config=config,
            initial_state=initial,
        )
        local_runtimes[item["worker_id"]] = local
        registered = await client.post(
            f"/api/v1/training-runs/{run_id}/workers/{item['worker_id']}" "/phase18/register",
            params={"peer_id": item["provider_id"]},
            headers=_worker_headers(item["credential"]),
            content=local.initial_state_envelope(),
        )
        assert registered.status_code == 200, registered.text
        assert registered.json()["bootstrap_required"] is False

    async def submit_update(item: dict, round_number: int, value: float):
        local = local_runtimes[item["worker_id"]]
        encoded = local.encode_update(
            round_number=round_number,
            delta={"adapter": np.full((8,), value, dtype=np.float32)},
            completed_local_steps=round_number * 3,
        )
        response = await client.post(
            f"/api/v1/training-runs/{run_id}/workers/{item['worker_id']}" "/phase18/updates",
            params={"peer_id": item["provider_id"]},
            headers=_worker_headers(item["credential"]),
            content=encoded,
        )
        assert response.status_code == 200, response.text
        return response, encoded

    first, duplicate_payload = await submit_update(workers[0], 1, 1.0)
    assert first.json()["finalized"] is False
    duplicate = await client.post(
        f"/api/v1/training-runs/{run_id}/workers/{workers[0]['worker_id']}" "/phase18/updates",
        params={"peer_id": workers[0]["provider_id"]},
        headers=_worker_headers(workers[0]["credential"]),
        content=duplicate_payload,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["disposition"] == "duplicate"

    await _worker_event(
        client,
        run_id=run_id,
        worker_id=workers[2]["worker_id"],
        peer_id=workers[2]["provider_id"],
        credential=workers[2]["credential"],
        kind="round_failed",
        payload={"round": 1, "error_type": "SimulatedDisconnect"},
    )
    second, _ = await submit_update(workers[1], 1, 3.0)
    assert second.json()["finalized"] is True
    assert second.json()["accepted_worker_ids"] == sorted(
        [workers[0]["worker_id"], workers[1]["worker_id"]]
    )

    for item in workers[:2]:
        state = await client.get(
            f"/api/v1/training-runs/{run_id}/workers/{item['worker_id']}" "/phase18/rounds/1/state",
            params={"peer_id": item["provider_id"]},
            headers=_worker_headers(item["credential"]),
        )
        assert state.status_code == 200, state.text
        local_runtimes[item["worker_id"]].apply_global_state(state.content)

    await _worker_event(
        client,
        run_id=run_id,
        worker_id=workers[2]["worker_id"],
        peer_id=workers[2]["provider_id"],
        credential=workers[2]["credential"],
        kind="reconnected",
        payload={"round": 1},
    )
    re_registered = await client.post(
        f"/api/v1/training-runs/{run_id}/workers/{workers[2]['worker_id']}" "/phase18/register",
        params={"peer_id": workers[2]["provider_id"]},
        headers=_worker_headers(workers[2]["credential"]),
        content=local_runtimes[workers[2]["worker_id"]].initial_state_envelope(),
    )
    assert re_registered.status_code == 200
    assert re_registered.json()["bootstrap_required"] is True
    bootstrapped = await client.post(
        f"/api/v1/training-runs/{run_id}/workers/{workers[2]['worker_id']}" "/phase18/bootstrap",
        params={"peer_id": workers[2]["provider_id"]},
        headers=_worker_headers(workers[2]["credential"]),
    )
    assert bootstrapped.status_code == 200, bootstrapped.text
    local_runtimes[workers[2]["worker_id"]].apply_global_state(bootstrapped.content)

    stale, _ = await submit_update(workers[2], 1, 99.0)
    assert stale.json()["disposition"] == "late"

    round2_results = []
    for index, item in enumerate(workers):
        result, _ = await submit_update(item, 2, float(index + 2))
        round2_results.append(result.json())
    assert round2_results[-1]["finalized"] is True
    assert len(round2_results[-1]["accepted_worker_ids"]) == 3

    for item in workers:
        completed = await _worker_event(
            client,
            run_id=run_id,
            worker_id=item["worker_id"],
            peer_id=item["provider_id"],
            credential=item["credential"],
            kind="completed",
            payload={"round": 2},
        )
    assert completed["state"] == "completed"

    async with factory() as session:
        persisted_run = await session.get(TrainingRun, uuid.UUID(run_id))
        assert persisted_run is not None
        assert persisted_run.current_outer_round == 2
        assert persisted_run.artifacts[-1]["outer_round"] == 2
        outer_rounds = list(
            (
                await session.execute(
                    select(TrainingOuterRound)
                    .where(TrainingOuterRound.run_id == run_id)
                    .order_by(TrainingOuterRound.round_number)
                )
            )
            .scalars()
            .all()
        )
        assert [item.round_number for item in outer_rounds] == [1, 2]
        assert [len(item.accepted_worker_ids) for item in outer_rounds] == [2, 3]
        assert len(outer_rounds[0].rejected_updates) == 2  # duplicate + late
        assert outer_rounds[0].metrics["policy"] == "all_active_or_deadline"
        reservations = list((await session.execute(select(TrainingGpuReservation))).scalars().all())
        assert {item.state for item in reservations} == {TrainingReservationState.RELEASED}
        assert len(reservations) == 3
    Phase18CoordinatorRuntime.discard(run_id)
