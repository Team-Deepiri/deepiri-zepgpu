"""Mapping helpers from internal VPN models to room-facing API schemas."""

from __future__ import annotations

from collections.abc import Sequence
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
    RoomResponse,
)


def _enum_value(value: Any) -> str:
    """Return enum value if present, otherwise string form."""

    return value.value if hasattr(value, "value") else str(value)


def vpn_network_to_room_response(
    network: VpnNetwork,
    host_id: UUID | None = None,
) -> RoomResponse:
    """Convert an internal VpnNetwork into a room-facing response."""

    return RoomResponse(
        id=network.id,
        name=network.name,
        description=None,
        host_id=host_id,
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
        id=peer.id,
        user_id=peer.user_id,
        display_name=display_name,
        status=_room_member_status(peer.online_status),
        joined_at=getattr(peer, "created_at", None),
        last_seen_at=peer.last_seen,
    )


def gpu_shares_to_room_pool_summary(
    room_id: UUID,
    shares: Sequence[GpuShare],
) -> RoomGpuPoolSummary:
    """Create a room GPU summary from GPU shares."""

    active_shares = [share for share in shares if share.is_active]

    total_gpus = len(active_shares)
    allocated_gpus = sum(1 for share in active_shares if share.state == GpuShareState.ALLOCATED)
    available_gpus = sum(1 for share in active_shares if share.state == GpuShareState.IDLE)

    total_memory_mb = sum(int(share.total_memory_mb or 0) for share in active_shares)
    available_memory_mb = sum(int(share.available_memory_mb or 0) for share in active_shares)

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
        id=invite.id,
        room_id=invite.vpn_network_id,
        code=invite.code,
        created_by=invite.creator_id,
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
        room_id=room_id,
        peer_id=peer_id,
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
