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
from deepiri_zepgpu.rooms.models import (
    RoomConnectionConfigResponse,
    RoomCreateRequest,
    RoomGpuPoolSummary,
    RoomInviteResponse,
    RoomMemberResponse,
    RoomNodeGpuResponse,
    RoomNodeResponse,
    RoomResponse,
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


def vpn_network_to_room_response(
    network: VpnNetwork,
    host_id: UUID | None = None,
) -> RoomResponse:
    """Convert an internal VpnNetwork into a room-facing response."""

    return RoomResponse(
        id=_uuid_value(network.id),
        name=network.name,
        description=None,
        host_id=_optional_uuid_value(host_id),
        status="active" if network.is_active else "archived",
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


def peer_to_room_node_response(peer: Peer) -> RoomNodeResponse:
    """Convert an internal VPN peer into a room node response."""

    gpu_shares = list(getattr(peer, "gpu_shares", []) or [])
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


def vpn_invite_to_room_invite_response(invite: VpnInvite) -> RoomInviteResponse:
    """Convert an internal VPN invite into a room invite response."""

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
    )


def room_create_to_vpn_network_data(request: RoomCreateRequest) -> dict[str, Any]:
    """Convert a room create request into VpnNetworkRepository.create kwargs."""

    return {
        "name": request.name,
    }


def peer_config_to_room_config_response(
    room_id: UUID,
    peer_id: UUID,
    config_text: str,
    filename: str | None = None,
) -> RoomConnectionConfigResponse:
    """Build a room-facing config response for a peer."""

    return RoomConnectionConfigResponse(
        room_id=_uuid_value(room_id),
        peer_id=_uuid_value(peer_id),
        config=config_text,
        filename=filename or f"room-{room_id}-peer-{peer_id}.conf",
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
