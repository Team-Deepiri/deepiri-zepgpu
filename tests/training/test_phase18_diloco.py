"""CPU-only elastic DiLoCo, min-k, checkpoint, and rejoin tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from deepiri_zepgpu.training.config import (
    CompressionConfig,
    CompressorBackend,
    DistributedTrainingConfig,
    OuterOptimizerConfig,
    OuterOptimizerKind,
    Phase18TrainingConfig,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.diloco import (
    DiLoCoError,
    ElasticDiLoCoCoordinator,
    MembershipState,
    RoundState,
    UpdateDisposition,
)

NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)


def ids(count: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(count)]


def config(
    *,
    workers: int = 3,
    min_k: int = 2,
    h: int = 2,
    backend: CompressorBackend = CompressorBackend.NONE,
    optimizer: OuterOptimizerConfig | None = None,
) -> TrainingRunConfig:
    return TrainingRunConfig(
        distributed=DistributedTrainingConfig(
            compression=CompressionConfig(
                backend=backend,
                top_k=4,
                chunk_size=64,
                quant_bits=8,
            )
        ),
        phase18=Phase18TrainingConfig(
            requested_node_count=workers,
            total_gpus=workers,
            min_k=min_k,
            diloco_h=h,
            sync_deadline_seconds=1,
            outer_optimizer=optimizer or OuterOptimizerConfig(),
        ),
    )


def coordinator(
    cfg: TrainingRunConfig, workers: list[str], *, width: int = 8
) -> ElasticDiLoCoCoordinator:
    return ElasticDiLoCoCoordinator(
        room_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        config=cfg,
        initial_state={"w": np.zeros(width, dtype=np.float32)},
        worker_ids=workers,
        placement={"selected_island_ids": [str(uuid.uuid4())]},
    )


def encoded(
    service: ElasticDiLoCoCoordinator,
    worker_id: str,
    round_number: int,
    value: float,
    *,
    local_steps: int = 2,
) -> bytes:
    return service.encode_update(
        worker_id=worker_id,
        round_number=round_number,
        delta={"w": np.full_like(service.global_state["w"], value)},
        completed_local_steps=local_steps,
    )


def test_h_controls_outer_sync_frequency() -> None:
    workers = ids(3)
    service = coordinator(config(h=4), workers)
    assert service.should_synchronize(1) is False
    assert service.should_synchronize(3) is False
    assert service.should_synchronize(4) is True
    service.start_round(now=NOW)
    with pytest.raises(DiLoCoError, match="H=4"):
        encoded(service, workers[0], 1, 1, local_steps=3)


def test_min_k_straggler_duplicate_late_and_outer_optimizer() -> None:
    workers = ids(3)
    service = coordinator(
        config(
            optimizer=OuterOptimizerConfig(
                kind=OuterOptimizerKind.SGD, learning_rate=0.5, momentum=0.5
            )
        ),
        workers,
    )
    round_number = service.start_round(now=NOW)
    first = encoded(service, workers[0], round_number, 1)
    second = encoded(service, workers[1], round_number, 3)
    assert service.submit_encoded(first).disposition == UpdateDisposition.ACCEPTED
    assert service.submit_encoded(first).disposition == UpdateDisposition.DUPLICATE
    assert service.submit_encoded(second).disposition == UpdateDisposition.ACCEPTED
    metric = service.finalize_round(now=NOW, allow_min_k_before_deadline=True)
    assert metric is not None
    assert metric.state == RoundState.FINALIZED
    assert metric.straggler_worker_ids == [workers[2]]
    assert np.allclose(service.global_state["w"], 1.0)
    assert service.outer_optimizer.step_count == 1
    assert service.submit_encoded(first).disposition == UpdateDisposition.LATE
    assert service.latest_checkpoint is not None
    assert service.latest_checkpoint.outer_optimizer_state["step_count"] == 1


def test_strict_min_k_waits_and_below_k_pauses_at_deadline() -> None:
    workers = ids(3)
    strict = coordinator(config(min_k=3), workers)
    strict.start_round(now=NOW)
    strict.submit_encoded(encoded(strict, workers[0], 1, 1))
    strict.submit_encoded(encoded(strict, workers[1], 1, 1))
    assert strict.finalize_round(now=NOW, allow_min_k_before_deadline=True) is None
    paused = strict.finalize_round(now=NOW + timedelta(seconds=2))
    assert paused is not None
    assert paused.state == RoundState.PAUSED
    assert strict.current_round == 0


def test_phase17_compressor_is_reused_on_wan_outer_path() -> None:
    workers = ids(2)
    service = coordinator(
        config(workers=2, min_k=2, backend=CompressorBackend.ZEP), workers, width=4096
    )
    service.start_round(now=NOW)
    for index, worker_id in enumerate(workers, start=1):
        receipt = service.submit_encoded(encoded(service, worker_id, 1, float(index)))
        assert receipt.disposition == UpdateDisposition.ACCEPTED
    metric = service.finalize_round(now=NOW)
    assert metric is not None
    assert metric.path_class == "wan"
    assert metric.compressed_bytes > 0
    assert metric.uncompressed_bytes == 2 * 4096 * 4
    assert metric.compressed_bytes < metric.uncompressed_bytes


def test_three_worker_failure_rejoin_requires_latest_checkpoint() -> None:
    workers = ids(3)
    service = coordinator(config(), workers)
    service.start_round(now=NOW)
    service.mark_failed(workers[2], reason="simulated loss")
    service.submit_encoded(encoded(service, workers[0], 1, 1))
    service.submit_encoded(encoded(service, workers[1], 1, 3))
    first_metric = service.finalize_round(now=NOW)
    assert first_metric is not None and first_metric.state == RoundState.FINALIZED
    checkpoint = service.request_join(workers[2])
    assert checkpoint is not None
    assert service.members[workers[2]].state == MembershipState.BOOTSTRAPPING

    service.start_round(now=NOW)
    with pytest.raises(DiLoCoError, match="inactive worker"):
        encoded(service, workers[2], 2, 100)
    restored = service.bootstrap_worker(workers[2], checkpoint)
    assert np.array_equal(restored["w"], service.global_state["w"])
    assert service.members[workers[2]].state == MembershipState.ACTIVE
    assert service.members[workers[2]].rejoin_count == 1

    for worker_id, value in zip(workers, (1.0, 2.0, 3.0), strict=True):
        receipt = service.submit_encoded(encoded(service, worker_id, 2, value, local_steps=4))
        assert receipt.disposition == UpdateDisposition.ACCEPTED
    second_metric = service.finalize_round(now=NOW)
    assert second_metric is not None and second_metric.accepted_workers == 3
    assert service.current_round == 2
    assert any(item["kind"] == "checkpoint_bootstrap" for item in service.events)


def test_stale_checkpoint_cannot_overwrite_newer_global_state() -> None:
    workers = ids(2)
    service = coordinator(config(workers=2, min_k=2), workers)
    service.start_round(now=NOW)
    for worker_id in workers:
        service.submit_encoded(encoded(service, worker_id, 1, 1))
    service.finalize_round(now=NOW)
    old = service.latest_checkpoint
    assert old is not None
    service.start_round(now=NOW)
    for worker_id in workers:
        service.submit_encoded(encoded(service, worker_id, 2, 1, local_steps=4))
    service.finalize_round(now=NOW)
    service.mark_failed(workers[1], reason="again")
    service.request_join(workers[1])
    with pytest.raises(DiLoCoError, match="latest finalized"):
        service.bootstrap_worker(workers[1], old)
