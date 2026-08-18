"""Mapping helpers from internal VPN models to room-facing API schemas."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from deepiri_zepgpu.database.models.vpn_models import (
    GpuShare,
    GpuShareState,
    Peer,
    VpnInvite,
    VpnNetwork,
)
from deepiri_zepgpu.rooms.capabilities import summarize_capabilities
from deepiri_zepgpu.rooms.models import (
    RoomConnectionConfigResponse,
    RoomCreateRequest,
    RoomGpuPoolSummary,
    RoomInviteResponse,
    RoomMemberResponse,
    RoomNodeCapabilitiesSummary,
    RoomNodeGpuResponse,
    RoomNodePathResponse,
    RoomNodeResponse,
    RoomResponse,
)
from deepiri_zepgpu.rooms.path_obs import MEASUREMENT_MEASURED
from deepiri_zepgpu.rooms.transport import (
    is_experimental_transport,
    requires_wireguard_udp,
    resolve_default_transport_mode,
)


def _enum_value(value: Any) -> str:
    """Return enum value if present, otherwise string form."""

    return value.value if hasattr(value, "value") else str(value)


def _uuid_value(value: Any) -> UUID:
    """Convert ORM string/UUID values into UUID objects for response schemas."""

    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _optional_uuid_value(value: Any) -> UUID | None:
    """Convert optional ORM string/UUID values into UUID objects."""

    if value is None:
        return None
    return _uuid_value(value)


def _network_transport_mode(network: VpnNetwork) -> str:
    return getattr(network, "transport_mode", None) or "wireguard"


def vpn_network_to_room_response(
    network: VpnNetwork,
    host_id: UUID | None = None,
) -> RoomResponse:
    """Convert an internal VpnNetwork into a room-facing response."""

    resolved_host_id = host_id if host_id is not None else getattr(network, "host_id", None)
    transport_mode = _network_transport_mode(network)

    return RoomResponse(
        id=_uuid_value(network.id),
        name=network.name,
        description=None,
        host_id=_optional_uuid_value(resolved_host_id),
        status="active" if network.is_active else "archived",
        transport_mode=transport_mode,
        transport_experimental=is_experimental_transport(transport_mode),
        requires_wireguard_udp=requires_wireguard_udp(transport_mode),
        created_at=network.created_at,
        updated_at=getattr(network, "updated_at", None),
    )


def peer_to_room_member_response(peer: Peer) -> RoomMemberResponse:
    """Convert an internal VPN peer into a room member response."""

    display_name = None
    if getattr(peer, "user", None) is not None:
        display_name = getattr(peer.user, "username", None) or getattr(peer.user, "email", None)

    return RoomMemberResponse(
        id=_uuid_value(peer.id),
        user_id=_optional_uuid_value(peer.user_id),
        display_name=display_name,
        status=_room_member_status(peer.online_status),
        joined_at=getattr(peer, "created_at", None),
        last_seen_at=peer.last_seen,
    )


def _peer_capabilities_summary(peer: Peer) -> RoomNodeCapabilitiesSummary | None:
    caps = getattr(peer, "capabilities_json", None)
    if not caps and not getattr(peer, "capabilities_reported_at", None):
        return None
    summary = summarize_capabilities(caps if isinstance(caps, dict) else None)
    reported = summary.get("reported_at") or getattr(peer, "capabilities_reported_at", None)
    return RoomNodeCapabilitiesSummary(
        gpu_count=int(summary.get("gpu_count") or 0),
        reported_at=reported,
        cuda_version=summary.get("cuda_version"),
        pytorch_version=summary.get("pytorch_version"),
        driver_version=summary.get("driver_version"),
        runtime=dict(summary.get("runtime") or {}),
        topology=dict(summary.get("topology") or {}),
    )


def _peer_path_response(peer: Peer) -> RoomNodePathResponse | None:
    path_type = getattr(peer, "path_type", None)
    path_class = getattr(peer, "path_class", None)
    rtt = getattr(peer, "coordinator_rtt_ms", None)
    kind = getattr(peer, "path_measurement_kind", None)
    freshness = getattr(peer, "path_freshness_at", None)
    if not any((path_type, path_class, rtt is not None, kind, freshness)):
        return None
    measurement_kind = kind or "estimated"
    return RoomNodePathResponse(
        path_type=path_type or "unknown",
        path_class=path_class or "wan",
        coordinator_rtt_ms=rtt,
        measurement_kind=measurement_kind,
        freshness_at=freshness,
        is_measured=measurement_kind == MEASUREMENT_MEASURED,
    )


def peer_to_room_node_response(peer: Peer) -> RoomNodeResponse:
    """Convert an internal VPN peer into a room node response."""

    room_gpu_shares = getattr(peer, "_room_gpu_shares", None)
    if room_gpu_shares is None:
        room_gpu_shares = getattr(peer, "gpu_shares", [])

    gpu_shares = list(room_gpu_shares or [])
    active_shares = [share for share in gpu_shares if share.is_active]

    return RoomNodeResponse(
        id=_uuid_value(peer.id),
        room_id=_uuid_value(peer.vpn_network_id),
        user_id=_uuid_value(peer.user_id),
        username=peer.user.username if peer.user else "",
        vpn_ip=peer.vpn_ip,
        status=_room_node_status(peer.online_status),
        is_gpu_host=peer.is_gpu_host,
        is_online=_room_node_status(peer.online_status) == "connected",
        last_seen=peer.last_seen,
        gpu_count=len(active_shares),
        available_gpu_count=sum(1 for share in active_shares if _enum_value(share.state) == "idle"),
        total_memory_mb=sum(share.total_memory_mb for share in active_shares),
        available_memory_mb=sum(share.available_memory_mb for share in active_shares),
        node_name=getattr(peer, "node_name", None),
        agent_version=getattr(peer, "agent_version", None),
        provider_mode=getattr(peer, "provider_mode", None),
        revoked_at=getattr(peer, "revoked_at", None),
        health_state=getattr(peer, "health_state", None),
        health_reason=getattr(peer, "health_reason", None),
        last_claim_at=getattr(peer, "last_claim_at", None),
        recent_failures=int(getattr(peer, "recent_failures", 0) or 0),
        capabilities=_peer_capabilities_summary(peer),
        path=_peer_path_response(peer),
    )


def gpu_share_to_room_node_gpu_response(share: GpuShare) -> RoomNodeGpuResponse:
    """Convert an internal GPU share into a room node GPU response."""

    return RoomNodeGpuResponse(
        id=_uuid_value(share.id),
        peer_id=_uuid_value(share.peer_id),
        room_id=_uuid_value(share.vpn_network_id),
        device_index=share.device_index,
        name=share.name,
        total_memory_mb=share.total_memory_mb,
        available_memory_mb=share.available_memory_mb,
        compute_capability=share.compute_capability,
        gpu_type=share.gpu_type,
        state=_enum_value(share.state),
        utilization_percent=share.utilization_percent,
        temperature_celsius=getattr(share, "temperature_celsius", None),
        power_watts=getattr(share, "power_watts", None),
        is_active=share.is_active,
        last_updated=_gpu_share_last_updated(share),
    )


def _gpu_share_peer_is_connected(share: GpuShare) -> bool:
    """Return whether a GPU share belongs to an online peer.

    Older tests and repository calls may provide shares without a loaded peer.
    Treat missing peer data as connected so existing behavior stays backward compatible.
    """

    peer = getattr(share, "peer", None)
    if peer is None:
        return True

    return _enum_value(peer.online_status) == "online"


def gpu_shares_to_room_pool_summary(
    room_id: UUID,
    shares: Sequence[GpuShare],
) -> RoomGpuPoolSummary:
    """Create a room GPU summary from GPU shares."""

    active_shares = [share for share in shares if share.is_active]
    connected_active_shares = [
        share for share in active_shares if _gpu_share_peer_is_connected(share)
    ]

    total_gpus = len(active_shares)
    allocated_gpus = sum(1 for share in active_shares if share.state == GpuShareState.ALLOCATED)
    available_gpus = sum(
        1 for share in connected_active_shares if share.state == GpuShareState.IDLE
    )

    total_memory_mb = sum(int(share.total_memory_mb or 0) for share in active_shares)
    available_memory_mb = sum(
        int(share.available_memory_mb or 0)
        for share in connected_active_shares
        if share.state == GpuShareState.IDLE
    )

    providers = sorted(
        {share.gpu_type for share in active_shares if getattr(share, "gpu_type", None)}
    )

    return RoomGpuPoolSummary(
        room_id=room_id,
        total_gpus=total_gpus,
        available_gpus=available_gpus,
        allocated_gpus=allocated_gpus,
        total_memory_mb=total_memory_mb,
        available_memory_mb=available_memory_mb,
        providers=providers,
    )


def build_invite_join_command(code: str, coordinator_url: str) -> str:
    """One-line provider join command for invite copy/UI."""

    return f"zepgpu-node join --invite {code} --coordinator {coordinator_url.rstrip('/')}"


def vpn_invite_to_room_invite_response(
    invite: VpnInvite,
    *,
    coordinator_url: str | None = None,
) -> RoomInviteResponse:
    """Convert an internal VPN invite into a room invite response."""

    from deepiri_zepgpu.config import settings

    url = (coordinator_url or settings.api.coordinator_public_url).rstrip("/")
    return RoomInviteResponse(
        id=_uuid_value(invite.id),
        room_id=_uuid_value(invite.vpn_network_id),
        code=invite.code,
        created_by=_uuid_value(invite.creator_id),
        expires_at=invite.expires_at,
        max_uses=invite.max_uses,
        use_count=invite.used_count,
        is_revoked=invite.is_revoked,
        created_at=invite.created_at,
        coordinator_url=url,
        join_command=build_invite_join_command(invite.code, url),
    )


def room_create_to_vpn_network_data(request: RoomCreateRequest) -> dict[str, Any]:
    """Convert a room create request into VpnNetworkRepository.create kwargs."""

    transport_mode = resolve_default_transport_mode(request.transport_mode)
    return {
        "name": request.name,
        "transport_mode": transport_mode,
    }


def peer_config_to_room_config_response(
    room_id: UUID,
    peer_id: UUID,
    config_text: str,
    filename: str | None = None,
    *,
    transport_mode: str = "wireguard",
) -> RoomConnectionConfigResponse:
    """Build a room-facing config response for a peer."""

    return RoomConnectionConfigResponse(
        room_id=_uuid_value(room_id),
        peer_id=_uuid_value(peer_id),
        config=config_text,
        filename=filename or f"room-{room_id}-peer-{peer_id}.conf",
        transport_mode=transport_mode,
        requires_wireguard_udp=requires_wireguard_udp(transport_mode),
    )


def _room_member_status(value: Any) -> str:
    status = _enum_value(value)
    if status == "online":
        return "connected"
    if status in {"offline", "awol"}:
        return "disconnected"
    return "pending"


def _room_node_status(value: Any) -> str:
    status = _enum_value(value)
    if status == "online":
        return "connected"
    if status == "offline":
        return "disconnected"
    if status == "awol":
        return "awol"
    return "pending"


def _gpu_share_last_updated(share: GpuShare) -> datetime:
    value = getattr(share, "last_updated", None)
    if isinstance(value, datetime):
        return value

    value = getattr(share, "updated_at", None)
    if isinstance(value, datetime):
        return value

    return datetime.now(UTC)
