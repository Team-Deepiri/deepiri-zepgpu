"""Phase 18 configuration compatibility and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deepiri_zepgpu.api.server.routes.training_runs import CreateTrainingRunRequest
from deepiri_zepgpu.training.config import (
    DistributedStrategy,
    DistributedTrainingConfig,
    NetworkScope,
    Phase18TrainingConfig,
    RuntimeRequirements,
    TrainingRunConfig,
)


def test_phase15_and_phase17_configs_remain_valid() -> None:
    phase15 = TrainingRunConfig(schema_version=1)
    assert phase15.schema_version == 1
    phase17 = TrainingRunConfig(
        schema_version=2,
        distributed=DistributedTrainingConfig(enabled=True, worker_count=2),
    )
    assert phase17.schema_version == 2
    assert phase17.distributed.worker_count == 2


def test_phase17_more_than_two_workers_remains_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly two"):
        TrainingRunConfig(
            schema_version=2,
            distributed=DistributedTrainingConfig(enabled=True, worker_count=3),
        )


def test_phase18_accepts_three_workers_and_maps_h() -> None:
    config = TrainingRunConfig(
        phase18=Phase18TrainingConfig(
            requested_node_count=3,
            gpus_per_node=1,
            total_gpus=3,
            min_k=2,
            diloco_h=8,
        )
    )
    assert config.schema_version == 3
    assert config.distributed.enabled is True
    assert config.distributed.worker_count == 3
    assert config.distributed.local_steps_per_round == 8


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"diloco_h": 0}, "greater than or equal to 1"),
        ({"min_k": 4}, "min_k cannot exceed"),
        ({"total_gpus": 2}, "total_gpus must equal"),
    ],
)
def test_phase18_invalid_job_shapes_rejected(overrides: dict, message: str) -> None:
    values = {
        "requested_node_count": 3,
        "gpus_per_node": 1,
        "total_gpus": 3,
        "min_k": 2,
        **overrides,
    }
    with pytest.raises(ValidationError, match=message):
        Phase18TrainingConfig(**values)


@pytest.mark.parametrize(
    "strategy", [DistributedStrategy.FSDP2, DistributedStrategy.TENSOR_PARALLEL]
)
def test_coupled_strategies_reject_wan(strategy: DistributedStrategy) -> None:
    with pytest.raises(ValidationError, match="cannot span WAN"):
        Phase18TrainingConfig(
            strategy=strategy,
            requested_node_count=1,
            gpus_per_node=2,
            total_gpus=2,
            min_k=1,
            network_scope=NetworkScope.WAN,
        )


def test_unsupported_cpu_fp16_phase18_rejected() -> None:
    with pytest.raises(ValidationError, match="fp16 Phase 18 training requires CUDA"):
        TrainingRunConfig(
            precision="fp16",
            phase18=Phase18TrainingConfig(
                requested_node_count=1,
                total_gpus=1,
                min_k=1,
                runtime_requirements=RuntimeRequirements(requires_cuda=False),
            ),
        )


def test_create_request_preserves_phase17_two_provider_gate() -> None:
    import uuid

    config = TrainingRunConfig(
        schema_version=2,
        distributed=DistributedTrainingConfig(enabled=True),
    )
    with pytest.raises(ValidationError, match="exactly two provider_ids"):
        CreateTrainingRunRequest(room_id=uuid.uuid4(), provider_ids=[uuid.uuid4()], config=config)


def test_privileged_phase18_runtime_remains_prohibited() -> None:
    with pytest.raises(ValidationError, match="privileged"):
        TrainingRunConfig.model_validate(
            {
                "phase18": {
                    "requested_node_count": 1,
                    "total_gpus": 1,
                    "min_k": 1,
                },
                "distributed": {"runtime": {"privileged": True}},
            }
        )
