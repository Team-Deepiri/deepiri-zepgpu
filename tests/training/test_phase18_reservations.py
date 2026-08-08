"""PostgreSQL reservation atomicity and launcher lifecycle tests."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepiri_zepgpu.database.models.training_run import (
    TrainingGpuReservation,
    TrainingOuterRound,
    TrainingOuterRoundState,
    TrainingReservationState,
    TrainingRun,
    TrainingRunState,
    TrainingWorkerState,
)
from deepiri_zepgpu.database.models.user import User, UserRole
from deepiri_zepgpu.database.models.vpn_models import (
    GpuShare,
    GpuShareState,
    Peer,
    PeerOnlineStatus,
    VpnNetwork,
)
from deepiri_zepgpu.database.repositories.training_reservation_repository import (
    TrainingReservationConflict,
    TrainingReservationError,
    TrainingReservationOwnershipError,
    TrainingReservationRepository,
    reservation_claim,
)
from deepiri_zepgpu.database.repositories.training_run_repository import TrainingRunRepository
from deepiri_zepgpu.training.config import Phase18TrainingConfig, TrainingRunConfig
from deepiri_zepgpu.training.diloco import DiLoCoWorkerRuntime, UpdateDisposition
from deepiri_zepgpu.training.elastic_diloco_runtime import Phase18CoordinatorRuntime
from deepiri_zepgpu.training.launcher import (
    DistributedTrainingLauncher,
    TrainingLaunchError,
)
from deepiri_zepgpu.training.placement import PlacementPlan, PlacementPlanner
from deepiri_zepgpu.training.topology import GpuCandidate, ProviderCandidate

pytestmark = pytest.mark.integration
NOW = datetime.now(UTC)


@dataclass(slots=True)
class ReservationContext:
    factory: async_sessionmaker[AsyncSession]
    user_id: str
    room_id: str
    provider_ids: list[str]
    share_ids: list[str]
    config: TrainingRunConfig
    plan: PlacementPlan


@pytest_asyncio.fixture
async def reservation_context(integration_engine):
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
    user_id, room_id = uuid.uuid4(), uuid.uuid4()
    provider_ids = [uuid.uuid4(), uuid.uuid4()]
    share_ids = [uuid.uuid4(), uuid.uuid4()]
    user = User(
        id=user_id,
        username=f"phase18-{uuid.uuid4().hex[:8]}",
        email=f"phase18-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="unused",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    room = VpnNetwork(id=room_id, name="phase18", host_id=user_id)
    peers = [
        Peer(
            id=peer_id,
            user_id=user_id,
            vpn_network_id=room_id,
            wireguard_public_key=f"p18-{peer_id}",
            vpn_ip=f"10.8.0.{index + 2}",
            last_seen=NOW,
            online_status=PeerOnlineStatus.ONLINE,
            is_gpu_host=True,
        )
        for index, peer_id in enumerate(provider_ids)
    ]
    shares = [
        GpuShare(
            id=share_id,
            peer_id=peer_id,
            vpn_network_id=room_id,
            device_index=0,
            total_memory_mb=24_576,
            available_memory_mb=24_576,
            state=GpuShareState.IDLE,
            is_active=True,
        )
        for share_id, peer_id in zip(share_ids, provider_ids, strict=True)
    ]
    async with factory() as session:
        session.add_all([user, room, *peers, *shares])
        await session.commit()
    config = TrainingRunConfig(
        phase18=Phase18TrainingConfig(
            requested_node_count=2,
            total_gpus=2,
            min_k=1,
            reservation_ttl_seconds=30,
        )
    )
    candidates = [
        ProviderCandidate(
            provider_id=str(peer_id),
            room_id=str(room_id),
            online=True,
            health_state="healthy",
            last_seen=NOW,
            capabilities={
                "runtime": {
                    "cuda_version": "13.0",
                    "pytorch_version": "2.13.0",
                    "nccl_version": "2.27",
                },
                "topology": {},
            },
            capabilities_reported_at=NOW,
            path_type="direct",
            path_class="wan",
            path_measurement_kind="measured",
            gpu_shares=[
                GpuCandidate(
                    gpu_share_id=str(share_id),
                    provider_id=str(peer_id),
                    room_id=str(room_id),
                    device_index=0,
                    total_memory_mb=24_576,
                    available_memory_mb=24_576,
                )
            ],
        )
        for peer_id, share_id in zip(provider_ids, share_ids, strict=True)
    ]
    plan = PlacementPlanner(now=NOW).plan(room_id=str(room_id), config=config, providers=candidates)
    yield ReservationContext(
        factory=factory,
        user_id=str(user_id),
        room_id=str(room_id),
        provider_ids=[str(item) for item in provider_ids],
        share_ids=[str(item) for item in share_ids],
        config=config,
        plan=plan,
    )
    async with integration_engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE training_run_events, training_outer_rounds, "
                "training_gpu_reservations, training_worker_events, training_workers, "
                "training_islands, training_runs, gpu_shares, vpn_peers, vpn_networks, "
                "users RESTART IDENTITY CASCADE"
            )
        )


async def create_run(context: ReservationContext) -> str:
    async with context.factory() as session:
        run = await TrainingRunRepository(session).create(
            room_id=context.room_id,
            user_id=context.user_id,
            config=context.config.to_public_dict(),
            provider_ids=context.provider_ids,
            placement_plan=context.plan.model_dump(mode="json"),
        )
        await session.commit()
        return str(run.id)


@pytest.mark.asyncio
async def test_atomic_success_owner_release_idempotency_and_ttl(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    run_id = await create_run(context)
    async with context.factory() as session:
        run = await session.get(TrainingRun, uuid.UUID(run_id))
        assert run is not None
        repo = TrainingReservationRepository(session)
        rows = await repo.reserve_plan(run=run, plan=context.plan, owner="owner-a", ttl_seconds=30)
        assert len(rows) == 2
        await session.commit()

    async with context.factory() as session:
        shares = list(
            (await session.execute(select(GpuShare).where(GpuShare.id.in_(context.share_ids))))
            .scalars()
            .all()
        )
        assert {item.state for item in shares} == {GpuShareState.ALLOCATED}
        repo = TrainingReservationRepository(session)
        with pytest.raises(TrainingReservationOwnershipError):
            await repo.release(run_id=run_id, owner="owner-b", reason="wrong")
        assert await repo.release(run_id=run_id, owner="owner-a", reason="done") == 2
        assert await repo.release(run_id=run_id, owner="owner-a", reason="duplicate") == 0
        await session.commit()

    second_run_id = await create_run(context)
    async with context.factory() as session:
        second = await session.get(TrainingRun, uuid.UUID(second_run_id))
        assert second is not None
        repo = TrainingReservationRepository(session)
        await repo.reserve_plan(run=second, plan=context.plan, owner="ttl", ttl_seconds=30)
        assert await repo.cleanup_expired(now=NOW + timedelta(hours=1)) == 2
        await session.commit()
    async with context.factory() as session:
        shares = list((await session.execute(select(GpuShare))).scalars().all())
        assert {item.state for item in shares} == {GpuShareState.IDLE}


@pytest.mark.asyncio
async def test_partial_failure_rolls_back_every_new_claim(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    run_id = await create_run(context)
    async with context.factory() as session:
        blocked = await session.get(GpuShare, uuid.UUID(context.share_ids[1]))
        assert blocked is not None
        blocked.state = GpuShareState.ALLOCATED
        blocked.current_task_id = "generic-task"
        await session.commit()
    async with context.factory() as session:
        run = await session.get(TrainingRun, uuid.UUID(run_id))
        assert run is not None
        with pytest.raises(TrainingReservationConflict):
            await TrainingReservationRepository(session).reserve_plan(
                run=run, plan=context.plan, owner="phase18", ttl_seconds=30
            )
        await session.commit()
    async with context.factory() as session:
        shares = {
            str(item.id): item for item in (await session.execute(select(GpuShare))).scalars().all()
        }
        assert shares[context.share_ids[0]].state == GpuShareState.IDLE
        assert shares[context.share_ids[0]].current_task_id is None
        assert shares[context.share_ids[1]].current_task_id == "generic-task"


@pytest.mark.asyncio
async def test_expired_claim_is_reacquired_atomically_without_waiting_for_sweep(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    first_run_id = await create_run(context)
    second_run_id = await create_run(context)
    async with context.factory() as session:
        first = await session.get(TrainingRun, uuid.UUID(first_run_id))
        assert first is not None
        rows = await TrainingReservationRepository(session).reserve_plan(
            run=first, plan=context.plan, owner="expired-owner", ttl_seconds=30
        )
        for row in rows:
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    async with context.factory() as session:
        second = await session.get(TrainingRun, uuid.UUID(second_run_id))
        assert second is not None
        acquired = await TrainingReservationRepository(session).reserve_plan(
            run=second, plan=context.plan, owner="new-owner", ttl_seconds=30
        )
        assert len(acquired) == 2
        await session.commit()

    async with context.factory() as session:
        reservations = list((await session.execute(select(TrainingGpuReservation))).scalars().all())
        assert sum(item.state == TrainingReservationState.EXPIRED for item in reservations) == 2
        assert sum(item.state == TrainingReservationState.ACTIVE for item in reservations) == 2
        shares = list((await session.execute(select(GpuShare))).scalars().all())
        assert {item.current_task_id for item in shares} == {
            reservation_claim(second_run_id, "new-owner")
        }


@pytest.mark.asyncio
async def test_concurrent_runs_cannot_reserve_the_same_shares(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    run_ids = [await create_run(context), await create_run(context)]

    async def attempt(run_id: str) -> str:
        async with context.factory() as session:
            run = await session.get(TrainingRun, uuid.UUID(run_id))
            assert run is not None
            try:
                await TrainingReservationRepository(session).reserve_plan(
                    run=run, plan=context.plan, owner=run_id, ttl_seconds=30
                )
                await session.commit()
                return "won"
            except TrainingReservationConflict:
                await session.rollback()
                return "conflict"

    outcomes = await asyncio.gather(*(attempt(run_id) for run_id in run_ids))
    assert sorted(outcomes) == ["conflict", "won"]


@pytest.mark.asyncio
async def test_worker_lease_renewal_survives_original_ttl_then_expires(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    run_id = await create_run(context)
    async with context.factory() as session:
        run = await TrainingRunRepository(session).get(run_id)
        assert run is not None
        await DistributedTrainingLauncher(session, credential_secret=b"x" * 32).launch(
            run, reservation_owner=context.user_id
        )
        workers = sorted(run.workers, key=lambda item: str(item.id))
        worker = workers[0]
        reservations = list(
            (
                await session.execute(
                    select(TrainingGpuReservation).where(
                        TrainingGpuReservation.worker_id == worker.id
                    )
                )
            )
            .scalars()
            .all()
        )
        original_expiry = reservations[0].expires_at
        for active_worker in workers:
            await TrainingReservationRepository(session).renew(
                run_id=run_id,
                worker_id=str(active_worker.id),
                owner=context.user_id,
                ttl_seconds=30,
                now=original_expiry - timedelta(seconds=1),
            )
        renewed_expiry = reservations[0].expires_at
        assert renewed_expiry > original_expiry
        assert (
            await TrainingReservationRepository(session).cleanup_expired(
                now=original_expiry + timedelta(seconds=1)
            )
            == 0
        )
        assert (
            await TrainingReservationRepository(session).cleanup_expired(
                now=renewed_expiry + timedelta(seconds=1)
            )
            == 2
        )


@pytest.mark.asyncio
async def test_worker_lease_renewal_is_owner_active_and_terminal_scoped(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    run_id = await create_run(context)
    async with context.factory() as session:
        repo = TrainingRunRepository(session)
        run = await repo.get(run_id)
        assert run is not None
        launcher = DistributedTrainingLauncher(session, credential_secret=b"x" * 32)
        await launcher.launch(run, reservation_owner=context.user_id)
        worker = sorted(run.workers, key=lambda item: str(item.id))[0]
        leases = TrainingReservationRepository(session)
        with pytest.raises(TrainingReservationOwnershipError):
            await leases.renew(
                run_id=run_id,
                worker_id=str(worker.id),
                owner="another-owner",
                ttl_seconds=30,
            )
        worker.state = TrainingWorkerState.RECONNECTING
        with pytest.raises(TrainingReservationError, match="inactive worker"):
            await leases.renew(
                run_id=run_id,
                worker_id=str(worker.id),
                owner=context.user_id,
                ttl_seconds=30,
            )
        worker.state = TrainingWorkerState.CREATED
        await launcher.cancel(run)
        with pytest.raises(TrainingReservationError, match="terminal run"):
            await leases.renew(
                run_id=run_id,
                worker_id=str(worker.id),
                owner=context.user_id,
                ttl_seconds=30,
            )


@pytest.mark.asyncio
async def test_concurrent_renewal_prevents_cleanup_from_releasing_healthy_lease(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    run_id = await create_run(context)
    async with context.factory() as session:
        run = await TrainingRunRepository(session).get(run_id)
        assert run is not None
        await DistributedTrainingLauncher(session, credential_secret=b"x" * 32).launch(
            run, reservation_owner=context.user_id
        )
        worker_ids = [str(item.id) for item in sorted(run.workers, key=lambda item: str(item.id))]
        worker_id = worker_ids[0]
        expiry = (
            await session.execute(
                select(TrainingGpuReservation.expires_at).where(
                    TrainingGpuReservation.worker_id == worker_id
                )
            )
        ).scalar_one()
        await session.commit()

    async def renew() -> int:
        async with context.factory() as session:
            count = 0
            for current_worker_id in worker_ids:
                count += await TrainingReservationRepository(session).renew(
                    run_id=run_id,
                    worker_id=current_worker_id,
                    owner=context.user_id,
                    ttl_seconds=30,
                    now=expiry - timedelta(milliseconds=1),
                )
            await session.commit()
            return count

    async def cleanup() -> int:
        await asyncio.sleep(0)
        async with context.factory() as session:
            count = await TrainingReservationRepository(session).cleanup_expired(
                now=expiry + timedelta(milliseconds=1)
            )
            await session.commit()
            return count

    renewed, expired = await asyncio.gather(renew(), cleanup())
    assert renewed == 2
    assert expired == 0
    async with context.factory() as session:
        reservation = (
            await session.execute(
                select(TrainingGpuReservation).where(TrainingGpuReservation.worker_id == worker_id)
            )
        ).scalar_one()
        assert reservation.state == TrainingReservationState.ACTIVE


@pytest.mark.asyncio
async def test_launcher_is_idempotent_and_cancellation_releases_all(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    run_id = await create_run(context)
    async with context.factory() as session:
        run = await TrainingRunRepository(session).get(run_id)
        assert run is not None
        launcher = DistributedTrainingLauncher(session, credential_secret=b"x" * 32)
        first = await launcher.launch(run, reservation_owner=context.user_id)
        second = await launcher.launch(run, reservation_owner=context.user_id)
        assert first.idempotent is False
        assert second.idempotent is True
        assert first.reservation_ids == second.reservation_ids
        assert sorted(item.global_rank for item in first.workers) == [0, 1]
        await launcher.cancel(run)
        await session.commit()
    async with context.factory() as session:
        shares = list((await session.execute(select(GpuShare))).scalars().all())
        assert {item.state for item in shares} == {GpuShareState.IDLE}


@pytest.mark.asyncio
async def test_launcher_readiness_and_max_runtime_deadlines_release_safely(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    expired_readiness_run_id = await create_run(context)
    async with context.factory() as session:
        run = await TrainingRunRepository(session).get(expired_readiness_run_id)
        assert run is not None
        phase18 = dict(run.config["phase18"])
        phase18["readiness_timeout_seconds"] = 1
        run.config = {**run.config, "phase18": phase18}
        run.created_at = datetime.now(UTC) - timedelta(seconds=2)
        launcher = DistributedTrainingLauncher(session, credential_secret=b"x" * 32)
        with pytest.raises(TrainingLaunchError, match="readiness deadline"):
            await launcher.launch(run, reservation_owner=context.user_id)
        active = list(
            (
                await session.execute(
                    select(TrainingGpuReservation).where(
                        TrainingGpuReservation.run_id == run.id,
                        TrainingGpuReservation.state == TrainingReservationState.ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert active == []

    runtime_run_id = await create_run(context)
    async with context.factory() as session:
        repo = TrainingRunRepository(session)
        run = await repo.get(runtime_run_id)
        assert run is not None
        phase18 = dict(run.config["phase18"])
        phase18["maximum_runtime_seconds"] = 30
        run.config = {**run.config, "phase18": phase18}
        await DistributedTrainingLauncher(session, credential_secret=b"x" * 32).launch(
            run, reservation_owner=context.user_id
        )
        first_worker = sorted(run.workers, key=lambda item: str(item.id))[0]
        await repo.record_worker_event(
            run,
            first_worker,
            event_id=str(uuid.uuid4()),
            kind="ready",
            occurred_at=datetime.now(UTC),
            payload={},
        )
        await repo.start(run)
        run.started_at = datetime.now(UTC) - timedelta(seconds=31)
        await repo.enforce_startup_deadline(run, now=datetime.now(UTC))
        assert run.state == TrainingRunState.TIMED_OUT
        assert run.error == "maximum Phase 18 training runtime expired"
        assert {item.state for item in run.workers} == {TrainingWorkerState.CANCELLED}
        await session.commit()

    async with context.factory() as session:
        shares = list((await session.execute(select(GpuShare))).scalars().all())
        assert {item.state for item in shares} == {GpuShareState.IDLE}


@pytest.mark.asyncio
async def test_persisted_min_k_late_update_and_checkpoint_rejoin(
    reservation_context: ReservationContext,
) -> None:
    context = reservation_context
    run_id = await create_run(context)
    async with context.factory() as session:
        repo = TrainingRunRepository(session)
        run = await repo.get(run_id)
        assert run is not None
        launcher = DistributedTrainingLauncher(session, credential_secret=b"x" * 32)
        await launcher.launch(run, reservation_owner=context.user_id)

        async def submit(worker_index: int, kind: str, payload: dict | None = None) -> None:
            worker = sorted(run.workers, key=lambda item: str(item.id))[worker_index]
            await repo.record_worker_event(
                run,
                worker,
                event_id=str(uuid.uuid4()),
                kind=kind,
                occurred_at=datetime.now(UTC),
                payload=payload or {},
            )

        await submit(0, "ready")
        assert run.state == TrainingRunState.READY
        await repo.start(run)
        workers = sorted(run.workers, key=lambda item: str(item.id))
        initial = {"adapter": np.zeros((4,), dtype=np.float32)}
        worker_runtimes = [
            DiLoCoWorkerRuntime(
                room_id=context.room_id,
                run_id=run_id,
                worker_id=str(worker.id),
                config=context.config,
                initial_state=initial,
            )
            for worker in workers
        ]
        runtime = Phase18CoordinatorRuntime(session)
        for worker, local in zip(workers, worker_runtimes, strict=True):
            await runtime.register(run, worker, local.initial_state_envelope())

        update0 = worker_runtimes[0].encode_update(
            round_number=1,
            delta={"adapter": np.ones((4,), dtype=np.float32)},
            completed_local_steps=1,
        )
        accepted = await runtime.submit_update(run, workers[0], update0)
        assert accepted.finalized is False

        workers[1].state = TrainingWorkerState.RECONNECTING
        await runtime.mark_worker_failed(run, workers[1], reason="simulated outage")
        assert run.current_outer_round == 1

        stale = worker_runtimes[1].encode_update(
            round_number=1,
            delta={"adapter": np.full((4,), 9, dtype=np.float32)},
            completed_local_steps=1,
        )
        late = await runtime.submit_update(run, workers[1], stale)
        assert late.receipt.disposition == UpdateDisposition.LATE

        outer_state = await runtime.bootstrap(run, workers[1])
        restored = worker_runtimes[1].apply_global_state(outer_state)
        worker0_state = worker_runtimes[0].apply_global_state(
            (await runtime.global_state(run, workers[0], round_number=1)) or b""
        )
        assert np.array_equal(restored["adapter"], worker0_state["adapter"])
        assert workers[1].state == TrainingWorkerState.RUNNING
        for worker, local, value in zip(workers, worker_runtimes, (2.0, 4.0), strict=True):
            result = await runtime.submit_update(
                run,
                worker,
                local.encode_update(
                    round_number=2,
                    delta={"adapter": np.full((4,), value, dtype=np.float32)},
                    completed_local_steps=2,
                ),
            )
        assert result.finalized is True
        assert run.current_outer_round == 2

        outer_round = (
            await session.execute(
                select(TrainingOuterRound).where(
                    TrainingOuterRound.run_id == run.id,
                    TrainingOuterRound.round_number == 1,
                )
            )
        ).scalar_one()
        assert outer_round.state == TrainingOuterRoundState.FINALIZED
        assert len(outer_round.accepted_worker_ids) == 1
        assert len(outer_round.rejected_updates) == 1
        assert run.artifacts[-1]["outer_round"] == 2
        await launcher.cancel(run)
        await session.commit()

    async with context.factory() as session:
        shares = list((await session.execute(select(GpuShare))).scalars().all())
        assert {item.state for item in shares} == {GpuShareState.IDLE}
