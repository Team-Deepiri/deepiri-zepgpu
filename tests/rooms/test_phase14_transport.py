"""Phase 14: transport modes, capability inventory, health, path, legacy router guard."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from deepiri_zepgpu.rooms.capabilities import (
    UNAVAILABLE,
    capabilities_are_stale,
    normalize_capabilities,
)
from deepiri_zepgpu.rooms.health import (
    HEALTH_CLAIM_TIMEOUT,
    HEALTH_DEGRADED,
    HEALTH_HEALTHY,
    HEALTH_INCOMPATIBLE,
    HEALTH_OFFLINE,
    HEALTH_REVOKED,
    HEALTH_STALE,
    assess_provider_health,
)
from deepiri_zepgpu.rooms.mappers import (
    room_create_to_vpn_network_data,
    vpn_network_to_room_response,
)
from deepiri_zepgpu.rooms.models import RoomCreateRequest
from deepiri_zepgpu.rooms.path_obs import (
    MEASUREMENT_MEASURED,
    PATH_CLASS_LAN,
    PATH_TYPE_DIRECT,
    build_path_report,
)
from deepiri_zepgpu.rooms.transport import (
    InvalidTransportModeError,
    allows_legacy_pickle_router,
    normalize_transport_mode,
    requires_wireguard_udp,
    resolve_default_transport_mode,
)
from deepiri_zepgpu.vpn.legacy_router_guard import (
    LegacyRouterForbiddenError,
    assert_legacy_pickle_router_allowed,
    assert_not_called_from_training,
)
from deepiri_zepgpu.vpn.task_router import TaskRouter


def test_normalize_transport_modes() -> None:
    assert normalize_transport_mode("WireGuard") == "wireguard"
    assert normalize_transport_mode("DIALOUT") == "dialout"
    assert normalize_transport_mode("overlay") == "overlay"
    with pytest.raises(InvalidTransportModeError):
        normalize_transport_mode("quic")


def test_default_new_room_transport_is_dialout() -> None:
    assert resolve_default_transport_mode(None) == "dialout"
    assert resolve_default_transport_mode("wireguard") == "wireguard"


def test_room_create_maps_transport_mode() -> None:
    data = room_create_to_vpn_network_data(RoomCreateRequest(name="r1", transport_mode=None))
    assert data["transport_mode"] == "dialout"
    data_wg = room_create_to_vpn_network_data(
        RoomCreateRequest(name="r2", transport_mode="wireguard")
    )
    assert data_wg["transport_mode"] == "wireguard"


def test_vpn_network_response_exposes_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Net:
        id = uuid4()
        name = "n"
        is_active = True
        host_id = None
        transport_mode = "dialout"
        created_at = datetime.now(UTC)
        updated_at = None

    resp = vpn_network_to_room_response(_Net())  # type: ignore[arg-type]
    assert resp.transport_mode == "dialout"
    assert resp.requires_wireguard_udp is False
    assert resp.transport_experimental is False


def test_wireguard_requires_udp_dialout_does_not() -> None:
    assert requires_wireguard_udp("wireguard") is True
    assert requires_wireguard_udp("dialout") is False


def test_legacy_pickle_quarantined_to_wireguard() -> None:
    assert allows_legacy_pickle_router("wireguard") is True
    assert allows_legacy_pickle_router("dialout") is False
    assert_legacy_pickle_router_allowed("wireguard")
    with pytest.raises(LegacyRouterForbiddenError):
        assert_legacy_pickle_router_allowed("dialout")


def test_task_router_does_not_accept_arbitrary_callable_payloads() -> None:
    signature = inspect.signature(TaskRouter.execute_on_peer)

    assert "func" not in signature.parameters
    assert "args" not in signature.parameters
    assert "kwargs" not in signature.parameters
    assert "serialized_func" not in signature.parameters


def test_training_caller_guard() -> None:
    import deepiri_zepgpu.training as training_pkg

    # Direct call from test module is allowed.
    assert_not_called_from_training()

    with pytest.raises(LegacyRouterForbiddenError):
        training_pkg._probe_legacy_router_guard()


def test_capability_normalization_marks_unavailable() -> None:
    caps = normalize_capabilities(
        {
            "gpus": [
                {
                    "device_index": 0,
                    "total_memory_mb": 8192,
                    "available_memory_mb": 7000,
                }
            ],
            "runtime": {"cuda_version": "12.1"},
            "topology": {},
        }
    )
    assert caps["gpu_count"] == 1
    assert caps["gpus"][0]["temperature_celsius"] == UNAVAILABLE
    assert caps["runtime"]["pytorch_version"] == UNAVAILABLE
    assert caps["topology"]["nvlink"] == UNAVAILABLE
    assert "reported_at" in caps


def test_capability_stale() -> None:
    now = datetime.now(UTC)
    assert capabilities_are_stale(None, now=now) is True
    assert capabilities_are_stale(now - timedelta(minutes=1), now=now) is False
    assert capabilities_are_stale(now - timedelta(minutes=30), now=now) is True


def test_health_state_transitions() -> None:
    now = datetime.now(UTC)
    healthy = assess_provider_health(
        online_status="online",
        last_seen=now,
        capabilities_reported_at=now,
        recent_failures=0,
        now=now,
    )
    assert healthy.state == HEALTH_HEALTHY

    revoked = assess_provider_health(
        online_status="online",
        last_seen=now,
        revoked_at=now,
        now=now,
    )
    assert revoked.state == HEALTH_REVOKED

    offline = assess_provider_health(
        online_status="offline",
        last_seen=now - timedelta(hours=1),
        now=now,
    )
    assert offline.state == HEALTH_OFFLINE

    stale = assess_provider_health(
        online_status="awol",
        last_seen=now - timedelta(minutes=5),
        now=now,
    )
    assert stale.state == HEALTH_STALE

    degraded = assess_provider_health(
        online_status="online",
        last_seen=now,
        capabilities_reported_at=now,
        recent_failures=5,
        now=now,
    )
    assert degraded.state == HEALTH_DEGRADED

    incompatible = assess_provider_health(
        online_status="online",
        last_seen=now,
        capabilities_reported_at=now,
        agent_version="0.1.0",
        min_compatible_agent_version="1.0.0",
        now=now,
    )
    assert incompatible.state == HEALTH_INCOMPATIBLE

    claim_timeout = assess_provider_health(
        online_status="online",
        last_seen=now,
        capabilities_reported_at=now,
        claim_timed_out=True,
        now=now,
    )
    assert claim_timeout.state == HEALTH_CLAIM_TIMEOUT


def test_path_report_measured_vs_estimated() -> None:
    measured = build_path_report(
        path_type=PATH_TYPE_DIRECT,
        coordinator_rtt_ms=8.0,
        measurement_kind=MEASUREMENT_MEASURED,
    )
    assert measured.path_class == PATH_CLASS_LAN
    assert measured.measurement_kind == MEASUREMENT_MEASURED

    estimated = build_path_report(path_type=None, coordinator_rtt_ms=None)
    assert estimated.path_type == "unknown"
    assert estimated.measurement_kind == "estimated"


def test_training_package_does_not_import_task_router() -> None:
    import ast
    from pathlib import Path

    training_root = Path(__file__).resolve().parents[2] / "deepiri_zepgpu" / "training"
    assert training_root.is_dir()
    for path in training_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "task_router" not in alias.name
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "task_router" not in mod
                for alias in node.names:
                    assert alias.name != "TaskRouter"
