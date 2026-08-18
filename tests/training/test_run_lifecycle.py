from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.training_run import (
    TrainingRun,
    TrainingRunState,
    TrainingWorker,
    TrainingWorkerState,
)
from deepiri_zepgpu.database.repositories.training_run_repository import (
    TrainingRunRepository,
    TrainingRunTransitionError,
)


def run_record() -> TrainingRun:
    now = datetime.now(UTC)
    return TrainingRun(
        id=uuid4(),
        vpn_network_id=uuid4(),
        user_id=uuid4(),
        state=TrainingRunState.CREATED,
        config_version=1,
        config={"schema_version": 1},
        provider_ids=[],
        artifacts=[],
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_training_run_state_machine() -> None:
    session = AsyncMock()
    repository = TrainingRunRepository(session)
    run = run_record()
    await repository.prepare(run)
    await repository.transition(run, TrainingRunState.READY)
    await repository.start(run)
    assert run.state == TrainingRunState.RUNNING
    assert run.started_at is not None
    await repository.transition(run, TrainingRunState.SYNCING)
    await repository.transition(run, TrainingRunState.RUNNING)
    await repository.transition(run, TrainingRunState.CHECKPOINTING)
    await repository.transition(run, TrainingRunState.COMPLETED)
    assert run.completed_at is not None
    with pytest.raises(TrainingRunTransitionError):
        await repository.abort(run)


@pytest.mark.asyncio
async def test_invalid_transition_rejected() -> None:
    repository = TrainingRunRepository(AsyncMock())
    with pytest.raises(TrainingRunTransitionError):
        await repository.transition(run_record(), TrainingRunState.COMPLETED)


@pytest.mark.asyncio
async def test_reconcile_completed_workers_heals_checkpointing() -> None:
    session = AsyncMock()
    repository = TrainingRunRepository(session)
    now = datetime.now(UTC)
    run = TrainingRun(
        id=uuid4(),
        vpn_network_id=uuid4(),
        user_id=uuid4(),
        state=TrainingRunState.CHECKPOINTING,
        config_version=1,
        config={"schema_version": 1},
        provider_ids=["a", "b"],
        artifacts=[],
        workers=[
            TrainingWorker(id=uuid4(), peer_id="a", state=TrainingWorkerState.COMPLETED),
            TrainingWorker(id=uuid4(), peer_id="b", state=TrainingWorkerState.COMPLETED),
        ],
        created_at=now,
        updated_at=now,
    )
    repository._lock_run = AsyncMock(return_value=run)  # type: ignore[method-assign]
    healed = await repository.reconcile_completed_workers(run)
    assert healed.state == TrainingRunState.COMPLETED
    assert healed.completed_at is not None


def test_overlay_worker_copies_credential_revoked_at() -> None:
    now = datetime.now(UTC)
    destination = TrainingWorker(peer_id="a", state=TrainingWorkerState.RUNNING)
    source = TrainingWorker(
        peer_id="a",
        state=TrainingWorkerState.COMPLETED,
        credential_revoked_at=now,
        current_round=3,
    )
    TrainingRunRepository._overlay_worker(destination, source)
    assert destination.state == TrainingWorkerState.COMPLETED
    assert destination.credential_revoked_at == now
    assert destination.current_round == 3
