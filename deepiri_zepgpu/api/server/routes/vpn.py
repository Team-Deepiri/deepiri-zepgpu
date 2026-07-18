"""VPN and GPU sharing network API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_db_session, get_required_user
from deepiri_zepgpu.compute_ledger.keys import generate_keypair as generate_ledger_keypair
from deepiri_zepgpu.compute_ledger.service import LedgerService
from deepiri_zepgpu.config import settings as app_settings
from deepiri_zepgpu.database.models import User
from deepiri_zepgpu.database.models.vpn_models import (
    GpuShareState,
    PeerOnlineStatus,
)
from deepiri_zepgpu.vpn.config import vpn_settings
from deepiri_zepgpu.vpn.crypto import encrypt_value
from deepiri_zepgpu.vpn.keygen import generate_keypair
from deepiri_zepgpu.vpn.models import (
    FriendListResponse,
    FriendRequest,
    FriendResponse,
    GpuPoolSummary,
    GpuShareResponse,
    InviteResponse,
    JoinNetworkRequest,
    NetworkInviteRequest,
    PeerHeartbeatRequest,
    PeerRegisterRequest,
    PeerResponse,
    VpnConfigResponse,
    VpnNetworkCreate,
    VpnNetworkResponse,
)
from deepiri_zepgpu.vpn.pool_sync import get_registered_gpu_pool, refresh_gpu_pool_from_db
from deepiri_zepgpu.vpn.repositories import (
    FriendshipRepository,
    GpuShareRepository,
    PeerRepository,
    VpnInviteRepository,
    VpnNetworkRepository,
)
from deepiri_zepgpu.vpn.wg_config import allocate_vpn_ip, generate_peer_config

router = APIRouter(prefix="/vpn", tags=["VPN"])


async def _ensure_network_member(
    network_repo: VpnNetworkRepository,
    user_id: str,
    network_id: str,
):
    network = await network_repo.get_by_id(network_id)
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    nets = await network_repo.list_user_networks(user_id)
    if not any(str(n.id) == network_id for n in nets):
        raise HTTPException(status_code=403, detail="Not a member of this VPN network")
    return network


@router.post("/networks", response_model=VpnNetworkResponse)
async def create_vpn_network(
    data: VpnNetworkCreate,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    repo = VpnNetworkRepository(db)
    relay_endpoint = data.relay_endpoint or vpn_settings.relay_host
    private_key, public_key = generate_keypair()
    network = await repo.create(
        name=data.name,
        cidr=data.cidr,
        listen_port=data.listen_port,
        relay_endpoint=relay_endpoint,
        relay_public_key=public_key,
        private_key_encrypted=encrypt_value(private_key),
    )
    peer_repo = PeerRepository(db)
    peer_priv, peer_pub = generate_keypair()
    ledger_priv, ledger_pub = generate_ledger_keypair()
    used: set[str] = set()
    first_ip = allocate_vpn_ip(network.cidr, used)
    await peer_repo.create(
        user_id=str(user.id),
        vpn_network_id=str(network.id),
        wireguard_public_key=peer_pub,
        vpn_ip=first_ip,
        private_key_encrypted=encrypt_value(peer_priv),
        is_gpu_host=False,
        is_relay=True,
        ledger_public_key=ledger_pub,
        ledger_private_key_encrypted=encrypt_value(ledger_priv),
    )
    if app_settings.ledger.enabled and app_settings.ledger.isolate_vpn_networks:
        ledger = LedgerService(db, network_id=str(network.id))
        await ledger.ensure_initialized()
    peer_count = await repo.get_peer_count(network.id)
    return VpnNetworkResponse(
        id=str(network.id),
        name=network.name,
        cidr=network.cidr,
        listen_port=network.listen_port,
        relay_endpoint=network.relay_endpoint,
        is_active=network.is_active,
        peer_count=peer_count,
        created_at=network.created_at,
    )


@router.get("/networks", response_model=list[VpnNetworkResponse])
async def list_vpn_networks(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    repo = VpnNetworkRepository(db)
    networks = await repo.list_user_networks(str(user.id))
    responses = []
    for net in networks:
        peer_count = await repo.get_peer_count(net.id)
        responses.append(
            VpnNetworkResponse(
                id=str(net.id),
                name=net.name,
                cidr=net.cidr,
                listen_port=net.listen_port,
                relay_endpoint=net.relay_endpoint,
                is_active=net.is_active,
                peer_count=peer_count,
                created_at=net.created_at,
            )
        )
    return responses


@router.get("/networks/{network_id}", response_model=VpnNetworkResponse)
async def get_vpn_network(
    network_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    repo = VpnNetworkRepository(db)
    network = await _ensure_network_member(repo, str(user.id), network_id)
    peer_count = await repo.get_peer_count(network_id)
    return VpnNetworkResponse(
        id=str(network.id),
        name=network.name,
        cidr=network.cidr,
        listen_port=network.listen_port,
        relay_endpoint=network.relay_endpoint,
        is_active=network.is_active,
        peer_count=peer_count,
        created_at=network.created_at,
    )


@router.get("/networks/{network_id}/peers", response_model=list[PeerResponse])
async def list_network_peers(
    network_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    net_repo = VpnNetworkRepository(db)
    await _ensure_network_member(net_repo, str(user.id), network_id)
    repo = PeerRepository(db)
    peers = await repo.get_by_network(network_id)
    return [
        PeerResponse(
            id=str(p.id),
            user_id=str(p.user_id),
            username=p.user.username if p.user else "unknown",
            vpn_ip=p.vpn_ip,
            online_status=p.online_status.value,
            is_gpu_host=p.is_gpu_host,
            is_online=p.online_status == PeerOnlineStatus.ONLINE,
            last_seen=p.last_seen,
            gpu_count=len(p.gpu_shares) if p.gpu_shares else 0,
        )
        for p in peers
    ]


@router.get("/networks/{network_id}/config")
async def get_wireguard_config(
    network_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    network_repo = VpnNetworkRepository(db)
    network = await _ensure_network_member(network_repo, str(user.id), network_id)

    peer_repo = PeerRepository(db)
    peer = None
    peers = await peer_repo.get_by_network(network_id)
    for p in peers:
        if str(p.user_id) == str(user.id):
            peer = p
            break

    if not peer:
        raise HTTPException(status_code=404, detail="You are not a member of this network")

    private_key = await peer_repo.get_private_key(peer)
    if not private_key:
        raise HTTPException(status_code=500, detail="Private key not found")

    config_text = generate_peer_config(
        vpn_ip=peer.vpn_ip,
        private_key=private_key,
        relay_public_key=network.relay_public_key or "",
        relay_endpoint=f"{network.relay_endpoint}:{network.listen_port}",
    )

    return VpnConfigResponse(
        config_text=config_text,
        vpn_ip=peer.vpn_ip,
        peer_id=str(peer.id),
    )


@router.post("/networks/{network_id}/invite", response_model=InviteResponse)
async def create_invite(
    network_id: str,
    data: NetworkInviteRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    network_repo = VpnNetworkRepository(db)
    network = await _ensure_network_member(network_repo, str(user.id), network_id)

    invite_repo = VpnInviteRepository(db)
    invite = await invite_repo.create(
        creator_id=str(user.id),
        vpn_network_id=network_id,
        max_uses=data.max_uses,
        expires_in_days=data.expires_in_days,
    )

    return InviteResponse(
        id=str(invite.id),
        code=invite.code,
        vpn_network_id=str(invite.vpn_network_id),
        vpn_network_name=network.name,
        max_uses=invite.max_uses,
        used_count=invite.used_count,
        expires_at=invite.expires_at,
        is_revoked=invite.is_revoked,
        created_at=invite.created_at,
    )


@router.get("/invites", response_model=list[InviteResponse])
async def list_invites(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    invite_repo = VpnInviteRepository(db)
    invites = await invite_repo.list_by_creator(str(user.id))
    responses = []
    for inv in invites:
        network_repo = VpnNetworkRepository(db)
        network = await network_repo.get_by_id(str(inv.vpn_network_id))
        responses.append(
            InviteResponse(
                id=str(inv.id),
                code=inv.code,
                vpn_network_id=str(inv.vpn_network_id),
                vpn_network_name=network.name if network else "unknown",
                max_uses=inv.max_uses,
                used_count=inv.used_count,
                expires_at=inv.expires_at,
                is_revoked=inv.is_revoked,
                created_at=inv.created_at,
            )
        )
    return responses


@router.delete("/invites/{invite_id}")
async def revoke_invite(
    invite_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    invite_repo = VpnInviteRepository(db)
    success = await invite_repo.revoke(invite_id)
    if not success:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"status": "revoked"}


@router.delete("/invites/by-code/{code}")
async def revoke_invite_by_code(
    code: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    invite_repo = VpnInviteRepository(db)
    inv = await invite_repo.get_by_code(code)
    if not inv or str(inv.creator_id) != str(user.id):
        raise HTTPException(status_code=404, detail="Invite not found")
    success = await invite_repo.revoke_by_code(code)
    if not success:
        raise HTTPException(status_code=404, detail="Invite not found")
    return {"status": "revoked"}


@router.post("/networks/{network_id}/leave")
async def leave_vpn_network(
    network_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    net_repo = VpnNetworkRepository(db)
    await _ensure_network_member(net_repo, str(user.id), network_id)
    peer_repo = PeerRepository(db)
    peers = await peer_repo.get_by_network(network_id)
    for p in peers:
        if str(p.user_id) == str(user.id):
            gpu_repo = GpuShareRepository(db)
            await gpu_repo.deactivate_peer_gpus(str(p.id))
            await peer_repo.delete(str(p.id))
            return {"status": "left"}
    raise HTTPException(status_code=404, detail="Peer not found for user")


@router.get("/peers", response_model=list[PeerResponse])
async def list_all_vpn_peers(
    network_id: str | None = None,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    net_repo = VpnNetworkRepository(db)
    peer_repo = PeerRepository(db)
    nets = await net_repo.list_user_networks(str(user.id))
    allowed = {str(n.id) for n in nets}
    peers = await peer_repo.list_all()
    if network_id:
        if network_id not in allowed:
            raise HTTPException(status_code=403, detail="Not a member of this VPN network")
        peers = [p for p in peers if str(p.vpn_network_id) == network_id]
    else:
        peers = [p for p in peers if str(p.vpn_network_id) in allowed]
    return [
        PeerResponse(
            id=str(p.id),
            user_id=str(p.user_id),
            username=p.user.username if p.user else "unknown",
            vpn_ip=p.vpn_ip,
            online_status=p.online_status.value,
            is_gpu_host=p.is_gpu_host,
            is_online=p.online_status == PeerOnlineStatus.ONLINE,
            last_seen=p.last_seen,
            gpu_count=len(p.gpu_shares) if p.gpu_shares else 0,
        )
        for p in peers
    ]


@router.post("/join", response_model=VpnConfigResponse)
async def join_network(
    data: JoinNetworkRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    invite_repo = VpnInviteRepository(db)
    invite = await invite_repo.get_by_code(data.invite_code)
    if not invite:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    if not await invite_repo.is_valid(invite):
        raise HTTPException(status_code=400, detail="Invite is expired or fully used")

    network_repo = VpnNetworkRepository(db)
    network = await network_repo.get_by_id(str(invite.vpn_network_id))
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")

    peer_repo = PeerRepository(db)
    peers_existing = await peer_repo.get_by_network(str(network.id))
    for p in peers_existing:
        if str(p.user_id) == str(user.id):
            raise HTTPException(status_code=400, detail="Already a member of this network")

    if data.wireguard_public_key:
        collision = await peer_repo.get_by_public_key(data.wireguard_public_key)
        if collision:
            raise HTTPException(status_code=400, detail="This public key is already registered")

    used_ips = {p.vpn_ip for p in peers_existing}
    vpn_ip = allocate_vpn_ip(network.cidr, used_ips)
    private_key, public_key = generate_keypair()
    ledger_priv, ledger_pub = generate_ledger_keypair()

    peer = await peer_repo.create(
        user_id=str(user.id),
        vpn_network_id=str(invite.vpn_network_id),
        wireguard_public_key=public_key,
        vpn_ip=vpn_ip,
        private_key_encrypted=encrypt_value(private_key),
        is_gpu_host=data.is_gpu_host,
        ledger_public_key=ledger_pub,
        ledger_private_key_encrypted=encrypt_value(ledger_priv),
    )

    await invite_repo.use(invite)

    config_text = generate_peer_config(
        vpn_ip=vpn_ip,
        private_key=private_key,
        relay_public_key=network.relay_public_key or "",
        relay_endpoint=f"{network.relay_endpoint}:{network.listen_port}",
    )

    return VpnConfigResponse(
        config_text=config_text,
        vpn_ip=vpn_ip,
        peer_id=str(peer.id),
    )


@router.post("/peers/register")
async def register_peer(
    data: PeerRegisterRequest,
    db: AsyncSession = Depends(get_db_session),
):
    peer_repo = PeerRepository(db)
    existing = await peer_repo.get_by_public_key(data.wireguard_public_key)
    if not existing:
        raise HTTPException(status_code=404, detail="Peer not found in network")

    peer = await peer_repo.heartbeat(str(existing.id), is_online=True, endpoint=data.endpoint)
    return {"peer_id": str(peer.id), "status": "registered"}


@router.post("/peers/heartbeat")
async def peer_heartbeat(
    data: PeerHeartbeatRequest,
    db: AsyncSession = Depends(get_db_session),
):
    peer_repo = PeerRepository(db)
    gpu_repo = GpuShareRepository(db)

    peer = await peer_repo.get_by_id(data.peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer not found")

    mark_host = True if data.gpu_status else None
    await peer_repo.heartbeat(
        data.peer_id,
        is_online=data.is_online,
        endpoint=data.endpoint,
        mark_gpu_host=mark_host,
    )

    for gpu in data.gpu_status:
        await gpu_repo.upsert(
            peer_id=data.peer_id,
            vpn_network_id=str(peer.vpn_network_id),
            gpu_data={
                "device_index": gpu.device_index,
                "name": gpu.name,
                "total_memory_mb": gpu.total_memory_mb,
                "available_memory_mb": gpu.available_memory_mb,
                "compute_capability": gpu.compute_capability,
                "gpu_type": gpu.gpu_type,
                "state": (
                    GpuShareState(gpu.state)
                    if gpu.state in ("idle", "allocated", "unavailable")
                    else GpuShareState.IDLE
                ),
                "utilization_percent": gpu.utilization_percent,
                "is_active": True,
            },
        )

    return {"status": "ok", "peer_id": data.peer_id}


@router.get("/peers/{peer_id}/gpus", response_model=list[GpuShareResponse])
async def get_peer_gpus(
    peer_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    peer_repo = PeerRepository(db)
    peer = await peer_repo.get_by_id(peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer not found")
    net_repo = VpnNetworkRepository(db)
    await _ensure_network_member(net_repo, str(user.id), str(peer.vpn_network_id))
    repo = GpuShareRepository(db)
    shares = await repo.list_by_peer(peer_id)
    username = peer.user.username if peer and peer.user else "unknown"
    return [
        GpuShareResponse(
            id=str(s.id),
            peer_id=str(s.peer_id),
            username=username,
            device_index=s.device_index,
            name=s.name,
            total_memory_mb=s.total_memory_mb,
            available_memory_mb=s.available_memory_mb,
            compute_capability=s.compute_capability,
            gpu_type=s.gpu_type,
            state=s.state.value,
            utilization_percent=s.utilization_percent,
            is_active=s.is_active,
            last_updated=s.updated_at,
        )
        for s in shares
    ]


@router.get("/gpu-pool", response_model=GpuPoolSummary)
async def get_gpu_pool(
    network_id: str | None = None,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    pool = get_registered_gpu_pool()
    if pool is not None:
        await refresh_gpu_pool_from_db(db, pool)

    gpu_repo = GpuShareRepository(db)
    if network_id:
        shares = await gpu_repo.list_by_network(network_id)
    else:
        all_shares = []
        net_repo = VpnNetworkRepository(db)
        networks = await net_repo.list_user_networks(str(user.id))
        for net in networks:
            net_shares = await gpu_repo.list_by_network(str(net.id))
            all_shares.extend(net_shares)
        shares = all_shares

    total_gpus = len(shares)
    total_memory = sum(s.total_memory_mb for s in shares)
    available_memory = sum(s.available_memory_mb for s in shares)
    online_peers = len({s.peer_id for s in shares if s.is_active})
    online_gpu_hosts = len({s.peer_id for s in shares})

    peer_repo = PeerRepository(db)
    breakdown = []
    for s in shares:
        peer = await peer_repo.get_by_id(str(s.peer_id))
        username = peer.user.username if peer and peer.user else "unknown"
        breakdown.append(
            GpuShareResponse(
                id=str(s.id),
                peer_id=str(s.peer_id),
                username=username,
                device_index=s.device_index,
                name=s.name,
                total_memory_mb=s.total_memory_mb,
                available_memory_mb=s.available_memory_mb,
                compute_capability=s.compute_capability,
                gpu_type=s.gpu_type,
                state=s.state.value,
                utilization_percent=s.utilization_percent,
                is_active=s.is_active,
                last_updated=s.updated_at,
            )
        )

    return GpuPoolSummary(
        total_gpus=total_gpus,
        total_memory_mb=total_memory,
        available_memory_mb=available_memory,
        online_peers=online_peers,
        online_gpu_hosts=online_gpu_hosts,
        gpu_breakdown=breakdown,
    )


@router.get("/friends", response_model=FriendListResponse)
async def list_friends(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    repo = FriendshipRepository(db)
    friends = await repo.get_friends(str(user.id))
    pending = await repo.get_pending(str(user.id))
    sent = await repo.get_sent_requests(str(user.id))

    def to_response(f) -> FriendResponse:
        return FriendResponse(
            id=str(f.id),
            user_id=str(f.user_id),
            username=f.friend.username if f.friend else "unknown",
            email=f.friend.email if f.friend else "",
            status=f.status.value,
            created_at=f.created_at,
            accepted_at=f.accepted_at,
        )

    return FriendListResponse(
        friends=[to_response(f) for f in friends],
        pending=[to_response(p) for p in pending],
        sent_requests=[to_response(s) for s in sent],
    )


@router.post("/friends/request")
async def send_friend_request(
    data: FriendRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    repo = FriendshipRepository(db)
    existing = await repo.check_friendship(str(user.id), data.friend_id)
    if existing:
        raise HTTPException(status_code=400, detail="Friendship already exists")

    await repo.create(str(user.id), data.friend_id)
    return {"status": "request_sent"}


@router.post("/friends/{friendship_id}/accept")
async def accept_friend(
    friendship_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    repo = FriendshipRepository(db)
    friendship = await repo.get_by_id(friendship_id)
    if not friendship:
        raise HTTPException(status_code=404, detail="Friendship not found")
    if str(friendship.friend_id) != str(user.id):
        raise HTTPException(status_code=403, detail="Not authorized to accept this request")

    await repo.accept(friendship_id)
    return {"status": "accepted"}


@router.post("/friends/{friendship_id}/block")
async def block_friend(
    friendship_id: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    repo = FriendshipRepository(db)
    friendship = await repo.get_by_id(friendship_id)
    if not friendship:
        raise HTTPException(status_code=404, detail="Friendship not found")
    if str(friendship.user_id) != str(user.id) and str(friendship.friend_id) != str(user.id):
        raise HTTPException(status_code=403, detail="Not part of this friendship")
    await repo.block(friendship_id)
    return {"status": "blocked"}
