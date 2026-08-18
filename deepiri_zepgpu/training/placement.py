"""Readiness filtering and deterministic Phase 18 placement planning."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from deepiri_zepgpu.rooms.capabilities import CAPABILITY_STALE_AFTER, capabilities_are_stale
from deepiri_zepgpu.training.config import (
    DistributedStrategy,
    Phase18TrainingConfig,
    RuntimeRequirements,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.topology import (
    GpuIsland,
    ProviderCandidate,
    build_gpu_islands,
)


class PlacementStatus(str, Enum):
    CAPABLE = "capable"
    MARGINAL = "marginal"
    INSUFFICIENT = "insufficient"


class RejectedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    code: str
    reason: str


class SelectedGpu(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    gpu_share_id: str
    device_index: int
    per_gpu_vram_mb: int
    island_id: str


class PlacementPlan(BaseModel):
    """Persistable planner result; contains no credentials or secrets."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    plan_id: str
    room_id: str
    strategy: DistributedStrategy
    status: PlacementStatus
    selected_provider_ids: list[str] = Field(default_factory=list)
    selected_gpus: list[SelectedGpu] = Field(default_factory=list)
    selected_island_ids: list[str] = Field(default_factory=list)
    candidate_islands: list[GpuIsland] = Field(default_factory=list)
    rejected_candidates: list[RejectedCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    actionable_reasons: list[str] = Field(default_factory=list)
    strategy_eligibility: dict[str, bool] = Field(default_factory=dict)
    network_measurements: dict[str, str] = Field(default_factory=dict)
    explanation: str

    @property
    def capable(self) -> bool:
        return self.status == PlacementStatus.CAPABLE


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _version_matches(required: str | None, actual: Any) -> bool:
    if required is None:
        return True
    if not isinstance(actual, str) or actual in {"", "unknown", "unavailable"}:
        return False
    return actual == required or actual.startswith(f"{required}.")


def _runtime_rejection(  # noqa: C901
    provider: ProviderCandidate, requirements: RuntimeRequirements
) -> str | None:
    runtime = provider.capabilities.get("runtime") or {}
    if not isinstance(runtime, dict):
        return "runtime capability record is missing"
    if requirements.requires_cuda:
        actual = runtime.get("cuda_version")
        if not isinstance(actual, str) or actual in {"", "unknown", "unavailable"}:
            return "required CUDA capability/version was not reported"
        if not _version_matches(requirements.cuda_version, actual):
            return "reported CUDA version is incompatible"
    pytorch = runtime.get("pytorch_version")
    if not isinstance(pytorch, str) or pytorch in {"", "unknown", "unavailable"}:
        return "required PyTorch capability/version was not reported"
    if not _version_matches(requirements.pytorch_version, pytorch):
        return "reported PyTorch version is incompatible"
    nccl = runtime.get("nccl_version")
    if (requirements.requires_fsdp2 or requirements.requires_tensor_parallel) and (
        not isinstance(nccl, str) or nccl in {"", "unknown", "unavailable"}
    ):
        return "required NCCL capability/version was not reported"
    if not _version_matches(requirements.nccl_version, nccl):
        return "reported NCCL version is incompatible"
    if requirements.requires_fsdp2 and runtime.get("fsdp_available") is not True:
        return "provider did not explicitly report FSDP2 support"
    if (
        requirements.requires_tensor_parallel
        and runtime.get("tensor_parallel_available") is not True
    ):
        return "provider did not explicitly report tensor-parallel support"
    topology = provider.capabilities.get("topology") or {}
    if not isinstance(topology, dict):
        topology = {}
    if requirements.requires_p2p and topology.get("p2p_access") is not True:
        return "provider did not explicitly report GPU P2P support"
    if requirements.requires_nvlink and topology.get("nvlink") is not True:
        return "provider did not explicitly report NVLink support"
    if requirements.maximum_rtt_ms is not None and (
        provider.rtt_ms is None or provider.rtt_ms > requirements.maximum_rtt_ms
    ):
        return "path RTT is missing or above the configured maximum"
    if requirements.minimum_bandwidth_mbps is not None and (
        provider.bandwidth_mbps is None
        or provider.bandwidth_mbps < requirements.minimum_bandwidth_mbps
    ):
        return "path bandwidth is missing or below the configured minimum"
    return None


def _eligibility(island: GpuIsland, strategy: DistributedStrategy) -> bool:
    return bool(getattr(island.eligibility, strategy.value))


def _island_rank(island: GpuIsland) -> tuple[int, int, str]:
    classification_rank = {"same_host": 0, "lan": 1, "wan_worker": 2}
    return (
        classification_rank[island.classification],
        -island.aggregate_capacity_mb,
        island.island_id,
    )


class PlacementPlanner:
    def __init__(
        self,
        *,
        now: datetime | None = None,
        capability_max_age: timedelta = CAPABILITY_STALE_AFTER,
    ) -> None:
        self.now = _aware(now or datetime.now(UTC))
        self.capability_max_age = capability_max_age

    def _filter(  # noqa: C901
        self,
        room_id: str,
        job: Phase18TrainingConfig,
        providers: list[ProviderCandidate],
    ) -> tuple[list[ProviderCandidate], list[RejectedCandidate], list[str]]:
        accepted: list[ProviderCandidate] = []
        rejected: list[RejectedCandidate] = []
        warnings: list[str] = []
        for provider in sorted(providers, key=lambda item: item.provider_id):
            code: str | None = None
            reason: str | None = None
            if provider.room_id != room_id:
                code, reason = "wrong_room", "provider does not belong to the requested room"
            elif provider.revoked:
                code, reason = "revoked", "provider membership has been revoked"
            elif not provider.online:
                code, reason = "offline", "provider is offline"
            elif provider.last_seen is None or self.now - _aware(provider.last_seen) > timedelta(
                seconds=max(90, provider.heartbeat_interval_seconds * 3)
            ):
                code, reason = "stale_heartbeat", "provider heartbeat is stale"
            elif capabilities_are_stale(
                provider.capabilities_reported_at,
                now=self.now,
                max_age=self.capability_max_age,
            ):
                code, reason = "stale_capabilities", "provider capability record is stale"
            elif provider.health_state in {"offline", "failed", "unhealthy", "revoked"}:
                code, reason = "unhealthy", f"provider health is {provider.health_state}"
            else:
                runtime_reason = _runtime_rejection(provider, job.runtime_requirements)
                if runtime_reason:
                    code, reason = "incompatible_runtime", runtime_reason
            viable_gpus = [
                gpu
                for gpu in sorted(
                    provider.gpu_shares,
                    key=lambda item: (item.device_index, item.gpu_share_id),
                )
                if gpu.room_id == room_id
                and gpu.provider_id == provider.provider_id
                and gpu.active
                and gpu.state == "idle"
                and gpu.current_task_id is None
                and gpu.total_memory_mb >= job.minimum_vram_per_gpu_mb
                and (
                    job.runtime_requirements.compute_capability is None
                    or gpu.compute_capability == job.runtime_requirements.compute_capability
                )
            ]
            if code is None and len(viable_gpus) < job.gpus_per_node:
                code, reason = (
                    "insufficient_gpu_capacity",
                    f"requires {job.gpus_per_node} idle GPU(s) with at least "
                    f"{job.minimum_vram_per_gpu_mb} MiB per GPU",
                )
            if code is not None:
                rejected.append(
                    RejectedCandidate(
                        provider_id=provider.provider_id,
                        code=code,
                        reason=reason or code,
                    )
                )
                continue
            clean = provider.model_copy(
                update={"gpu_shares": viable_gpus[: job.gpus_per_node]}, deep=True
            )
            accepted.append(clean)
            if provider.health_state in {None, "unknown", "degraded"}:
                warnings.append(
                    f"provider {provider.provider_id} health is "
                    f"{provider.health_state or 'unreported'}"
                )
            if provider.path_measurement_kind != "measured":
                warnings.append(
                    f"provider {provider.provider_id} network figures are estimated or unavailable"
                )
        return accepted, rejected, sorted(set(warnings))

    def plan(  # noqa: C901
        self,
        *,
        room_id: str,
        config: TrainingRunConfig,
        providers: list[ProviderCandidate],
    ) -> PlacementPlan:
        if config.phase18 is None or config.schema_version != 3:
            raise ValueError("placement planning requires a schema-version 3 Phase 18 config")
        job = config.phase18
        accepted, rejected, warnings = self._filter(room_id, job, providers)
        islands = build_gpu_islands(
            accepted, now=self.now, pairwise_max_age=self.capability_max_age
        )
        selected_islands: list[GpuIsland] = []
        selected_providers: list[ProviderCandidate] = []

        if job.strategy in {DistributedStrategy.FSDP2, DistributedStrategy.TENSOR_PARALLEL}:
            eligible = [
                island
                for island in islands
                if _eligibility(island, job.strategy)
                and len(island.provider_ids) == job.requested_node_count
                and len(island.gpu_share_ids) >= job.total_gpus
                and (
                    job.runtime_requirements.maximum_rtt_ms is None
                    or island.rtt_ms is not None
                    and island.rtt_ms <= job.runtime_requirements.maximum_rtt_ms
                )
                and (
                    job.runtime_requirements.minimum_bandwidth_mbps is None
                    or island.bandwidth_mbps is not None
                    and island.bandwidth_mbps >= job.runtime_requirements.minimum_bandwidth_mbps
                )
                and (
                    job.network_scope is None
                    or island.classification == job.network_scope.value
                    or (
                        job.network_scope.value == "same_host"
                        and island.classification == "same_host"
                    )
                )
            ]
            if eligible:
                selected_islands = [sorted(eligible, key=_island_rank)[0]]
                wanted = set(selected_islands[0].provider_ids)
                selected_providers = [item for item in accepted if item.provider_id in wanted]
        else:
            provider_islands = {
                island.provider_ids[0]: island
                for island in islands
                if island.classification == "same_host" and len(island.provider_ids) == 1
            }
            ranked = sorted(
                accepted,
                key=lambda item: (
                    item.recent_failures,
                    0 if item.path_class in {"same_host", "lan", "high_bandwidth_lan"} else 1,
                    item.rtt_ms if item.rtt_ms is not None else float("inf"),
                    item.provider_id,
                ),
            )
            selected_providers = ranked[: job.requested_node_count]
            selected_islands = [
                provider_islands[item.provider_id]
                for item in selected_providers
                if item.provider_id in provider_islands
            ]

        selected_gpus: list[SelectedGpu] = []
        if job.strategy in {DistributedStrategy.FSDP2, DistributedStrategy.TENSOR_PARALLEL}:
            if selected_islands:
                island = selected_islands[0]
                shares_by_id = {
                    gpu.gpu_share_id: gpu
                    for provider in selected_providers
                    for gpu in provider.gpu_shares
                }
                for share_id in island.gpu_share_ids[: job.total_gpus]:
                    gpu = shares_by_id[share_id]
                    selected_gpus.append(
                        SelectedGpu(
                            provider_id=gpu.provider_id,
                            gpu_share_id=gpu.gpu_share_id,
                            device_index=gpu.device_index,
                            per_gpu_vram_mb=gpu.total_memory_mb,
                            island_id=island.island_id,
                        )
                    )
        else:
            islands_by_provider = {
                island.provider_ids[0]: island
                for island in selected_islands
                if len(island.provider_ids) == 1
            }
            for provider in selected_providers:
                provider_island = islands_by_provider.get(provider.provider_id)
                if provider_island is None:
                    continue
                for gpu in provider.gpu_shares[: job.gpus_per_node]:
                    selected_gpus.append(
                        SelectedGpu(
                            provider_id=provider.provider_id,
                            gpu_share_id=gpu.gpu_share_id,
                            device_index=gpu.device_index,
                            per_gpu_vram_mb=gpu.total_memory_mb,
                            island_id=provider_island.island_id,
                        )
                    )

        enough = (
            len({item.provider_id for item in selected_gpus}) == job.requested_node_count
            and len(selected_gpus) == job.total_gpus
        )
        if enough:
            status = PlacementStatus.MARGINAL if warnings else PlacementStatus.CAPABLE
            explanation = (
                f"selected {job.total_gpus} GPU(s) across {job.requested_node_count} "
                f"provider(s) for {job.strategy.value}; ranking preferred same-host/LAN "
                "capacity and then reliability/path quality"
            )
            reasons: list[str] = []
        else:
            status = PlacementStatus.INSUFFICIENT
            explanation = (
                f"no eligible {job.strategy.value} placement provides {job.total_gpus} GPU(s) "
                f"across {job.requested_node_count} provider(s)"
            )
            reasons = [
                "bring additional room providers online with fresh capability reports",
                f"ensure every selected GPU has at least {job.minimum_vram_per_gpu_mb} MiB VRAM",
            ]
            if job.strategy in {
                DistributedStrategy.FSDP2,
                DistributedStrategy.TENSOR_PARALLEL,
            }:
                reasons.append(
                    "report explicit P2P/runtime/topology compatibility on a same-host or measured LAN island"
                )
                if job.network_scope is not None and job.network_scope.value == "lan":
                    reasons.append("pairwise LAN topology not measured")

        measurements = {
            provider.provider_id: (
                "measured" if provider.path_measurement_kind == "measured" else "estimated"
            )
            for provider in selected_providers
        }
        strategy_eligibility = {
            strategy.value: any(_eligibility(island, strategy) for island in islands)
            for strategy in DistributedStrategy
        }
        material = {
            "room_id": room_id,
            "config": config.to_public_dict(),
            "selected": [item.model_dump(mode="json") for item in selected_gpus],
            "rejected": [item.model_dump(mode="json") for item in rejected],
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return PlacementPlan(
            plan_id=digest,
            room_id=room_id,
            strategy=job.strategy,
            status=status,
            selected_provider_ids=sorted({item.provider_id for item in selected_gpus}),
            selected_gpus=selected_gpus,
            selected_island_ids=[item.island_id for item in selected_islands],
            candidate_islands=islands,
            rejected_candidates=rejected,
            warnings=warnings,
            actionable_reasons=reasons,
            strategy_eligibility=strategy_eligibility,
            network_measurements=measurements,
            explanation=explanation,
        )
