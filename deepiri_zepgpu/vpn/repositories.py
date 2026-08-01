"""Repository for VPN models."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from deepiri_zepgpu.database.models.vpn_models import (
    Friendship,
    FriendshipStatus,
    GpuShare,
    GpuShareQuota,
    GpuShareState,
    Peer,
    PeerOnlineStatus,
    VpnInvite,
    VpnNetwork,
)
from deepiri_zepgpu.vpn.config import vpn_settings
from deepiri_zepgpu.vpn.crypto import decrypt_value, encrypt_value


def generate_invite_code(length: int = 8) -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(chars) for _ in range(length))


class VpnNetworkRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        name: str,
        cidr: str = "10.8.0.0/24",
        listen_port: int = 51820,
        relay_endpoint: str | None = None,
        relay_public_key: str | None = None,
        private_key_encrypted: str | None = None,
        host_id: str | None = None,
        transport_mode: str = "wireguard",
    ) -> VpnNetwork:
        network = VpnNetwork(
            name=name,
            cidr=cidr,
            listen_port=listen_port,
            relay_endpoint=relay_endpoint,
            relay_public_key=relay_public_key,
            private_key_encrypted=private_key_encrypted,
            host_id=host_id,
            transport_mode=transport_mode,
        )
        self.db.add(network)
        await self.db.commit()
        await self.db.refresh(network)
        return network

    async def get_by_id(self, network_id: str) -> VpnNetwork | None:
        result = await self.db.execute(select(VpnNetwork).where(VpnNetwork.id == network_id))
        return result.scalar_one_or_none()

    async def list_user_networks(self, user_id: str) -> list[VpnNetwork]:
        result = await self.db.execute(
            select(VpnNetwork).join(Peer).where(Peer.user_id == user_id).distinct()
        )
        return list(result.scalars().all())

    async def user_belongs_to_network(self, user_id: str, network_id: str) -> bool:
        """Return True if the user has a peer on the given network."""
        result = await self.db.execute(
            select(Peer.id)
            .where(
                Peer.user_id == user_id,
                Peer.vpn_network_id == network_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_all(self) -> list[VpnNetwork]:
        result = await self.db.execute(select(VpnNetwork))
        return list(result.scalars().all())

    async def get_peer_count(self, network_id: str) -> int:
        result = await self.db.execute(
            select(func.count(Peer.id)).where(Peer.vpn_network_id == network_id)
        )
        return result.scalar() or 0


class PeerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: str,
        vpn_network_id: str,
        wireguard_public_key: str,
        vpn_ip: str,
        private_key_encrypted: str | None = None,
        endpoint: str | None = None,
        is_gpu_host: bool = False,
        is_relay: bool = False,
        auth_token_encrypted: str | None = None,
        ledger_public_key: str | None = None,
        ledger_private_key_encrypted: str | None = None,
    ) -> Peer:
        peer = Peer(
            user_id=user_id,
            vpn_network_id=vpn_network_id,
            wireguard_public_key=wireguard_public_key,
            wireguard_private_key_encrypted=private_key_encrypted,
            vpn_ip=vpn_ip,
            endpoint=endpoint,
            is_gpu_host=is_gpu_host,
            is_relay=is_relay,
            last_seen=datetime.now(UTC),
            auth_token_encrypted=auth_token_encrypted,
            ledger_public_key=ledger_public_key,
            ledger_private_key_encrypted=ledger_private_key_encrypted,
        )
        self.db.add(peer)
        await self.db.commit()
        await self.db.refresh(peer)
        return peer

    async def set_ledger_keys(
        self,
        peer_id: str,
        public_key: str,
        private_key_encrypted: str,
    ) -> Peer | None:
        peer = await self.get_by_id(peer_id)
        if not peer:
            return None
        peer.ledger_public_key = public_key
        peer.ledger_private_key_encrypted = private_key_encrypted
        await self.db.commit()
        await self.db.refresh(peer)
        return peer

    async def get_by_id(self, peer_id: str) -> Peer | None:
        result = await self.db.execute(
            select(Peer).options(joinedload(Peer.user)).where(Peer.id == peer_id)
        )
        return result.unique().scalar_one_or_none()

    async def get_by_public_key(self, public_key: str) -> Peer | None:
        result = await self.db.execute(
            select(Peer)
            .options(joinedload(Peer.user))
            .where(Peer.wireguard_public_key == public_key)
        )
        return result.unique().scalar_one_or_none()

    async def get_by_network(self, network_id: str) -> list[Peer]:
        result = await self.db.execute(
            select(Peer).options(joinedload(Peer.user)).where(Peer.vpn_network_id == network_id)
        )
        return list(result.unique().scalars().all())

    async def list_all(self) -> list[Peer]:
        result = await self.db.execute(select(Peer).options(joinedload(Peer.user)))
        return list(result.unique().scalars().all())

    async def heartbeat(
        self,
        peer_id: str,
        is_online: bool = True,
        endpoint: str | None = None,
        mark_gpu_host: bool | None = None,
    ) -> Peer | None:
        result = await self.db.execute(select(Peer).where(Peer.id == peer_id))
        peer = result.scalar_one_or_none()
        if peer:
            peer.last_seen = datetime.now(UTC)
            peer.online_status = PeerOnlineStatus.ONLINE if is_online else PeerOnlineStatus.OFFLINE
            if endpoint:
                peer.endpoint = endpoint
            if mark_gpu_host is not None:
                peer.is_gpu_host = mark_gpu_host
            await self.db.commit()
            await self.db.refresh(peer)
        return peer

    async def mark_awol_peers(self, timeout_seconds: int = 90) -> list[Peer]:
        threshold = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        result = await self.db.execute(
            select(Peer).where(
                and_(
                    Peer.online_status == PeerOnlineStatus.ONLINE,
                    Peer.last_seen < threshold,
                )
            )
        )
        peers = list(result.scalars().all())
        for peer in peers:
            peer.online_status = PeerOnlineStatus.AWOL
        await self.db.commit()
        return peers

    async def delete(self, peer_id: str) -> bool:
        result = await self.db.execute(select(Peer).where(Peer.id == peer_id))
        peer = result.scalar_one_or_none()
        if peer:
            await self.db.delete(peer)
            await self.db.commit()
            return True
        return False

    async def get_auth_token(self, peer: Peer) -> str | None:
        if peer.auth_token_encrypted:
            return decrypt_value(peer.auth_token_encrypted)
        return None

    async def set_auth_token(self, peer: Peer, token: str) -> None:
        peer.auth_token_encrypted = encrypt_value(token)
        await self.db.commit()

    async def get_or_create_auth_token(self, peer: Peer) -> str:
        """Return the peer's provider auth token, generating one if missing.

        Covers both freshly created peers (join/create flows) and peers
        that existed before per-peer provider auth was added, so any
        call to fetch a peer's config transparently provisions a token.

        Raises:
            ProviderRevokedError: if the peer membership or token is revoked.
        """
        from deepiri_zepgpu.rooms.provider_tokens import (
            ProviderRevokedError,
            issue_provider_token,
            provider_token_ttl,
        )

        if peer.revoked_at is not None or peer.token_revoked_at is not None:
            raise ProviderRevokedError("Cannot issue credentials for a revoked provider")

        existing = await self.get_auth_token(peer)
        if existing:
            if peer.token_expires_at is None:
                from datetime import UTC, datetime

                peer.token_expires_at = datetime.now(UTC) + provider_token_ttl()
                await self.db.commit()
            return existing
        return await issue_provider_token(self, peer)

    async def revoke_provider(self, peer: Peer) -> Peer:
        """Revoke provider membership and invalidate credentials."""
        now = datetime.now(UTC)
        peer.revoked_at = now
        peer.token_revoked_at = now
        peer.auth_token_encrypted = None
        peer.online_status = PeerOnlineStatus.OFFLINE
        await self.db.commit()
        await self.db.refresh(peer)
        return peer

    async def get_private_key(self, peer: Peer) -> str | None:
        if peer.wireguard_private_key_encrypted:
            return decrypt_value(peer.wireguard_private_key_encrypted)
        return None


class GpuShareRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert(
        self,
        peer_id: str,
        vpn_network_id: str,
        gpu_data: dict,
    ) -> GpuShare:
        result = await self.db.execute(
            select(GpuShare).where(
                and_(
                    GpuShare.peer_id == peer_id,
                    GpuShare.device_index == gpu_data["device_index"],
                )
            )
        )
        share = result.scalar_one_or_none()
        if share:
            for key, value in gpu_data.items():
                if hasattr(share, key):
                    setattr(share, key, value)
        else:
            share = GpuShare(
                peer_id=peer_id,
                vpn_network_id=vpn_network_id,
                **gpu_data,
            )
            self.db.add(share)
        await self.db.commit()
        await self.db.refresh(share)
        return share

    async def list_by_network(self, network_id: str, active_only: bool = True) -> list[GpuShare]:
        query = (
            select(GpuShare)
            .options(joinedload(GpuShare.peer).joinedload(Peer.user))
            .where(GpuShare.vpn_network_id == network_id)
        )
        if active_only:
            query = query.where(GpuShare.is_active.is_(True))
        result = await self.db.execute(query)
        return list(result.unique().scalars().all())

    async def list_by_peer(self, peer_id: str) -> list[GpuShare]:
        result = await self.db.execute(select(GpuShare).where(GpuShare.peer_id == peer_id))
        return list(result.scalars().all())

    async def get_by_id(self, share_id: str) -> GpuShare | None:
        result = await self.db.execute(select(GpuShare).where(GpuShare.id == share_id))
        return result.scalar_one_or_none()

    async def update_state(
        self,
        share_id: str,
        state: GpuShareState,
        current_task_id: str | None = None,
    ) -> GpuShare | None:
        result = await self.db.execute(select(GpuShare).where(GpuShare.id == share_id))
        share = result.scalar_one_or_none()
        if share:
            share.state = state
            share.current_task_id = current_task_id
            await self.db.commit()
            await self.db.refresh(share)
        return share

    async def deactivate_peer_gpus(self, peer_id: str) -> int:
        result = await self.db.execute(select(GpuShare).where(GpuShare.peer_id == peer_id))
        shares = list(result.scalars().all())
        for share in shares:
            share.is_active = False
        await self.db.commit()
        return len(shares)


class FriendshipRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user_id: str, friend_id: str) -> Friendship:
        friendship = Friendship(user_id=user_id, friend_id=friend_id)
        self.db.add(friendship)
        await self.db.commit()
        await self.db.refresh(friendship)
        return friendship

    async def get_friends(self, user_id: str) -> list[Friendship]:
        result = await self.db.execute(
            select(Friendship)
            .options(joinedload(Friendship.friend))
            .where(
                and_(
                    Friendship.user_id == user_id,
                    Friendship.status == FriendshipStatus.ACCEPTED,
                )
            )
        )
        return list(result.scalars().all())

    async def get_pending(self, user_id: str) -> list[Friendship]:
        result = await self.db.execute(
            select(Friendship)
            .options(joinedload(Friendship.user), joinedload(Friendship.friend))
            .where(
                and_(
                    Friendship.friend_id == user_id,
                    Friendship.status == FriendshipStatus.PENDING,
                )
            )
        )
        return list(result.scalars().all())

    async def get_sent_requests(self, user_id: str) -> list[Friendship]:
        result = await self.db.execute(
            select(Friendship)
            .options(joinedload(Friendship.friend))
            .where(
                and_(
                    Friendship.user_id == user_id,
                    Friendship.status == FriendshipStatus.PENDING,
                )
            )
        )
        return list(result.scalars().all())

    async def get_by_id(self, friendship_id: str) -> Friendship | None:
        result = await self.db.execute(select(Friendship).where(Friendship.id == friendship_id))
        return result.scalar_one_or_none()

    async def accept(self, friendship_id: str) -> Friendship | None:
        result = await self.db.execute(select(Friendship).where(Friendship.id == friendship_id))
        friendship = result.scalar_one_or_none()
        if friendship:
            friendship.status = FriendshipStatus.ACCEPTED
            friendship.accepted_at = datetime.now(UTC)
            await self.db.commit()
            await self.db.refresh(friendship)
        return friendship

    async def block(self, friendship_id: str) -> Friendship | None:
        result = await self.db.execute(select(Friendship).where(Friendship.id == friendship_id))
        friendship = result.scalar_one_or_none()
        if friendship:
            friendship.status = FriendshipStatus.BLOCKED
            await self.db.commit()
            await self.db.refresh(friendship)
        return friendship

    async def check_friendship(self, user_id: str, friend_id: str) -> Friendship | None:
        result = await self.db.execute(
            select(Friendship).where(
                or_(
                    and_(Friendship.user_id == user_id, Friendship.friend_id == friend_id),
                    and_(Friendship.user_id == friend_id, Friendship.friend_id == user_id),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_friend_ids(self, user_id: str) -> list[str]:
        friends = await self.get_friends(user_id)
        return [f.friend_id for f in friends]


class VpnInviteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        creator_id: str,
        vpn_network_id: str,
        max_uses: int = 1,
        expires_in_days: int = 7,
    ) -> VpnInvite:
        code = generate_invite_code(vpn_settings.invite_code_length)
        expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
        invite = VpnInvite(
            code=code,
            creator_id=creator_id,
            vpn_network_id=vpn_network_id,
            max_uses=max_uses,
            expires_at=expires_at,
        )
        self.db.add(invite)
        await self.db.commit()
        await self.db.refresh(invite)
        return invite

    async def get_by_code(self, code: str) -> VpnInvite | None:
        result = await self.db.execute(select(VpnInvite).where(VpnInvite.code == code))
        return result.scalar_one_or_none()

    async def list_by_creator(self, creator_id: str) -> list[VpnInvite]:
        result = await self.db.execute(
            select(VpnInvite)
            .options(joinedload(VpnInvite.vpn_network))
            .where(VpnInvite.creator_id == creator_id)
            .order_by(VpnInvite.created_at.desc())
        )
        return list(result.unique().scalars().all())

    async def is_valid(self, invite: VpnInvite) -> bool:
        if invite.is_revoked:
            return False
        if invite.used_count >= invite.max_uses:
            return False
        if invite.expires_at:
            now = datetime.now(invite.expires_at.tzinfo or UTC)
            if now > invite.expires_at:
                return False
        return True

    async def use(self, invite: VpnInvite) -> bool:
        if not await self.is_valid(invite):
            return False
        invite.used_count += 1
        await self.db.commit()
        return True

    async def revoke(self, invite_id: str) -> bool:
        result = await self.db.execute(select(VpnInvite).where(VpnInvite.id == invite_id))
        invite = result.scalar_one_or_none()
        if invite:
            invite.is_revoked = True
            await self.db.commit()
            return True
        return False

    async def revoke_by_code(self, code: str) -> bool:
        result = await self.db.execute(select(VpnInvite).where(VpnInvite.code == code))
        invite = result.scalar_one_or_none()
        if invite:
            invite.is_revoked = True
            await self.db.commit()
            return True
        return False


class GpuShareQuotaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        peer_id: str,
        max_gpu_hours_per_day: float = 4.0,
        max_concurrent_tasks: int = 1,
        priority_boost: int = 0,
    ) -> GpuShareQuota:
        quota = GpuShareQuota(
            peer_id=peer_id,
            max_gpu_hours_per_day=max_gpu_hours_per_day,
            max_concurrent_tasks=max_concurrent_tasks,
            priority_boost=priority_boost,
        )
        self.db.add(quota)
        await self.db.commit()
        await self.db.refresh(quota)
        return quota

    async def get_by_peer(self, peer_id: str) -> GpuShareQuota | None:
        result = await self.db.execute(
            select(GpuShareQuota).where(GpuShareQuota.peer_id == peer_id)
        )
        return result.scalar_one_or_none()
