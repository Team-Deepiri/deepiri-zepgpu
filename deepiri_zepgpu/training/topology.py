"""Deterministic, fail-closed GPU-island construction for Phase 18."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from deepiri_zepgpu.rooms.capabilities import CAPABILITY_STALE_AFTER, UNAVAILABLE

IslandClass = Literal["same_host", "lan", "wan_worker"]


class GpuCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gpu_share_id: str
    provider_id: str
    room_id: str
    device_index: int
    total_memory_mb: int = Field(ge=0)
    available_memory_mb: int = Field(ge=0)
    compute_capability: str | None = None
    active: bool = True
    state: str = "idle"
    current_task_id: str | None = None


class ProviderCandidate(BaseModel):
    """Planner input derived from the existing Peer/GpuShare inventory."""

    model_config = ConfigDict(extra="forbid")

    provider_id: str
    room_id: str
    node_name: str | None = None
    revoked: bool = False
    online: bool = False
    health_state: str | None = None
    last_seen: datetime | None = None
    heartbeat_interval_seconds: int = Field(default=30, ge=1)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    capabilities_reported_at: datetime | None = None
    path_type: str | None = None
    path_class: str | None = None
    rtt_ms: float | None = Field(default=None, ge=0)
    bandwidth_mbps: float | None = Field(default=None, ge=0)
    path_measurement_kind: str | None = None
    recent_failures: int = Field(default=0, ge=0)
    gpu_shares: list[GpuCandidate] = Field(default_factory=list)


class StrategyEligibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    single: bool = False
    diloco: bool = False
    fsdp2: bool = False
    tensor_parallel: bool = False
    reasons: dict[str, str] = Field(default_factory=dict)


class GpuIsland(BaseModel):
    model_config = ConfigDict(extra="forbid")

    island_id: str
    classification: IslandClass
    provider_ids: list[str]
    gpu_share_ids: list[str]
    device_indices: dict[str, list[int]]
    interconnect_class: str | None = None
    path_type: str | None = None
    path_class: str | None = None
    path_measurement_kind: str | None = None
    rtt_ms: float | None = None
    bandwidth_mbps: float | None = None
    pairwise_evidence: list[dict[str, Any]] = Field(default_factory=list)
    p2p_support: bool | None = None
    nvlink: bool | None = None
    pcie_generation: str | int | None = None
    topology_hint: str | None = None
    cuda_version: str | None = None
    pytorch_version: str | None = None
    nccl_version: str | None = None
    per_gpu_vram_mb: list[int]
    aggregate_capacity_mb: int = Field(ge=0)
    runtime_compatible: bool
    eligibility: StrategyEligibility
    explanation: str


def _reported(value: Any) -> bool:
    return value is not None and value != UNAVAILABLE and value != "unknown"


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _runtime(provider: ProviderCandidate) -> dict[str, Any]:
    value = provider.capabilities.get("runtime", {})
    return value if isinstance(value, dict) else {}


def _topology(provider: ProviderCandidate) -> dict[str, Any]:
    value = provider.capabilities.get("topology", {})
    return value if isinstance(value, dict) else {}


def _pairwise_paths(provider: ProviderCandidate) -> list[dict[str, Any]]:
    value = provider.capabilities.get("pairwise_paths", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _pairwise_evidence(
    source: ProviderCandidate,
    target_id: str,
    *,
    now: datetime,
    max_age: timedelta,
) -> dict[str, Any] | None:
    """Return fresh measured source→target LAN evidence, or fail closed."""

    for sample in _pairwise_paths(source):
        if sample.get("target_provider_id") != target_id:
            continue
        measured_at_raw = sample.get("measured_at")
        try:
            measured_at = _aware(datetime.fromisoformat(str(measured_at_raw)))
        except (TypeError, ValueError):
            continue
        rtt = sample.get("rtt_ms")
        bandwidth = sample.get("bandwidth_mbps")
        if (
            sample.get("measurement_kind") != "measured"
            or sample.get("path_class") not in {"lan", "high_bandwidth_lan", "same_site"}
            or not isinstance(rtt, int | float)
            or not isinstance(bandwidth, int | float)
            or rtt < 0
            or bandwidth <= 0
            or now - measured_at > max_age
        ):
            continue
        return {
            "source_provider_id": source.provider_id,
            "target_provider_id": target_id,
            "path_class": str(sample["path_class"]),
            "measurement_kind": "measured",
            "rtt_ms": float(rtt),
            "bandwidth_mbps": float(bandwidth),
            "measured_at": measured_at.isoformat(),
            "provenance": str(sample.get("provenance") or "provider_report"),
        }
    return None


def _complete_pairwise_evidence(
    providers: list[ProviderCandidate],
    *,
    now: datetime,
    max_age: timedelta,
) -> list[dict[str, Any]] | None:
    evidence: list[dict[str, Any]] = []
    for source in sorted(providers, key=lambda item: item.provider_id):
        for target in sorted(providers, key=lambda item: item.provider_id):
            if source.provider_id == target.provider_id:
                continue
            sample = _pairwise_evidence(source, target.provider_id, now=now, max_age=max_age)
            if sample is None:
                return None
            evidence.append(sample)
    return evidence


def _island_id(classification: IslandClass, providers: list[str], shares: list[str]) -> str:
    material = ":".join([classification, *sorted(providers), *sorted(shares)])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"zepgpu-island:{material}"))


def _runtime_signature(provider: ProviderCandidate) -> tuple[str, str, str]:
    runtime = _runtime(provider)
    return (
        str(runtime.get("cuda_version", UNAVAILABLE)),
        str(runtime.get("pytorch_version", UNAVAILABLE)),
        str(runtime.get("nccl_version", UNAVAILABLE)),
    )


def _same_host_island(provider: ProviderCandidate) -> GpuIsland:
    shares = sorted(provider.gpu_shares, key=lambda item: (item.device_index, item.gpu_share_id))
    runtime = _runtime(provider)
    topology = _topology(provider)
    p2p = _bool_or_none(topology.get("p2p_access"))
    nvlink = _bool_or_none(topology.get("nvlink"))
    has_runtime = all(
        _reported(runtime.get(name)) for name in ("cuda_version", "pytorch_version", "nccl_version")
    )
    multi_gpu = len(shares) > 1
    fsdp_reported = runtime.get("fsdp_available") is True
    tp_reported = runtime.get("tensor_parallel_available") is True
    fsdp2 = multi_gpu and has_runtime and p2p is True and fsdp_reported
    tp_hardware_capable = (
        multi_gpu and has_runtime and p2p is True and nvlink is True and tp_reported
    )
    # Phase 18 currently has no registered model-specific parallelize_plan.
    # Fail closed instead of advertising a strategy that the runtime cannot launch.
    tp = False
    reasons = {
        "single": "at least one reported GPU is available",
        "diloco": "provider can act as an independent DiLoCo worker",
        "fsdp2": (
            "explicit same-host FSDP2, P2P, CUDA, PyTorch, and NCCL support reported"
            if fsdp2
            else "missing explicit multi-GPU FSDP2/P2P/runtime compatibility evidence"
        ),
        "tensor_parallel": (
            "hardware/topology reports TP capability, but no supported model-specific "
            "tensor-parallel execution plan is registered"
            if tp_hardware_capable
            else "missing explicit TP/P2P/NVLink/runtime compatibility evidence"
        ),
    }
    return GpuIsland(
        island_id=_island_id(
            "same_host", [provider.provider_id], [item.gpu_share_id for item in shares]
        ),
        classification="same_host",
        provider_ids=[provider.provider_id],
        gpu_share_ids=[item.gpu_share_id for item in shares],
        device_indices={provider.provider_id: [item.device_index for item in shares]},
        interconnect_class=("nvlink" if nvlink is True else "pcie" if p2p is True else None),
        path_type=provider.path_type,
        path_class=provider.path_class,
        path_measurement_kind=provider.path_measurement_kind,
        rtt_ms=provider.rtt_ms,
        bandwidth_mbps=provider.bandwidth_mbps,
        p2p_support=p2p,
        nvlink=nvlink,
        pcie_generation=(
            topology.get("pcie_generation") if _reported(topology.get("pcie_generation")) else None
        ),
        topology_hint=(
            topology.get("topology_hint") if _reported(topology.get("topology_hint")) else None
        ),
        cuda_version=(
            str(runtime.get("cuda_version")) if _reported(runtime.get("cuda_version")) else None
        ),
        pytorch_version=(
            str(runtime.get("pytorch_version"))
            if _reported(runtime.get("pytorch_version"))
            else None
        ),
        nccl_version=(
            str(runtime.get("nccl_version")) if _reported(runtime.get("nccl_version")) else None
        ),
        per_gpu_vram_mb=[item.total_memory_mb for item in shares],
        aggregate_capacity_mb=sum(item.total_memory_mb for item in shares),
        runtime_compatible=has_runtime,
        eligibility=StrategyEligibility(
            single=bool(shares),
            diloco=bool(shares),
            fsdp2=fsdp2,
            tensor_parallel=tp,
            reasons=reasons,
        ),
        explanation=(
            f"{len(shares)} GPU(s) reported by provider {provider.provider_id}; "
            "tightly coupled strategies are enabled only from explicit capability evidence"
        ),
    )


def _lan_island(
    providers: list[ProviderCandidate], pairwise_evidence: list[dict[str, Any]]
) -> GpuIsland:
    ordered = sorted(providers, key=lambda item: item.provider_id)
    shares = sorted(
        (share for provider in ordered for share in provider.gpu_shares),
        key=lambda item: (item.provider_id, item.device_index, item.gpu_share_id),
    )
    runtimes = [_runtime(provider) for provider in ordered]
    topologies = [_topology(provider) for provider in ordered]
    runtime_compatible = len({_runtime_signature(provider) for provider in ordered}) == 1 and all(
        all(
            _reported(runtime.get(name))
            for name in ("cuda_version", "pytorch_version", "nccl_version")
        )
        for runtime in runtimes
    )
    explicit_lan = bool(pairwise_evidence) and all(
        topology.get("lan_collective_compatible") is True for topology in topologies
    )
    p2p = all(topology.get("p2p_access") is True for topology in topologies)
    fsdp = all(runtime.get("fsdp_available") is True for runtime in runtimes)
    tp = all(runtime.get("tensor_parallel_available") is True for runtime in runtimes)
    nvlink = all(topology.get("nvlink") is True for topology in topologies)
    fsdp2 = runtime_compatible and explicit_lan and p2p and fsdp
    tp_hardware_capable = runtime_compatible and explicit_lan and p2p and nvlink and tp
    # Phase 18 currently has no registered model-specific parallelize_plan.
    tensor_parallel = False
    bandwidths = [float(item["bandwidth_mbps"]) for item in pairwise_evidence]
    rtts = [float(item["rtt_ms"]) for item in pairwise_evidence]
    provider_ids = [item.provider_id for item in ordered]
    reasons = {
        "single": "multi-provider LAN islands are not ordinary single-device placements",
        "diloco": "providers may also run as independent DiLoCo workers",
        "fsdp2": (
            "all LAN peers explicitly report collective, P2P, FSDP2, and matching runtimes"
            if fsdp2
            else "LAN collective/FSDP2/P2P/runtime evidence is incomplete or incompatible"
        ),
        "tensor_parallel": (
            "LAN hardware/topology reports TP capability, but no supported model-specific "
            "tensor-parallel execution plan is registered"
            if tp_hardware_capable
            else "LAN TP/P2P/NVLink/runtime evidence is incomplete or incompatible"
        ),
    }
    first_runtime = runtimes[0]
    return GpuIsland(
        island_id=_island_id("lan", provider_ids, [item.gpu_share_id for item in shares]),
        classification="lan",
        provider_ids=provider_ids,
        gpu_share_ids=[item.gpu_share_id for item in shares],
        device_indices={
            provider.provider_id: [share.device_index for share in provider.gpu_shares]
            for provider in ordered
        },
        interconnect_class="explicit_lan_collective" if explicit_lan else None,
        path_type="direct" if explicit_lan else None,
        path_class="lan",
        path_measurement_kind="measured" if explicit_lan else None,
        rtt_ms=max(rtts) if rtts else None,
        bandwidth_mbps=min(bandwidths) if bandwidths else None,
        pairwise_evidence=pairwise_evidence,
        p2p_support=p2p if all("p2p_access" in item for item in topologies) else None,
        nvlink=nvlink if all("nvlink" in item for item in topologies) else None,
        cuda_version=str(first_runtime.get("cuda_version")) if runtime_compatible else None,
        pytorch_version=str(first_runtime.get("pytorch_version")) if runtime_compatible else None,
        nccl_version=str(first_runtime.get("nccl_version")) if runtime_compatible else None,
        per_gpu_vram_mb=[item.total_memory_mb for item in shares],
        aggregate_capacity_mb=sum(item.total_memory_mb for item in shares),
        runtime_compatible=runtime_compatible,
        eligibility=StrategyEligibility(
            diloco=bool(shares),
            fsdp2=fsdp2,
            tensor_parallel=tensor_parallel,
            reasons=reasons,
        ),
        explanation=(
            "LAN island requires fresh measured provider-to-provider paths in both directions, "
            "explicit collective compatibility, "
            "and matching reported runtime versions on every provider"
        ),
    )


def build_gpu_islands(
    providers: list[ProviderCandidate],
    *,
    now: datetime | None = None,
    pairwise_max_age: timedelta = CAPABILITY_STALE_AFTER,
) -> list[GpuIsland]:
    """Build same-host islands plus only explicitly compatible LAN groups."""

    ordered = sorted(providers, key=lambda item: item.provider_id)
    islands = [_same_host_island(provider) for provider in ordered if provider.gpu_shares]
    lan_groups: dict[tuple[str, str, str], list[ProviderCandidate]] = defaultdict(list)
    for provider in ordered:
        topology = _topology(provider)
        if (
            provider.gpu_shares
            and provider.path_class in {"lan", "high_bandwidth_lan", "same_site"}
            and provider.path_measurement_kind == "measured"
            and topology.get("lan_collective_compatible") is True
        ):
            lan_groups[_runtime_signature(provider)].append(provider)
    current = _aware(now or datetime.now(UTC))
    for providers_with_runtime in lan_groups.values():
        if len(providers_with_runtime) > 1:
            evidence = _complete_pairwise_evidence(
                providers_with_runtime, now=current, max_age=pairwise_max_age
            )
            if evidence is not None:
                islands.append(_lan_island(providers_with_runtime, evidence))
    return sorted(islands, key=lambda item: (item.classification != "same_host", item.island_id))


def provider_candidate_from_models(peer: Any, shares: list[Any]) -> ProviderCandidate:
    """Adapt existing ORM inventory without creating another capability source."""

    capabilities = dict(peer.capabilities_json or {})
    network = capabilities.get("network") or {}
    bandwidth = network.get("bandwidth_mbps") if isinstance(network, dict) else None
    return ProviderCandidate(
        provider_id=str(peer.id),
        room_id=str(peer.vpn_network_id),
        node_name=peer.node_name,
        revoked=peer.revoked_at is not None,
        online=str(getattr(peer.online_status, "value", peer.online_status)) == "online",
        health_state=peer.health_state,
        last_seen=peer.last_seen,
        heartbeat_interval_seconds=peer.heartbeat_interval_seconds,
        capabilities=capabilities,
        capabilities_reported_at=peer.capabilities_reported_at,
        path_type=peer.path_type,
        path_class=peer.path_class,
        rtt_ms=peer.coordinator_rtt_ms,
        bandwidth_mbps=float(bandwidth) if isinstance(bandwidth, int | float) else None,
        path_measurement_kind=peer.path_measurement_kind,
        recent_failures=peer.recent_failures,
        gpu_shares=[
            GpuCandidate(
                gpu_share_id=str(share.id),
                provider_id=str(share.peer_id),
                room_id=str(share.vpn_network_id),
                device_index=share.device_index,
                total_memory_mb=int(share.total_memory_mb),
                available_memory_mb=int(share.available_memory_mb),
                compute_capability=share.compute_capability,
                active=share.is_active,
                state=str(getattr(share.state, "value", share.state)),
                current_task_id=share.current_task_id,
            )
            for share in shares
        ],
    )


def utc_now() -> datetime:
    """Injectable current-time helper for callers constructing planner inputs."""

    return datetime.now(UTC)
