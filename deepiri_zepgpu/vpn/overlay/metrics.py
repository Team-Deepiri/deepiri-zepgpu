"""Prometheus metrics for overlay join and path outcomes."""

from __future__ import annotations

from prometheus_client import Counter

OVERLAY_JOINS = Counter(
    "zepgpu_overlay_joins_total",
    "Overlay peer connect attempts",
    ["result", "backend"],
)

OVERLAY_PATHS = Counter(
    "zepgpu_overlay_path_total",
    "Overlay send path outcomes",
    ["path_type", "backend"],
)

OVERLAY_BYTES = Counter(
    "zepgpu_overlay_bytes_total",
    "Overlay payload bytes sent",
    ["path_type", "backend"],
)

OVERLAY_RELAY_BYTES = Counter(
    "zepgpu_overlay_relay_bytes_total",
    "Bytes that fell back to coordinator/overlay relay",
    ["backend"],
)


def record_overlay_join(*, result: str, backend: str) -> None:
    OVERLAY_JOINS.labels(result=result, backend=backend).inc()


def record_overlay_path(*, path_type: str, backend: str) -> None:
    OVERLAY_PATHS.labels(path_type=path_type, backend=backend).inc()


def record_overlay_bytes(*, path_type: str, backend: str, nbytes: int) -> None:
    if nbytes < 0:
        raise ValueError("nbytes cannot be negative")
    OVERLAY_BYTES.labels(path_type=path_type, backend=backend).inc(nbytes)
    if path_type == "relay":
        OVERLAY_RELAY_BYTES.labels(backend=backend).inc(nbytes)
