"""Deterministic Phase 18 topology and placement tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from deepiri_zepgpu.training.config import (
    DistributedStrategy,
    NetworkScope,
    Phase18TrainingConfig,
    RuntimeRequirements,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.placement import PlacementPlanner, PlacementStatus
from deepiri_zepgpu.training.topology import (
    GpuCandidate,
    ProviderCandidate,
    build_gpu_islands,
)

NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
ROOM = str(uuid.uuid4())


def provider(
    *,
    provider_id: str | None = None,
    gpu_count: int = 1,
    vram_mb: int = 24_576,
    online: bool = True,
    revoked: bool = False,
    last_seen: datetime = NOW,
    capabilities_at: datetime = NOW,
    path_class: str = "wan",
    measured: bool = True,
    fsdp: bool = False,
    tp: bool = False,
    topology: bool = True,
    failures: int = 0,
) -> ProviderCandidate:
    peer_id = provider_id or str(uuid.uuid4())
    runtime = {
        "cuda_version": "13.0",
        "pytorch_version": "2.13.0",
        "nccl_version": "2.27",
        "fsdp_available": fsdp,
        "tensor_parallel_available": tp,
    }
    topology_data = (
        {
            "p2p_access": True,
            "nvlink": True,
            "pcie_generation": 5,
            "topology_hint": "fully-connected",
            "lan_collective_compatible": path_class == "lan",
        }
        if topology
        else {}
    )
    return ProviderCandidate(
        provider_id=peer_id,
        room_id=ROOM,
        online=online,
        revoked=revoked,
        health_state="healthy",
        last_seen=last_seen,
        capabilities={"runtime": runtime, "topology": topology_data},
        capabilities_reported_at=capabilities_at,
        path_type="direct",
        path_class=path_class,
        rtt_ms=1 if path_class == "lan" else 50,
        bandwidth_mbps=20_000 if path_class == "lan" else 200,
        path_measurement_kind="measured" if measured else "estimated",
        recent_failures=failures,
        gpu_shares=[
            GpuCandidate(
                gpu_share_id=str(uuid.uuid5(uuid.UUID(peer_id), f"gpu-{index}")),
                provider_id=peer_id,
                room_id=ROOM,
                device_index=index,
                total_memory_mb=vram_mb,
                available_memory_mb=vram_mb,
            )
            for index in range(gpu_count)
        ],
    )


def diloco_config(*, nodes: int = 2, vram: int = 1024) -> TrainingRunConfig:
    return TrainingRunConfig(
        phase18=Phase18TrainingConfig(
            requested_node_count=nodes,
            total_gpus=nodes,
            min_k=max(1, nodes - 1),
            minimum_vram_per_gpu_mb=vram,
        )
    )


def add_pairwise_paths(
    peers: list[ProviderCandidate],
    *,
    measured_at: datetime = NOW,
    path_class: str = "lan",
    rtt_ms: float = 1.0,
    bandwidth_mbps: float = 20_000,
    measurement_kind: str = "measured",
) -> list[ProviderCandidate]:
    output: list[ProviderCandidate] = []
    for source in peers:
        paths = [
            {
                "target_provider_id": target.provider_id,
                "path_class": path_class,
                "measurement_kind": measurement_kind,
                "rtt_ms": rtt_ms,
                "bandwidth_mbps": bandwidth_mbps,
                "measured_at": measured_at.isoformat(),
                "provenance": "test_probe",
            }
            for target in peers
            if target.provider_id != source.provider_id
        ]
        output.append(
            source.model_copy(
                update={"capabilities": {**source.capabilities, "pairwise_paths": paths}},
                deep=True,
            )
        )
    return output


def test_offline_revoked_stale_and_insufficient_vram_are_excluded() -> None:
    good = provider()
    candidates = [
        good,
        provider(online=False),
        provider(revoked=True),
        provider(last_seen=NOW - timedelta(minutes=10)),
        provider(capabilities_at=NOW - timedelta(hours=1)),
        provider(vram_mb=512),
    ]
    plan = PlacementPlanner(now=NOW).plan(
        room_id=ROOM, config=diloco_config(nodes=1, vram=1024), providers=candidates
    )
    assert plan.selected_provider_ids == [good.provider_id]
    assert {item.code for item in plan.rejected_candidates} == {
        "offline",
        "revoked",
        "stale_heartbeat",
        "stale_capabilities",
        "insufficient_gpu_capacity",
    }


def test_same_host_multi_gpu_island_and_tp_fails_closed_without_model_plan() -> None:
    capable = provider(gpu_count=2, fsdp=True, tp=True)
    island = build_gpu_islands([capable])[0]

    assert island.classification == "same_host"
    assert island.provider_ids == [capable.provider_id]

    # FSDP2 is actually supported by the Phase 18 island runtime.
    assert island.eligibility.fsdp2 is True

    # Hardware may report TP/P2P/NVLink capability, but ZepGPU does not yet
    # have a supported model-specific tensor-parallel execution plan.
    assert island.eligibility.tensor_parallel is False
    assert (
        island.eligibility.reasons["tensor_parallel"]
        == "hardware/topology reports TP capability, but no supported "
        "model-specific tensor-parallel execution plan is registered"
    )


def test_missing_topology_never_enables_fsdp_or_tp() -> None:
    island = build_gpu_islands([provider(gpu_count=2, fsdp=True, tp=True, topology=False)])[0]
    assert island.p2p_support is None
    assert island.eligibility.fsdp2 is False
    assert island.eligibility.tensor_parallel is False
    assert "missing explicit" in island.eligibility.reasons["tensor_parallel"]


def test_explicit_compatible_lan_island_preferred_for_fsdp() -> None:
    peers = add_pairwise_paths(
        [provider(path_class="lan", fsdp=True), provider(path_class="lan", fsdp=True)]
    )
    config = TrainingRunConfig(
        phase18=Phase18TrainingConfig(
            strategy=DistributedStrategy.FSDP2,
            requested_node_count=2,
            total_gpus=2,
            min_k=2,
            network_scope=NetworkScope.LAN,
        )
    )
    plan = PlacementPlanner(now=NOW).plan(room_id=ROOM, config=config, providers=peers)
    assert plan.status == PlacementStatus.CAPABLE
    selected = next(
        item for item in plan.candidate_islands if item.island_id in plan.selected_island_ids
    )
    assert selected.classification == "lan"
    assert selected.path_measurement_kind == "measured"
    assert len(selected.pairwise_evidence) == 2


def test_coordinator_lan_paths_without_pairwise_samples_fail_closed() -> None:
    peers = [provider(path_class="lan", fsdp=True), provider(path_class="lan", fsdp=True)]
    config = TrainingRunConfig(
        phase18=Phase18TrainingConfig(
            strategy=DistributedStrategy.FSDP2,
            requested_node_count=2,
            total_gpus=2,
            min_k=2,
            network_scope=NetworkScope.LAN,
        )
    )
    plan = PlacementPlanner(now=NOW).plan(room_id=ROOM, config=config, providers=peers)
    assert plan.status == PlacementStatus.INSUFFICIENT
    assert "pairwise LAN topology not measured" in plan.actionable_reasons
    assert not any(item.classification == "lan" for item in plan.candidate_islands)


def test_stale_pairwise_samples_fail_closed() -> None:
    peers = add_pairwise_paths(
        [provider(path_class="lan", fsdp=True), provider(path_class="lan", fsdp=True)],
        measured_at=NOW - timedelta(hours=1),
    )
    assert not any(item.classification == "lan" for item in build_gpu_islands(peers, now=NOW))


def test_pairwise_thresholds_are_applied_to_measured_provider_paths() -> None:
    peers = add_pairwise_paths(
        [provider(path_class="lan", fsdp=True), provider(path_class="lan", fsdp=True)],
        rtt_ms=25,
        bandwidth_mbps=500,
    )
    config = TrainingRunConfig(
        phase18=Phase18TrainingConfig(
            strategy=DistributedStrategy.FSDP2,
            requested_node_count=2,
            total_gpus=2,
            min_k=2,
            network_scope=NetworkScope.LAN,
            runtime_requirements=RuntimeRequirements(
                maximum_rtt_ms=5,
                minimum_bandwidth_mbps=10_000,
            ),
        )
    )
    plan = PlacementPlanner(now=NOW).plan(room_id=ROOM, config=config, providers=peers)
    assert plan.status == PlacementStatus.INSUFFICIENT


def test_pairwise_wan_sample_never_forms_lan_island() -> None:
    peers = add_pairwise_paths(
        [provider(path_class="lan", fsdp=True), provider(path_class="lan", fsdp=True)],
        path_class="wan",
    )
    assert not any(item.classification == "lan" for item in build_gpu_islands(peers, now=NOW))


def test_wan_peers_are_diloco_workers_but_never_one_fsdp_island() -> None:
    peers = [provider(path_class="wan", fsdp=True), provider(path_class="wan", fsdp=True)]
    diloco = PlacementPlanner(now=NOW).plan(room_id=ROOM, config=diloco_config(), providers=peers)
    assert diloco.status == PlacementStatus.CAPABLE
    assert len(diloco.selected_provider_ids) == 2
    assert not any(item.classification == "lan" for item in diloco.candidate_islands)

    fsdp = TrainingRunConfig(
        phase18=Phase18TrainingConfig(
            strategy=DistributedStrategy.FSDP2,
            requested_node_count=2,
            total_gpus=2,
            min_k=2,
            network_scope=NetworkScope.LAN,
        )
    )
    rejected = PlacementPlanner(now=NOW).plan(room_id=ROOM, config=fsdp, providers=peers)
    assert rejected.status == PlacementStatus.INSUFFICIENT
    assert rejected.selected_gpus == []


def test_ranking_and_explanations_are_deterministic() -> None:
    wan = provider(path_class="wan")
    lan = provider(path_class="lan")
    planner = PlacementPlanner(now=NOW)
    first = planner.plan(room_id=ROOM, config=diloco_config(nodes=1), providers=[wan, lan])
    second = planner.plan(room_id=ROOM, config=diloco_config(nodes=1), providers=[lan, wan])
    assert first == second
    assert first.selected_provider_ids == [lan.provider_id]
    assert "ranking preferred same-host/LAN" in first.explanation


def test_estimated_network_is_marginal_and_labeled() -> None:
    estimated = provider(measured=False)
    plan = PlacementPlanner(now=NOW).plan(
        room_id=ROOM, config=diloco_config(nodes=1), providers=[estimated]
    )
    assert plan.status == PlacementStatus.MARGINAL
    assert plan.network_measurements[estimated.provider_id] == "estimated"
    assert plan.warnings
