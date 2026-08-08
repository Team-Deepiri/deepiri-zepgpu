"""CPU-only island-runtime and launcher assignment tests."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from deepiri_zepgpu.database.models.training_run import TrainingRun, TrainingWorker
from deepiri_zepgpu.node_agent.training_runner import TrainingAgentRunner
from deepiri_zepgpu.training.config import (
    DistributedStrategy,
    NetworkScope,
    Phase18TrainingConfig,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.credentials import verify_run_credential
from deepiri_zepgpu.training.island_runtime import (
    IslandRankAssignment,
    IslandRuntime,
    IslandRuntimeError,
    validate_island_strategy,
)
from deepiri_zepgpu.training.launcher import DistributedTrainingLauncher
from deepiri_zepgpu.training.placement import (
    PlacementPlan,
    PlacementStatus,
    SelectedGpu,
)
from deepiri_zepgpu.training.runtime import RuntimeHandle, TrainingRuntime
from deepiri_zepgpu.training.topology import GpuIsland, StrategyEligibility


def island(*, classification: str = "same_host", eligible: bool = True) -> GpuIsland:
    provider_id = str(uuid.uuid4())
    share_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    return GpuIsland(
        island_id=str(uuid.uuid4()),
        classification=classification,
        provider_ids=[provider_id],
        gpu_share_ids=share_ids,
        device_indices={provider_id: [0, 1]},
        path_class="lan" if classification == "lan" else "same_host",
        path_measurement_kind="measured",
        p2p_support=True,
        nvlink=True,
        cuda_version="13.0",
        pytorch_version="2.13.0",
        nccl_version="2.27",
        per_gpu_vram_mb=[24_576, 24_576],
        aggregate_capacity_mb=49_152,
        runtime_compatible=True,
        eligibility=StrategyEligibility(
            fsdp2=eligible,
            tensor_parallel=eligible,
            reasons={
                "fsdp2": "explicitly supported" if eligible else "missing evidence",
                "tensor_parallel": "explicitly supported" if eligible else "missing evidence",
            },
        ),
        explanation="test island",
    )


def test_island_runtime_rejects_wan_and_missing_eligibility() -> None:
    with pytest.raises(IslandRuntimeError, match="cannot span WAN"):
        validate_island_strategy(island(classification="wan_worker"), DistributedStrategy.FSDP2)
    with pytest.raises(IslandRuntimeError, match="missing evidence"):
        validate_island_strategy(island(eligible=False), DistributedStrategy.TENSOR_PARALLEL)


def test_island_runtime_rank_environment_is_deterministic() -> None:
    target = island()
    assignment = IslandRankAssignment(
        worker_id=str(uuid.uuid4()),
        provider_id=target.provider_ids[0],
        gpu_share_id=target.gpu_share_ids[1],
        device_index=1,
        global_rank=1,
        island_rank=1,
        world_size=2,
        island_world_size=2,
        island_id=target.island_id,
    )
    runtime = IslandRuntime(
        island=target,
        strategy=DistributedStrategy.FSDP2,
        assignment=assignment,
    )
    assert runtime.startup_environment() == {
        "RANK": "1",
        "WORLD_SIZE": "2",
        "LOCAL_RANK": "1",
        "ZEPGPU_GLOBAL_RANK": "1",
        "ZEPGPU_GLOBAL_WORLD_SIZE": "2",
        "ZEPGPU_ISLAND_ID": target.island_id,
        "CUDA_VISIBLE_DEVICES": "1",
    }


def test_launcher_assigns_stable_global_and_island_ranks() -> None:
    providers = [str(uuid.uuid4()), str(uuid.uuid4())]
    islands = [
        GpuIsland(
            island_id=str(uuid.uuid4()),
            classification="same_host",
            provider_ids=[provider_id],
            gpu_share_ids=[str(uuid.uuid4())],
            device_indices={provider_id: [0]},
            per_gpu_vram_mb=[24_576],
            aggregate_capacity_mb=24_576,
            runtime_compatible=True,
            eligibility=StrategyEligibility(single=True, diloco=True),
            explanation="independent worker",
        )
        for provider_id in providers
    ]
    selected = [
        SelectedGpu(
            provider_id=provider_id,
            gpu_share_id=target.gpu_share_ids[0],
            device_index=0,
            per_gpu_vram_mb=24_576,
            island_id=target.island_id,
        )
        for provider_id, target in zip(providers, islands, strict=True)
    ]
    plan = PlacementPlan(
        plan_id="p",
        room_id=str(uuid.uuid4()),
        strategy=DistributedStrategy.DILOCO,
        status=PlacementStatus.CAPABLE,
        selected_provider_ids=providers,
        selected_gpus=list(reversed(selected)),
        selected_island_ids=[item.island_id for item in islands],
        candidate_islands=islands,
        explanation="test",
    )
    workers = [TrainingWorker(id=uuid.uuid4(), peer_id=value) for value in providers]
    launcher = DistributedTrainingLauncher(cast(Any, None), credential_secret=b"x" * 32)
    first = launcher._assign_ranks(workers, plan)
    second = launcher._assign_ranks(list(reversed(workers)), plan)
    assert first == second
    all_assignments = sorted(
        (assignment for values in first.values() for assignment in values),
        key=lambda item: item.global_rank,
    )
    assert [item.global_rank for item in all_assignments] == [0, 1]
    assert all(item.island_rank == 0 for item in all_assignments)


def test_launcher_credentials_remain_room_run_worker_scoped() -> None:
    room_id, run_id, peer_id, worker_id = (uuid.uuid4() for _ in range(4))
    cfg = TrainingRunConfig(
        phase18=Phase18TrainingConfig(
            requested_node_count=1,
            total_gpus=1,
            min_k=1,
            network_scope=NetworkScope.WAN,
        )
    )
    worker = TrainingWorker(id=worker_id, peer_id=peer_id)
    run = TrainingRun(
        id=run_id,
        vpn_network_id=room_id,
        user_id=uuid.uuid4(),
        config_version=3,
        config=cfg.to_public_dict(),
        provider_ids=[str(peer_id)],
        artifacts=[],
        workers=[worker],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    secret = b"phase18-test-secret-key-material!!"
    launcher = DistributedTrainingLauncher(cast(Any, None), credential_secret=secret)
    issued = launcher._issue_credentials(run, now=datetime.now(UTC))
    credential = verify_run_credential(issued[str(worker_id)][0], secret)
    assert credential.room_id == str(room_id)
    assert credential.run_id == str(run_id)
    assert credential.worker_id == str(worker_id)
    assert credential.peer_id == str(peer_id)


class _HoldingRuntime:
    def __init__(self) -> None:
        self.specs: list[Any] = []
        self.release = asyncio.Event()

    async def start_process(self, spec: Any) -> RuntimeHandle:
        self.specs.append(spec)
        return RuntimeHandle(runtime_id=str(uuid.uuid4()), mode="process")

    async def wait(self, handle: RuntimeHandle) -> int:
        del handle
        await self.release.wait()
        return 0

    async def cleanup(self, handle: RuntimeHandle) -> None:
        del handle


@pytest.mark.asyncio
async def test_provider_launch_message_reaches_phase18_process_runtime() -> None:
    fake = _HoldingRuntime()
    runner = TrainingAgentRunner(
        provider_token="provider-secret",
        runtime=cast(TrainingRuntime, fake),
    )
    room_id, run_id, worker_id, provider_id = (str(uuid.uuid4()) for _ in range(4))
    config = TrainingRunConfig(
        device="cpu",
        precision="fp32",
        phase18=Phase18TrainingConfig(
            requested_node_count=1,
            total_gpus=1,
            min_k=1,
            runtime_requirements={"requires_cuda": False},
        ),
    )
    process = IslandRankAssignment(
        worker_id=worker_id,
        provider_id=provider_id,
        gpu_share_id=str(uuid.uuid4()),
        device_index=0,
        global_rank=0,
        island_rank=0,
        world_size=1,
        island_world_size=1,
        island_id=str(uuid.uuid4()),
    )
    handled = await runner.handle_message(
        {
            "type": "training_launch",
            "base_url": "http://127.0.0.1:8000",
            "room_id": room_id,
            "run_id": run_id,
            "worker_id": worker_id,
            "provider_id": provider_id,
            "credential": "run-secret",
            "config": config.to_public_dict(),
            "processes": [asdict(process)],
        }
    )
    assert handled is True
    assert len(fake.specs) == 1
    assert fake.specs[0].command[1:3] == ["-m", "deepiri_zepgpu.training.process_worker"]
    assert fake.specs[0].gpu_devices == [0]
    fake.release.set()
    await runner.close()
