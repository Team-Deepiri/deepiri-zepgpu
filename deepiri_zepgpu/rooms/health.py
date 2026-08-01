"""Structured provider health states and human-readable reasons."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from deepiri_zepgpu.database.models.vpn_models import PeerOnlineStatus
from deepiri_zepgpu.rooms.capabilities import capabilities_are_stale

HEALTH_HEALTHY: Final = "healthy"
HEALTH_DEGRADED: Final = "degraded"
HEALTH_STALE: Final = "stale"
HEALTH_OFFLINE: Final = "offline"
HEALTH_REVOKED: Final = "revoked"
HEALTH_INCOMPATIBLE: Final = "incompatible"
HEALTH_CLAIM_TIMEOUT: Final = "claim_timeout"

VALID_HEALTH_STATES: Final = frozenset(
    {
        HEALTH_HEALTHY,
        HEALTH_DEGRADED,
        HEALTH_STALE,
        HEALTH_OFFLINE,
        HEALTH_REVOKED,
        HEALTH_INCOMPATIBLE,
        HEALTH_CLAIM_TIMEOUT,
    }
)

# Soft thresholds for degraded / claim-timeout heuristics.
RECENT_FAILURE_DEGRADED_THRESHOLD: Final = 3
CLAIM_TIMEOUT_AFTER: Final = timedelta(minutes=5)
DEFAULT_COMPATIBLE_AGENT_PREFIX: Final = "0."


@dataclass(frozen=True)
class HealthAssessment:
    state: str
    reason: str


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def assess_provider_health(
    *,
    online_status: Any,
    last_seen: datetime | None,
    revoked_at: datetime | None = None,
    agent_version: str | None = None,
    capabilities_reported_at: datetime | None = None,
    recent_failures: int = 0,
    last_claim_at: datetime | None = None,
    claim_timed_out: bool = False,
    min_compatible_agent_version: str | None = None,
    heartbeat_timeout_seconds: int = 90,
    now: datetime | None = None,
) -> HealthAssessment:
    """Derive health_state + health_reason from peer observability fields."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)

    if revoked_at is not None:
        return HealthAssessment(HEALTH_REVOKED, "Provider membership has been revoked")

    if claim_timed_out:
        return HealthAssessment(
            HEALTH_CLAIM_TIMEOUT,
            "Provider failed to claim or start an assignment before the timeout",
        )

    if last_claim_at is not None:
        claim_ts = last_claim_at if last_claim_at.tzinfo else last_claim_at.replace(tzinfo=UTC)
        if (current - claim_ts) > CLAIM_TIMEOUT_AFTER and _enum_value(online_status) != "online":
            return HealthAssessment(
                HEALTH_CLAIM_TIMEOUT,
                "Last claim is older than the claim-timeout window while provider is offline",
            )

    if min_compatible_agent_version and agent_version:
        if not _version_compatible(agent_version, min_compatible_agent_version):
            return HealthAssessment(
                HEALTH_INCOMPATIBLE,
                f"Agent version {agent_version} is incompatible "
                f"(requires >= {min_compatible_agent_version})",
            )

    status = _enum_value(online_status)
    if status in {"offline", PeerOnlineStatus.OFFLINE.value}:
        return HealthAssessment(HEALTH_OFFLINE, "Provider is offline (no recent heartbeat)")

    if status in {"awol", PeerOnlineStatus.AWOL.value}:
        return HealthAssessment(
            HEALTH_STALE,
            f"Heartbeat timed out (no update within {heartbeat_timeout_seconds}s)",
        )

    if last_seen is not None:
        seen = last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=UTC)
        if (current - seen).total_seconds() > heartbeat_timeout_seconds:
            return HealthAssessment(
                HEALTH_STALE,
                f"Last heartbeat is older than {heartbeat_timeout_seconds}s",
            )

    if capabilities_are_stale(capabilities_reported_at, now=current):
        return HealthAssessment(
            HEALTH_STALE,
            "Capability inventory is stale or missing",
        )

    if recent_failures >= RECENT_FAILURE_DEGRADED_THRESHOLD:
        return HealthAssessment(
            HEALTH_DEGRADED,
            f"Recent assignment failures ({recent_failures}) indicate degraded reliability",
        )

    if status == "online":
        return HealthAssessment(HEALTH_HEALTHY, "Provider is online with fresh heartbeat")

    return HealthAssessment(HEALTH_OFFLINE, f"Provider status is {status}")


def _version_compatible(agent_version: str, minimum: str) -> bool:
    """Loose major.minor compatibility check (string prefix / tuple compare)."""

    def parts(v: str) -> tuple[int, ...]:
        nums: list[int] = []
        for piece in v.split("."):
            digits = "".join(ch for ch in piece if ch.isdigit())
            if digits:
                nums.append(int(digits))
            else:
                break
        return tuple(nums) or (0,)

    return parts(agent_version) >= parts(minimum)
