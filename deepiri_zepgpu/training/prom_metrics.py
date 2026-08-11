"""Phase 19 Prometheus metrics for training sync, checkpoints, failures, rejoins."""

from __future__ import annotations

from prometheus_client import Counter, Gauge

TRAINING_SYNC_ROUNDS = Counter(
    "zepgpu_training_sync_rounds_total",
    "Training outer/sync rounds completed",
    ["room_id", "path_type", "result"],
)

TRAINING_SYNC_BYTES = Counter(
    "zepgpu_training_sync_bytes_total",
    "Training sync payload bytes",
    ["room_id", "path_type"],
)

TRAINING_CHECKPOINTS = Counter(
    "zepgpu_training_checkpoints_total",
    "Training checkpoint save/load events",
    ["room_id", "operation", "result"],
)

TRAINING_FAILURES = Counter(
    "zepgpu_training_failures_total",
    "Training failures by cause",
    ["room_id", "cause"],
)

TRAINING_REJOINS = Counter(
    "zepgpu_training_rejoins_total",
    "Worker rejoin events",
    ["room_id", "result"],
)

TRAINING_ACTIVE_RUNS = Gauge(
    "zepgpu_training_active_runs",
    "Active training runs by state",
    ["state"],
)


def record_sync_round(*, room_id: str, path_type: str, result: str, nbytes: int = 0) -> None:
    TRAINING_SYNC_ROUNDS.labels(room_id=room_id, path_type=path_type, result=result).inc()
    if nbytes > 0:
        TRAINING_SYNC_BYTES.labels(room_id=room_id, path_type=path_type).inc(nbytes)


def record_checkpoint(*, room_id: str, operation: str, result: str) -> None:
    TRAINING_CHECKPOINTS.labels(room_id=room_id, operation=operation, result=result).inc()


def record_training_failure(*, room_id: str, cause: str) -> None:
    TRAINING_FAILURES.labels(room_id=room_id, cause=cause).inc()


def record_rejoin(*, room_id: str, result: str) -> None:
    TRAINING_REJOINS.labels(room_id=room_id, result=result).inc()


def set_active_runs(*, state: str, count: int) -> None:
    TRAINING_ACTIVE_RUNS.labels(state=state).set(count)
