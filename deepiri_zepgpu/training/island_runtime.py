"""Fail-closed island-local FSDP2 and narrow tensor-parallel runtime helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from deepiri_zepgpu.training.config import DistributedStrategy
from deepiri_zepgpu.training.topology import GpuIsland


class IslandRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IslandRankAssignment:
    worker_id: str
    provider_id: str
    gpu_share_id: str
    device_index: int
    global_rank: int
    island_rank: int
    world_size: int
    island_world_size: int
    island_id: str


@dataclass(frozen=True, slots=True)
class ProcessGroupConfig:
    backend: str
    rank: int
    world_size: int
    local_rank: int
    init_method: str
    island_id: str


def validate_island_strategy(island: GpuIsland, strategy: DistributedStrategy) -> None:
    if strategy not in {DistributedStrategy.FSDP2, DistributedStrategy.TENSOR_PARALLEL}:
        raise IslandRuntimeError("island runtime only launches FSDP2 or tensor_parallel")
    if island.classification not in {"same_host", "lan"}:
        raise IslandRuntimeError("FSDP2/tensor parallel cannot span WAN links")
    if not island.runtime_compatible:
        raise IslandRuntimeError("island runtime versions are missing or incompatible")
    if not bool(getattr(island.eligibility, strategy.value)):
        reason = island.eligibility.reasons.get(strategy.value, "strategy is not eligible")
        raise IslandRuntimeError(reason)
    if island.classification == "lan" and island.path_measurement_kind != "measured":
        raise IslandRuntimeError("LAN distributed execution requires measured network evidence")


class IslandRuntime:
    def __init__(
        self,
        *,
        island: GpuIsland,
        strategy: DistributedStrategy,
        assignment: IslandRankAssignment,
        init_method: str = "env://",
    ) -> None:
        validate_island_strategy(island, strategy)
        if assignment.island_id != island.island_id:
            raise IslandRuntimeError("rank assignment belongs to a different island")
        if assignment.island_rank >= assignment.island_world_size:
            raise IslandRuntimeError("island rank is outside island world size")
        if assignment.global_rank >= assignment.world_size:
            raise IslandRuntimeError("global rank is outside world size")
        self.island = island
        self.strategy = strategy
        self.assignment = assignment
        self.process_group = ProcessGroupConfig(
            backend="nccl",
            rank=assignment.island_rank,
            world_size=assignment.island_world_size,
            local_rank=assignment.device_index,
            init_method=init_method,
            island_id=island.island_id,
        )

    def startup_environment(self) -> dict[str, str]:
        """Deterministic torchrun-compatible environment, without starting a process."""

        return {
            "RANK": str(self.assignment.island_rank),
            "WORLD_SIZE": str(self.assignment.island_world_size),
            "LOCAL_RANK": str(self.assignment.device_index),
            "ZEPGPU_GLOBAL_RANK": str(self.assignment.global_rank),
            "ZEPGPU_GLOBAL_WORLD_SIZE": str(self.assignment.world_size),
            "ZEPGPU_ISLAND_ID": self.assignment.island_id,
            "CUDA_VISIBLE_DEVICES": str(self.assignment.device_index),
        }

    def validate_environment(self) -> Any:
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise IslandRuntimeError("PyTorch is required for island-local execution") from exc
        if not torch.cuda.is_available():
            raise IslandRuntimeError("CUDA is required for FSDP2/tensor-parallel execution")
        if not torch.distributed.is_available():
            raise IslandRuntimeError("torch.distributed is unavailable")
        if self.strategy == DistributedStrategy.FSDP2:
            try:
                from torch.distributed._composable.fsdp import fully_shard  # noqa: F401
            except ImportError as exc:
                raise IslandRuntimeError("installed PyTorch does not provide FSDP2") from exc
        else:
            try:
                from torch.distributed.tensor.parallel import parallelize_module  # noqa: F401
            except ImportError as exc:
                raise IslandRuntimeError(
                    "installed PyTorch does not provide tensor-parallel APIs"
                ) from exc
        return torch

    def initialize_process_group(self) -> None:
        """Initialize only the island-local NCCL group; never a WAN-wide group."""

        torch = self.validate_environment()
        for key, value in self.startup_environment().items():
            os.environ[key] = value
        torch.cuda.set_device(self.assignment.device_index)
        if not torch.distributed.is_initialized():
            torch.distributed.init_process_group(
                backend=self.process_group.backend,
                init_method=self.process_group.init_method,
                rank=self.process_group.rank,
                world_size=self.process_group.world_size,
            )

    def wrap_model(self, model: Any, *, parallelize_plan: Any | None = None) -> Any:
        """Apply the explicitly selected strategy after process-group initialization."""

        torch = self.validate_environment()
        if not torch.distributed.is_initialized():
            raise IslandRuntimeError("island process group must be initialized before wrapping")
        if self.strategy == DistributedStrategy.FSDP2:
            from torch.distributed._composable.fsdp import fully_shard

            fully_shard(model)
            return model
        if parallelize_plan is None:
            raise IslandRuntimeError(
                "tensor_parallel requires an explicit model-specific parallelize_plan"
            )
        from torch.distributed.device_mesh import init_device_mesh
        from torch.distributed.tensor.parallel import parallelize_module

        mesh = init_device_mesh("cuda", (self.assignment.island_world_size,))
        return parallelize_module(model, mesh, parallelize_plan)

    def peak_vram_bytes(self) -> int | None:
        try:
            torch = self.validate_environment()
        except IslandRuntimeError:
            return None
        return int(torch.cuda.max_memory_allocated(self.assignment.device_index))
