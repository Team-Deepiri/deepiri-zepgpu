"""Path type/class observability and Prometheus metrics for provider↔coordinator links."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from prometheus_client import Counter, Gauge, Histogram

PATH_TYPE_DIRECT: Final = "direct"
PATH_TYPE_RELAY: Final = "relay"
PATH_TYPE_UNKNOWN: Final = "unknown"

PATH_CLASS_SAME_HOST: Final = "same_host"
PATH_CLASS_LAN: Final = "lan"
PATH_CLASS_WAN: Final = "wan"
PATH_CLASS_RELAY: Final = "relay"

MEASUREMENT_MEASURED: Final = "measured"
MEASUREMENT_ESTIMATED: Final = "estimated"

VALID_PATH_TYPES: Final = frozenset({PATH_TYPE_DIRECT, PATH_TYPE_RELAY, PATH_TYPE_UNKNOWN})
VALID_PATH_CLASSES: Final = frozenset(
    {PATH_CLASS_SAME_HOST, PATH_CLASS_LAN, PATH_CLASS_WAN, PATH_CLASS_RELAY}
)
VALID_MEASUREMENT_KINDS: Final = frozenset({MEASUREMENT_MEASURED, MEASUREMENT_ESTIMATED})

PROVIDER_COORDINATOR_RTT = Histogram(
    "zepgpu_provider_coordinator_rtt_seconds",
    "Provider to coordinator RTT measured on heartbeat",
    ["room_id", "path_class", "measurement_kind"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

PROVIDER_PATH_INFO = Gauge(
    "zepgpu_provider_path_info",
    "Provider path observability (1 = current sample)",
    ["room_id", "peer_id", "path_type", "path_class", "measurement_kind"],
)

PROVIDER_HEALTH_STATE = Gauge(
    "zepgpu_provider_health_state",
    "Provider health state encoded as 1 for the active state label",
    ["room_id", "peer_id", "health_state"],
)

PROVIDER_HEARTBEATS = Counter(
    "zepgpu_provider_heartbeats_total",
    "Provider heartbeats accepted by the coordinator",
    ["room_id", "transport_mode", "path_class"],
)


@dataclass(frozen=True)
class PathReport:
    path_type: str
    path_class: str
    coordinator_rtt_ms: float | None
    measurement_kind: str
    freshness_at: datetime
    p2p_rtt_ms: float | None = None
    bandwidth_mbps: float | None = None


def normalize_path_type(value: str | None) -> str:
    if not value:
        return PATH_TYPE_UNKNOWN
    mode = str(value).strip().lower()
    return mode if mode in VALID_PATH_TYPES else PATH_TYPE_UNKNOWN


def normalize_path_class(value: str | None) -> str:
    if not value:
        return PATH_CLASS_WAN
    mode = str(value).strip().lower()
    return mode if mode in VALID_PATH_CLASSES else PATH_CLASS_WAN


def normalize_measurement_kind(value: str | None) -> str:
    if not value:
        return MEASUREMENT_ESTIMATED
    mode = str(value).strip().lower()
    return mode if mode in VALID_MEASUREMENT_KINDS else MEASUREMENT_ESTIMATED


def infer_path_class_from_rtt(rtt_ms: float | None) -> str:
    """Best-effort path class when agent does not supply one."""

    if rtt_ms is None:
        return PATH_CLASS_WAN
    if rtt_ms < 2.0:
        return PATH_CLASS_SAME_HOST
    if rtt_ms < 15.0:
        return PATH_CLASS_LAN
    return PATH_CLASS_WAN


def build_path_report(
    *,
    path_type: str | None = None,
    path_class: str | None = None,
    coordinator_rtt_ms: float | None = None,
    measurement_kind: str | None = None,
    p2p_rtt_ms: float | None = None,
    bandwidth_mbps: float | None = None,
    now: datetime | None = None,
) -> PathReport:
    kind = normalize_measurement_kind(measurement_kind)
    if coordinator_rtt_ms is not None and measurement_kind is None:
        kind = MEASUREMENT_MEASURED

    resolved_class = (
        normalize_path_class(path_class)
        if path_class
        else infer_path_class_from_rtt(coordinator_rtt_ms)
    )
    resolved_type = normalize_path_type(path_type)
    if resolved_class == PATH_CLASS_RELAY and resolved_type == PATH_TYPE_UNKNOWN:
        resolved_type = PATH_TYPE_RELAY

    freshness = now or datetime.now(UTC)
    if freshness.tzinfo is None:
        freshness = freshness.replace(tzinfo=UTC)

    return PathReport(
        path_type=resolved_type,
        path_class=resolved_class,
        coordinator_rtt_ms=coordinator_rtt_ms,
        measurement_kind=kind,
        freshness_at=freshness,
        p2p_rtt_ms=p2p_rtt_ms,
        bandwidth_mbps=bandwidth_mbps,
    )


def path_report_to_dict(report: PathReport) -> dict[str, Any]:
    return {
        "path_type": report.path_type,
        "path_class": report.path_class,
        "coordinator_rtt_ms": report.coordinator_rtt_ms,
        "measurement_kind": report.measurement_kind,
        "freshness_at": report.freshness_at.isoformat(),
        "p2p_rtt_ms": report.p2p_rtt_ms,
        "bandwidth_mbps": report.bandwidth_mbps,
        "is_measured": report.measurement_kind == MEASUREMENT_MEASURED,
    }


def record_path_metrics(
    *,
    room_id: str,
    peer_id: str,
    transport_mode: str,
    report: PathReport,
    health_state: str | None = None,
) -> None:
    """Update Prometheus series for path/RTT/health (safe to call on every heartbeat)."""

    labels = {
        "room_id": str(room_id),
        "peer_id": str(peer_id),
        "path_type": report.path_type,
        "path_class": report.path_class,
        "measurement_kind": report.measurement_kind,
    }
    PROVIDER_PATH_INFO.labels(**labels).set(1)

    if report.coordinator_rtt_ms is not None:
        PROVIDER_COORDINATOR_RTT.labels(
            room_id=str(room_id),
            path_class=report.path_class,
            measurement_kind=report.measurement_kind,
        ).observe(max(0.0, report.coordinator_rtt_ms) / 1000.0)

    PROVIDER_HEARTBEATS.labels(
        room_id=str(room_id),
        transport_mode=transport_mode or "unknown",
        path_class=report.path_class,
    ).inc()

    if health_state:
        for state in (
            "healthy",
            "degraded",
            "stale",
            "offline",
            "revoked",
            "incompatible",
            "claim_timeout",
        ):
            PROVIDER_HEALTH_STATE.labels(
                room_id=str(room_id),
                peer_id=str(peer_id),
                health_state=state,
            ).set(1.0 if state == health_state else 0.0)
