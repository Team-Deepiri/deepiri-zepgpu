from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from deepiri_zepgpu.database.models.training_run import TrainingRun, TrainingRunState
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
