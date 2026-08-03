"""Provider capability inventory normalization and staleness checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

UNAVAILABLE: Final = "unavailable"

CAPABILITY_STALE_AFTER: Final = timedelta(minutes=10)

GPU_OPTIONAL_NUMERIC: Final = ("temperature_celsius", "power_watts", "utilization_percent")
GPU_OPTIONAL_STR: Final = ("compute_capability", "name", "gpu_type", "state")

RUNTIME_KEYS: Final = (
    "compute_capability",
    "driver_version",
    "cuda_version",
    "pytorch_version",
    "container_runtime",
    "nccl_version",
    "fsdp_available",
    "deepspeed_available",
)

TOPOLOGY_KEYS: Final = (
    "p2p_access",
    "nvlink",
    "pcie_generation",
    "topology_hint",
)


def _unavailable() -> str:
    return UNAVAILABLE


def _mark_missing(keys: tuple[str, ...], payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for key in keys:
        if key not in out or out[key] is None:
            out[key] = _unavailable()
    return out


def normalize_gpu_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize one GPU inventory entry; missing optionals → unavailable."""

    entry: dict[str, Any] = {
        "device_index": int(raw["device_index"]),
        "total_memory_mb": int(raw["total_memory_mb"]),
        "available_memory_mb": int(raw["available_memory_mb"]),
    }
    for key in GPU_OPTIONAL_STR:
        value = raw.get(key)
        entry[key] = value if value is not None else _unavailable()
    for key in GPU_OPTIONAL_NUMERIC:
        value = raw.get(key)
        entry[key] = value if value is not None else _unavailable()
    return entry


def normalize_capabilities(
    raw: dict[str, Any] | None,
    *,
    reported_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a timestamped capability inventory with explicit unavailable fields."""

    payload = dict(raw or {})
    gpus_raw = payload.get("gpus") or payload.get("gpu_status") or []
    gpus = [normalize_gpu_entry(g) for g in gpus_raw if isinstance(g, dict)]

    runtime = _mark_missing(RUNTIME_KEYS, dict(payload.get("runtime") or {}))
    topology = _mark_missing(TOPOLOGY_KEYS, dict(payload.get("topology") or {}))

    ts = reported_at or datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)

    return {
        "reported_at": ts.isoformat(),
        "gpu_count": len(gpus),
        "gpus": gpus,
        "runtime": runtime,
        "topology": topology,
    }


def capabilities_are_stale(
    reported_at: datetime | None,
    *,
    now: datetime | None = None,
    max_age: timedelta = CAPABILITY_STALE_AFTER,
) -> bool:
    if reported_at is None:
        return True
    current = now or datetime.now(UTC)
    if reported_at.tzinfo is None:
        reported_at = reported_at.replace(tzinfo=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return (current - reported_at) > max_age


def summarize_capabilities(capabilities: dict[str, Any] | None) -> dict[str, Any]:
    """Compact summary for API/UI node cards."""

    if not capabilities:
        return {
            "gpu_count": 0,
            "runtime": {k: UNAVAILABLE for k in RUNTIME_KEYS},
            "topology": {k: UNAVAILABLE for k in TOPOLOGY_KEYS},
            "reported_at": None,
        }

    runtime = capabilities.get("runtime") or {}
    topology = capabilities.get("topology") or {}
    return {
        "gpu_count": int(capabilities.get("gpu_count") or len(capabilities.get("gpus") or [])),
        "runtime": {k: runtime.get(k, UNAVAILABLE) for k in RUNTIME_KEYS},
        "topology": {k: topology.get(k, UNAVAILABLE) for k in TOPOLOGY_KEYS},
        "reported_at": capabilities.get("reported_at"),
        "cuda_version": runtime.get("cuda_version", UNAVAILABLE),
        "pytorch_version": runtime.get("pytorch_version", UNAVAILABLE),
        "driver_version": runtime.get("driver_version", UNAVAILABLE),
    }
