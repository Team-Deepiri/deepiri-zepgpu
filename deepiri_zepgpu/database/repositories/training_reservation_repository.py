"""Transactional multi-GPU reservations for Phase 18 training."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.training_run import (
    TrainingGpuReservation,
    TrainingIsland,
    TrainingReservationState,
    TrainingRun,
    TrainingRunEvent,
    TrainingRunState,
    TrainingWorker,
    TrainingWorkerState,
)
from deepiri_zepgpu.database.models.vpn_models import GpuShare, GpuShareState
from deepiri_zepgpu.training.placement import PlacementPlan, PlacementStatus


class TrainingReservationError(RuntimeError):
    pass


class TrainingReservationConflict(TrainingReservationError):
    pass


class TrainingReservationOwnershipError(TrainingReservationError):
    pass


def reservation_claim(run_id: str, owner: str) -> str:
    return f"training:{run_id}:{owner}"


class TrainingReservationRepository:
    """Database-first reservation service; Redis is never the correctness boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve_plan(  # noqa: C901
        self,
        *,
        run: TrainingRun,
        plan: PlacementPlan,
        owner: str,
        ttl_seconds: int,
    ) -> list[TrainingGpuReservation]:
        if plan.status == PlacementStatus.INSUFFICIENT:
            raise TrainingReservationError("cannot reserve an insufficient placement plan")
        if str(run.vpn_network_id) != plan.room_id:
            raise TrainingReservationError("placement plan belongs to a different room")
        share_ids = sorted({item.gpu_share_id for item in plan.selected_gpus})
        if len(share_ids) != len(plan.selected_gpus) or not share_ids:
            raise TrainingReservationError("placement plan contains duplicate or no GPU shares")
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)
        claim = reservation_claim(str(run.id), owner)
        created: list[TrainingGpuReservation] = []
        # A savepoint makes a validation/flush failure all-or-none without rolling back
        # unrelated work already staged by the caller's request transaction.
        async with self.session.begin_nested():
            result = await self.session.execute(
                select(GpuShare)
                .where(GpuShare.id.in_(share_ids))
                .order_by(GpuShare.id)
                .with_for_update()
            )
            shares = list(result.scalars().all())
            if len(shares) != len(share_ids):
                raise TrainingReservationConflict("one or more selected GPU shares no longer exist")
            shares_by_id = {str(share.id): share for share in shares}

            active_result = await self.session.execute(
                select(TrainingGpuReservation)
                .where(
                    TrainingGpuReservation.gpu_share_id.in_(share_ids),
                    TrainingGpuReservation.state == TrainingReservationState.ACTIVE,
                )
                .order_by(TrainingGpuReservation.gpu_share_id)
                .with_for_update()
            )
            active = list(active_result.scalars().all())
            expired_by_run: dict[str, int] = {}
            for reservation in active:
                expiry = reservation.expires_at
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=UTC)
                if expiry > now:
                    raise TrainingReservationConflict(
                        f"GPU share {reservation.gpu_share_id} is already reserved"
                    )
                reservation.state = TrainingReservationState.EXPIRED
                reservation.released_at = now
                reservation.release_reason = "reservation TTL expired before reacquisition"
                # Reclaim an expired durable claim while the corresponding GPU-share
                # row is still locked.  If another owner changed current_task_id, the
                # normal availability validation below fails closed instead.
                share = shares_by_id.get(str(reservation.gpu_share_id))
                expected_claim = reservation_claim(
                    str(reservation.run_id), reservation.reservation_owner
                )
                if share is not None and share.current_task_id == expected_claim:
                    share.state = GpuShareState.IDLE
                    share.current_task_id = None
                expired_run_id = str(reservation.run_id)
                expired_by_run[expired_run_id] = expired_by_run.get(expired_run_id, 0) + 1
            for expired_run_id, reservation_count in sorted(expired_by_run.items()):
                self.session.add(
                    TrainingRunEvent(
                        id=uuid.uuid4(),
                        run_id=uuid.UUID(expired_run_id),
                        kind="reservation_expired",
                        payload={
                            "reservation_count": reservation_count,
                            "reason": "expired during atomic reacquisition",
                        },
                    )
                )

            selected = {item.gpu_share_id: item for item in plan.selected_gpus}
            islands = {item.island_id: item for item in plan.candidate_islands}
            persisted_island_result = await self.session.execute(
                select(TrainingIsland.id).where(
                    TrainingIsland.run_id == run.id,
                    TrainingIsland.id.in_([uuid.UUID(item) for item in plan.selected_island_ids]),
                )
            )
            persisted_island_ids = {
                str(island_id) for island_id in persisted_island_result.scalars().all()
            }
            for share in shares:
                selected_gpu = selected[str(share.id)]
                if str(share.vpn_network_id) != plan.room_id:
                    raise TrainingReservationConflict(
                        f"GPU share {share.id} moved outside the training room"
                    )
                if str(share.peer_id) != selected_gpu.provider_id:
                    raise TrainingReservationConflict(
                        f"GPU share {share.id} no longer belongs to the selected provider"
                    )
                # This coordinates with generic task allocation through the existing
                # durable state/current_task_id fields while rows are locked.
                if share.state != GpuShareState.IDLE or share.current_task_id is not None:
                    raise TrainingReservationConflict(f"GPU share {share.id} is not available")
                if not share.is_active:
                    raise TrainingReservationConflict(f"GPU share {share.id} is inactive")
                share.state = GpuShareState.ALLOCATED
                share.current_task_id = claim
                island = islands.get(selected_gpu.island_id)
                reservation = TrainingGpuReservation(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    island_id=(
                        uuid.UUID(island.island_id)
                        if island is not None and island.island_id in persisted_island_ids
                        else None
                    ),
                    vpn_network_id=run.vpn_network_id,
                    peer_id=share.peer_id,
                    gpu_share_id=share.id,
                    reservation_owner=owner,
                    state=TrainingReservationState.ACTIVE,
                    expires_at=expires_at,
                )
                self.session.add(reservation)
                created.append(reservation)
            self.session.add(
                TrainingRunEvent(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    kind="reservation_acquired",
                    payload={
                        "owner": owner,
                        "reservation_count": len(created),
                        "gpu_share_ids": share_ids,
                        "expires_at": expires_at.isoformat(),
                    },
                )
            )
            await self.session.flush()
        return created

    async def release(
        self,
        *,
        run_id: str,
        owner: str,
        reason: str,
    ) -> int:
        return await self._release(run_id=run_id, owner=owner, reason=reason, enforce_owner=True)

    async def renew(
        self,
        *,
        run_id: str,
        worker_id: str,
        owner: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> int:
        """Renew one healthy worker's owned GPU leases under row locks.

        Renewal is intentionally worker-scoped: a healthy peer cannot keep a
        failed peer's devices allocated.  Cleanup takes the same reservation
        row locks, so a concurrent cleanup either observes the renewed expiry
        or wins first and makes renewal fail closed.
        """

        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        bounded_ttl = max(30, min(int(ttl_seconds), 86400))
        run_result = await self.session.execute(
            select(TrainingRun).where(TrainingRun.id == run_id).with_for_update()
        )
        run = run_result.scalar_one_or_none()
        if run is None:
            raise TrainingReservationError("training run does not exist")
        if run.state in {
            TrainingRunState.COMPLETED,
            TrainingRunState.FAILED,
            TrainingRunState.CANCELLED,
            TrainingRunState.TIMED_OUT,
        }:
            raise TrainingReservationError("terminal run cannot renew reservations")
        worker_result = await self.session.execute(
            select(TrainingWorker).where(
                TrainingWorker.id == worker_id,
                TrainingWorker.run_id == run_id,
            )
        )
        worker = worker_result.scalar_one_or_none()
        if worker is None:
            raise TrainingReservationOwnershipError("worker does not belong to this run")
        if worker.state in {
            TrainingWorkerState.RECONNECTING,
            TrainingWorkerState.STOPPING,
            TrainingWorkerState.STOPPED,
            TrainingWorkerState.ABORTED,
            TrainingWorkerState.COMPLETED,
            TrainingWorkerState.FAILED,
            TrainingWorkerState.CANCELLED,
        }:
            raise TrainingReservationError("inactive worker cannot renew reservations")
        result = await self.session.execute(
            select(TrainingGpuReservation)
            .where(
                TrainingGpuReservation.run_id == run_id,
                TrainingGpuReservation.worker_id == worker_id,
            )
            .order_by(TrainingGpuReservation.gpu_share_id)
            .with_for_update()
        )
        rows = list(result.scalars().all())
        active = [row for row in rows if row.state == TrainingReservationState.ACTIVE]
        if any(row.reservation_owner != owner for row in active):
            raise TrainingReservationOwnershipError("reservation owner mismatch")
        if not active:
            raise TrainingReservationError("worker has no active reservation to renew")
        expires_at = current + timedelta(seconds=bounded_ttl)
        for reservation in active:
            existing = reservation.expires_at
            if existing.tzinfo is None:
                existing = existing.replace(tzinfo=UTC)
            reservation.expires_at = max(existing, expires_at)
        await self.session.flush()
        return len(active)

    async def release_terminal(self, *, run_id: str, reason: str) -> int:
        """System cleanup for a terminal run; ownership remains scoped by run id."""

        return await self._release(run_id=run_id, owner=None, reason=reason, enforce_owner=False)

    async def _release(
        self,
        *,
        run_id: str,
        owner: str | None,
        reason: str,
        enforce_owner: bool,
    ) -> int:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(TrainingGpuReservation)
            .where(TrainingGpuReservation.run_id == run_id)
            .order_by(TrainingGpuReservation.gpu_share_id)
            .with_for_update()
        )
        all_rows = list(result.scalars().all())
        active = [row for row in all_rows if row.state == TrainingReservationState.ACTIVE]
        if enforce_owner and any(row.reservation_owner != owner for row in active):
            raise TrainingReservationOwnershipError("reservation owner mismatch")
        if not active:
            return 0
        share_ids = [row.gpu_share_id for row in active]
        shares_result = await self.session.execute(
            select(GpuShare)
            .where(GpuShare.id.in_(share_ids))
            .order_by(GpuShare.id)
            .with_for_update()
        )
        shares = {str(item.id): item for item in shares_result.scalars().all()}
        for reservation in active:
            reservation.state = TrainingReservationState.RELEASED
            reservation.released_at = now
            reservation.release_reason = reason
            share = shares.get(str(reservation.gpu_share_id))
            expected_claim = reservation_claim(
                str(reservation.run_id), reservation.reservation_owner
            )
            if share is not None and share.current_task_id == expected_claim:
                share.state = GpuShareState.IDLE
                share.current_task_id = None
        self.session.add(
            TrainingRunEvent(
                id=uuid.uuid4(),
                run_id=uuid.UUID(run_id),
                kind="reservation_released",
                payload={"reason": reason, "reservation_count": len(active)},
            )
        )
        await self.session.flush()
        return len(active)

    async def cleanup_expired(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        # Discover candidates without locks, then take locks in the same
        # run→reservation→GPU order as heartbeat renewal.  skip_locked means
        # an in-flight healthy heartbeat wins and the next sweep re-evaluates
        # the newly extended expiry instead of prematurely releasing the GPU.
        run_ids_result = await self.session.execute(
            select(TrainingGpuReservation.run_id)
            .where(
                TrainingGpuReservation.state == TrainingReservationState.ACTIVE,
                TrainingGpuReservation.expires_at <= current,
            )
            .distinct()
            .order_by(TrainingGpuReservation.run_id)
        )
        count = 0
        for raw_run_id in run_ids_result.scalars().all():
            run_id = str(raw_run_id)
            run_lock = await self.session.execute(
                select(TrainingRun)
                .where(TrainingRun.id == raw_run_id)
                .with_for_update(skip_locked=True)
            )
            if run_lock.scalar_one_or_none() is None:
                continue
            expired_result = await self.session.execute(
                select(TrainingGpuReservation)
                .where(
                    TrainingGpuReservation.run_id == raw_run_id,
                    TrainingGpuReservation.state == TrainingReservationState.ACTIVE,
                    TrainingGpuReservation.expires_at <= current,
                )
                .order_by(TrainingGpuReservation.gpu_share_id)
                .with_for_update(skip_locked=True)
            )
            rows = list(expired_result.scalars().all())
            if not rows:
                continue
            share_ids = [item.gpu_share_id for item in rows]
            shares_result = await self.session.execute(
                select(GpuShare).where(GpuShare.id.in_(share_ids)).with_for_update()
            )
            shares = {str(item.id): item for item in shares_result.scalars().all()}
            for reservation in rows:
                reservation.state = TrainingReservationState.EXPIRED
                reservation.released_at = current
                reservation.release_reason = "reservation TTL expired"
                share = shares.get(str(reservation.gpu_share_id))
                expected = reservation_claim(run_id, reservation.reservation_owner)
                if share is not None and share.current_task_id == expected:
                    share.state = GpuShareState.IDLE
                    share.current_task_id = None
                count += 1
            self.session.add(
                TrainingRunEvent(
                    id=uuid.uuid4(),
                    run_id=uuid.UUID(run_id),
                    kind="reservation_expired",
                    payload={"reservation_count": len(rows)},
                )
            )
        await self.session.flush()
        return count
