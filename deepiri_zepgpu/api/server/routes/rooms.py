"""Room-facing API routes backed by existing VPN network functionality."""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_db_session, get_required_user
from deepiri_zepgpu.api.server.room_events import emit_room_event
from deepiri_zepgpu.api.server.websocket_manager import manager
from deepiri_zepgpu.database.models import User
from deepiri_zepgpu.database.models.vpn_models import Peer, PeerOnlineStatus, VpnInvite, VpnNetwork
from deepiri_zepgpu.rooms.mappers import (
    gpu_share_to_room_node_gpu_response,
    gpu_shares_to_room_pool_summary,
    peer_config_to_room_config_response,
    peer_to_room_member_response,
    peer_to_room_node_response,
    room_create_to_vpn_network_data,
    vpn_invite_to_room_invite_response,
    vpn_network_to_room_response,
)
from deepiri_zepgpu.rooms.models import (
    RoomConnectionConfigResponse,
    RoomCreateRequest,
    RoomGpuPoolSummary,
    RoomInviteCreateRequest,
    RoomInviteResponse,
    RoomJoinRequest,
    RoomJoinResponse,
    RoomMemberResponse,
    RoomNodeGpuResponse,
    RoomNodeHeartbeatRequest,
    RoomNodeResponse,
    RoomResponse,
)
from deepiri_zepgpu.vpn.config import vpn_settings
from deepiri_zepgpu.vpn.crypto import encrypt_value
from deepiri_zepgpu.vpn.keygen import generate_keypair
from deepiri_zepgpu.vpn.repositories import (
    GpuShareRepository,
    PeerRepository,
    VpnInviteRepository,
    VpnNetworkRepository,
)
from deepiri_zepgpu.vpn.wg_config import allocate_vpn_ip, generate_peer_config

router = APIRouter(prefix="/rooms", tags=["GPU Rooms"])


async def _ensure_room_member(
    network_repo: VpnNetworkRepository,
    user_id: str,
    room_id: str,
) -> VpnNetwork:
    """Ensure the current user belongs to the underlying VPN network."""

    room = await network_repo.get_by_id(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    user_rooms = await network_repo.list_user_networks(user_id)
    if not any(str(user_room.id) == str(room_id) for user_room in user_rooms):
        raise HTTPException(status_code=403, detail="You do not have access to this room")

    return room


async def _ensure_room_host(
    peer_repo: PeerRepository,
    user_id: str,
    room_id: str,
) -> None:
    """Ensure the current user is the room host.

    Until rooms have a first-class host field, the relay peer created with
    the room is treated as the host.
    """

    peers = await peer_repo.get_by_network(room_id)
    for peer in peers:
        if str(peer.user_id) == str(user_id) and peer.is_relay:
            return

    raise HTTPException(
        status_code=403,
        detail="Only the room host or an admin can perform this action",
    )


def _expires_at_to_days(expires_at: datetime | None) -> int:
    """Convert an optional expires_at timestamp into repository expires_in_days."""

    if expires_at is None:
        return 7

    now = datetime.now(expires_at.tzinfo or UTC)
    delta_seconds = (expires_at - now).total_seconds()
    if delta_seconds <= 0:
        raise HTTPException(status_code=400, detail="Invite expiration must be in the future")

    return max(1, ceil(delta_seconds / 86_400))


async def _get_invite_by_id(db: AsyncSession, invite_id: str) -> VpnInvite | None:
    """Fetch a VPN invite by ID."""

    result = await db.execute(select(VpnInvite).where(VpnInvite.id == invite_id))
    return result.scalar_one_or_none()


async def _list_room_invites(db: AsyncSession, room_id: str) -> list[VpnInvite]:
    """List invites for a room."""

    result = await db.execute(
        select(VpnInvite)
        .where(VpnInvite.vpn_network_id == room_id)
        .order_by(VpnInvite.created_at.desc())
    )
    return list(result.scalars().all())


async def _get_current_user_peer(
    peer_repo: PeerRepository,
    user_id: str,
    room_id: str,
) -> Peer | None:
    """Find the current user's peer in a room."""

    peers = await peer_repo.get_by_network(room_id)
    for peer in peers:
        if str(peer.user_id) == str(user_id):
            return peer
    return None


async def _get_room_host_id(peer_repo: PeerRepository, room_id: str) -> UUID | None:
    """Return the relay peer owner's user ID for a room."""
    peers = await peer_repo.get_by_network(room_id)
    for peer in peers:
        if peer.is_relay:
            return UUID(str(peer.user_id))
    return None


@router.post("", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
async def create_room(
    data: RoomCreateRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> RoomResponse:
    """Create a GPU room backed by a VPN network."""

    network_repo = VpnNetworkRepository(db)
    relay_endpoint = vpn_settings.relay_host
    private_key, public_key = generate_keypair()

    room_data = room_create_to_vpn_network_data(data)
    network = await network_repo.create(
        **room_data,
        relay_endpoint=relay_endpoint,
        relay_public_key=public_key,
        private_key_encrypted=encrypt_value(private_key),
    )

    peer_repo = PeerRepository(db)
    peer_private_key, peer_public_key = generate_keypair()
    first_ip = allocate_vpn_ip(network.cidr, set())

    await peer_repo.create(
        user_id=str(user.id),
        vpn_network_id=str(network.id),
        wireguard_public_key=peer_public_key,
        vpn_ip=first_ip,
        private_key_encrypted=encrypt_value(peer_private_key),
        is_gpu_host=False,
        is_relay=True,
    )

    return vpn_network_to_room_response(network, host_id=UUID(str(user.id)))


@router.get("", response_model=list[RoomResponse])
async def list_rooms(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[RoomResponse]:
    """List rooms available to the current user."""

    network_repo = VpnNetworkRepository(db)
    networks = await network_repo.list_user_networks(str(user.id))
    return [vpn_network_to_room_response(network) for network in networks]


@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(
    room_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> RoomResponse:
    """Get room details."""

    network_repo = VpnNetworkRepository(db)
    room = await _ensure_room_member(network_repo, str(user.id), room_id)
    peer_repo = PeerRepository(db)
    host_id = await _get_room_host_id(peer_repo, room_id)
    return vpn_network_to_room_response(room, host_id=host_id)


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Archive/deactivate a room without hard-deleting peer history."""

    network_repo = VpnNetworkRepository(db)
    room = await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    await _ensure_room_host(peer_repo, str(user.id), room_id)

    room.is_active = False
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{room_id}/members", response_model=list[RoomMemberResponse])
async def list_room_members(
    room_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[RoomMemberResponse]:
    """List room members backed by VPN peers."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    peers = await peer_repo.get_by_network(room_id)
    return [peer_to_room_member_response(peer) for peer in peers]


@router.delete("/{room_id}/members/me", status_code=status.HTTP_204_NO_CONTENT)
async def leave_room(
    room_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Remove the current user's peer membership from a room."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    peer = await _get_current_user_peer(peer_repo, str(user.id), room_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Room membership not found")
    if peer.is_relay:
        raise HTTPException(
            status_code=409,
            detail="The room host cannot leave; archive the room instead",
        )

    member_payload = peer_to_room_member_response(peer).model_dump(mode="json")
    gpu_repo = GpuShareRepository(db)
    await gpu_repo.deactivate_peer_gpus(str(peer.id))
    if not await peer_repo.delete(str(peer.id)):
        raise HTTPException(status_code=404, detail="Room membership not found")

    await emit_room_event(room_id, "room_member_left", member_payload)
    await manager.unsubscribe_user_from_room(str(user.id), room_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{room_id}/nodes", response_model=list[RoomNodeResponse])
async def list_room_nodes(
    room_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[RoomNodeResponse]:
    """List room nodes backed by VPN peers."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    gpu_repo = GpuShareRepository(db)

    peers = await peer_repo.get_by_network(room_id)
    peers = await _attach_room_gpu_shares(gpu_repo, room_id, peers)

    return [peer_to_room_node_response(peer) for peer in peers]


@router.get("/{room_id}/nodes/{peer_id}", response_model=RoomNodeResponse)
async def get_room_node(
    room_id: str,
    peer_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> RoomNodeResponse:
    """Get one room node."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    peer = await peer_repo.get_by_id(peer_id)
    if not peer or str(peer.vpn_network_id) != str(room_id):
        raise HTTPException(status_code=404, detail="Node not found")

    gpu_repo = GpuShareRepository(db)
    shares = await gpu_repo.list_by_peer(peer_id)
    peer._room_gpu_shares = shares  # type: ignore[attr-defined]

    return peer_to_room_node_response(peer)


@router.post("/{room_id}/nodes/{peer_id}/heartbeat", response_model=RoomNodeResponse)
async def room_node_heartbeat(
    room_id: str,
    peer_id: str,
    data: RoomNodeHeartbeatRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> RoomNodeResponse:
    """Update room node heartbeat and GPU metrics."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    peer = await peer_repo.get_by_id(peer_id)
    if not peer or str(peer.vpn_network_id) != str(room_id):
        raise HTTPException(status_code=404, detail="Node not found")

    if str(peer.user_id) != str(user.id):
        raise HTTPException(status_code=403, detail="You cannot update this node")

    was_online = peer.online_status == PeerOnlineStatus.ONLINE

    updated_peer = await peer_repo.heartbeat(
        peer_id=peer_id,
        is_online=data.is_online,
        endpoint=data.endpoint,
        mark_gpu_host=bool(data.gpu_status),
    )
    if not updated_peer:
        raise HTTPException(status_code=404, detail="Node not found")

    gpu_repo = GpuShareRepository(db)
    for gpu in data.gpu_status:
        await gpu_repo.upsert(
            peer_id=peer_id,
            vpn_network_id=room_id,
            gpu_data=gpu.model_dump(),
        )

    refreshed_peer = await peer_repo.get_by_id(peer_id)
    if not refreshed_peer:
        raise HTTPException(status_code=404, detail="Node not found")

    shares = await gpu_repo.list_by_peer(peer_id)
    room_shares = [share for share in shares if str(share.vpn_network_id) == str(room_id)]
    refreshed_peer._room_gpu_shares = room_shares  # type: ignore[attr-defined]

    node_payload = peer_to_room_node_response(refreshed_peer).model_dump(mode="json")
    if data.is_online and not was_online:
        await emit_room_event(room_id, "room_node_online", node_payload)
    elif not data.is_online and was_online:
        await emit_room_event(room_id, "room_node_offline", node_payload)
    elif data.is_online:
        await emit_room_event(room_id, "room_node_online", node_payload)

    if data.gpu_status:
        await emit_room_event(
            room_id,
            "room_gpu_update",
            {
                "peer_id": peer_id,
                "gpus": [
                    gpu_share_to_room_node_gpu_response(share).model_dump(mode="json")
                    for share in room_shares
                ],
            },
        )

    return peer_to_room_node_response(refreshed_peer)


@router.get("/{room_id}/nodes/{peer_id}/gpus", response_model=list[RoomNodeGpuResponse])
async def list_room_node_gpus(
    room_id: str,
    peer_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[RoomNodeGpuResponse]:
    """List GPUs reported by one room node."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    peer = await peer_repo.get_by_id(peer_id)
    if not peer or str(peer.vpn_network_id) != str(room_id):
        raise HTTPException(status_code=404, detail="Node not found")

    gpu_repo = GpuShareRepository(db)
    shares = await gpu_repo.list_by_peer(peer_id)
    room_shares = [share for share in shares if str(share.vpn_network_id) == str(room_id)]

    return [gpu_share_to_room_node_gpu_response(share) for share in room_shares]


@router.get("/{room_id}/gpus", response_model=list[RoomNodeGpuResponse])
async def list_room_gpus(
    room_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[RoomNodeGpuResponse]:
    """List every GPU share in a room in a single request."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    gpu_repo = GpuShareRepository(db)
    shares = await gpu_repo.list_by_network(room_id)

    return [gpu_share_to_room_node_gpu_response(share) for share in shares]


@router.get("/{room_id}/gpu-pool", response_model=RoomGpuPoolSummary)
async def get_room_gpu_pool(
    room_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> RoomGpuPoolSummary:
    """Get GPU pool summary for a room."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    gpu_repo = GpuShareRepository(db)
    shares = await gpu_repo.list_by_network(room_id)
    return gpu_shares_to_room_pool_summary(UUID(str(room_id)), shares)


@router.post(
    "/{room_id}/invites",
    response_model=RoomInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_room_invite(
    room_id: str,
    data: RoomInviteCreateRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> RoomInviteResponse:
    """Create a room invite backed by VpnInvite."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    await _ensure_room_host(peer_repo, str(user.id), room_id)

    invite_repo = VpnInviteRepository(db)
    invite = await invite_repo.create(
        creator_id=str(user.id),
        vpn_network_id=room_id,
        max_uses=data.max_uses,
        expires_in_days=_expires_at_to_days(data.expires_at),
    )

    return vpn_invite_to_room_invite_response(invite)


@router.get("/{room_id}/invites", response_model=list[RoomInviteResponse])
async def list_room_invites(
    room_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[RoomInviteResponse]:
    """List active invites for a room."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    await _ensure_room_host(peer_repo, str(user.id), room_id)

    invites = await _list_room_invites(db, room_id)
    active_invites = [
        invite
        for invite in invites
        if not invite.is_revoked
        and invite.used_count < invite.max_uses
        and (invite.expires_at is None or invite.expires_at > datetime.now(UTC))
    ]

    return [vpn_invite_to_room_invite_response(invite) for invite in active_invites]


@router.delete("/{room_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_room_invite(
    room_id: str,
    invite_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Revoke a room invite."""

    network_repo = VpnNetworkRepository(db)
    await _ensure_room_member(network_repo, str(user.id), room_id)

    invite = await _get_invite_by_id(db, invite_id)
    if not invite or str(invite.vpn_network_id) != str(room_id):
        raise HTTPException(status_code=404, detail="Invite not found")

    peer_repo = PeerRepository(db)
    try:
        await _ensure_room_host(peer_repo, str(user.id), room_id)
    except HTTPException:
        if str(invite.creator_id) != str(user.id):
            raise HTTPException(
                status_code=403,
                detail="Only the room host or an admin can perform this action",
            ) from None

    invite_repo = VpnInviteRepository(db)
    success = await invite_repo.revoke(invite_id)
    if not success:
        raise HTTPException(status_code=404, detail="Invite not found")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/join", response_model=RoomJoinResponse)
async def join_room(
    data: RoomJoinRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> RoomJoinResponse:
    """Join a room using an invite code."""

    invite_repo = VpnInviteRepository(db)
    invite = await invite_repo.get_by_code(data.invite_code)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    if invite.is_revoked:
        raise HTTPException(status_code=410, detail="Invite has been revoked")
    if invite.used_count >= invite.max_uses:
        raise HTTPException(status_code=410, detail="Invite usage limit reached")
    if invite.expires_at and datetime.now(invite.expires_at.tzinfo or UTC) > invite.expires_at:
        raise HTTPException(status_code=410, detail="Invite has expired")

    network_repo = VpnNetworkRepository(db)
    room = await network_repo.get_by_id(str(invite.vpn_network_id))
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    peer_repo = PeerRepository(db)
    existing_peer = await _get_current_user_peer(peer_repo, str(user.id), str(room.id))
    if existing_peer:
        raise HTTPException(status_code=409, detail="User has already joined this room")

    peers_existing = await peer_repo.get_by_network(str(room.id))
    used_ips = {peer.vpn_ip for peer in peers_existing}
    vpn_ip = allocate_vpn_ip(room.cidr, used_ips)

    private_key, public_key = generate_keypair()
    peer = await peer_repo.create(
        user_id=str(user.id),
        vpn_network_id=str(room.id),
        wireguard_public_key=public_key,
        vpn_ip=vpn_ip,
        private_key_encrypted=encrypt_value(private_key),
        is_gpu_host=False,
    )

    await invite_repo.use(invite)

    member = peer_to_room_member_response(peer)
    await emit_room_event(
        str(room.id),
        "room_member_joined",
        member.model_dump(mode="json"),
    )

    return RoomJoinResponse(
        room=vpn_network_to_room_response(room),
        member=member,
        config_available=True,
    )


@router.get("/{room_id}/config", response_model=RoomConnectionConfigResponse)
async def get_room_config(
    room_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
) -> RoomConnectionConfigResponse:
    """Return WireGuard/client config for the current user in a room."""

    network_repo = VpnNetworkRepository(db)
    room = await _ensure_room_member(network_repo, str(user.id), room_id)

    peer_repo = PeerRepository(db)
    peer = await _get_current_user_peer(peer_repo, str(user.id), room_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Room config is not available yet")

    private_key = await peer_repo.get_private_key(peer)
    if not private_key:
        raise HTTPException(status_code=404, detail="Room config is not available yet")

    config_text = generate_peer_config(
        vpn_ip=peer.vpn_ip,
        private_key=private_key,
        relay_public_key=room.relay_public_key or "",
        relay_endpoint=f"{room.relay_endpoint}:{room.listen_port}",
    )

    return peer_config_to_room_config_response(
        room_id=UUID(str(room_id)),
        peer_id=UUID(str(peer.id)),
        config_text=config_text,
    )


async def _attach_room_gpu_shares(
    gpu_repo: GpuShareRepository,
    room_id: str,
    peers: list[Peer],
) -> list[Peer]:
    """Attach room GPU shares to peers without using Peer.gpu_shares eager loading."""

    shares = await gpu_repo.list_by_network(room_id)
    shares_by_peer: dict[str, list] = {}

    for share in shares:
        shares_by_peer.setdefault(str(share.peer_id), []).append(share)

    for peer in peers:
        peer._room_gpu_shares = shares_by_peer.get(str(peer.id), [])  # type: ignore[attr-defined]

    return peers
