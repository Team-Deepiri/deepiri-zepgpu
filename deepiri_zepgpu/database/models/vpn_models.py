"""VPN, peer, and GPU sharing models."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from deepiri_zepgpu.database.models.user import User


class FriendshipStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"


class PeerOnlineStatus(str, enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    AWOL = "awol"


class GpuShareState(str, enum.Enum):
    IDLE = "idle"
    ALLOCATED = "allocated"
    UNAVAILABLE = "unavailable"


class VpnNetwork(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "vpn_networks"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cidr: Mapped[str] = mapped_column(String(20), default="10.8.0.0/24", nullable=False)
    listen_port: Mapped[int] = mapped_column(Integer, default=51820, nullable=False)
    relay_endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relay_public_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    private_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    peers: Mapped[list[Peer]] = relationship("Peer", back_populates="vpn_network", lazy="dynamic")
    invites: Mapped[list[VpnInvite]] = relationship(
        "VpnInvite", back_populates="vpn_network", lazy="dynamic"
    )
    gpu_shares: Mapped[list[GpuShare]] = relationship(
        "GpuShare", back_populates="vpn_network", lazy="dynamic"
    )


class Peer(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "vpn_peers"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vpn_network_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vpn_networks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    wireguard_public_key: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    wireguard_private_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    vpn_ip: Mapped[str] = mapped_column(String(15), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)

    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    online_status: Mapped[PeerOnlineStatus] = mapped_column(
        Enum(PeerOnlineStatus), default=PeerOnlineStatus.OFFLINE, nullable=False
    )
    is_gpu_host: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_relay: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    heartbeat_interval_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    auth_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship("User", back_populates="vpn_peers", lazy="joined")
    vpn_network: Mapped[VpnNetwork] = relationship("VpnNetwork", back_populates="peers")
    gpu_shares: Mapped[list[GpuShare]] = relationship(
        "GpuShare", back_populates="peer", lazy="dynamic"
    )
    quota: Mapped[GpuShareQuota] = relationship(
        "GpuShareQuota", back_populates="peer", uselist=False
    )


class GpuShare(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "gpu_shares"

    peer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vpn_peers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vpn_network_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vpn_networks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    device_index: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_memory_mb: Mapped[int] = mapped_column(BigInteger, nullable=False)
    available_memory_mb: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compute_capability: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gpu_type: Mapped[str] = mapped_column(String(50), default="nvidia", nullable=False)

    state: Mapped[GpuShareState] = mapped_column(
        Enum(GpuShareState), default=GpuShareState.IDLE, nullable=False
    )
    current_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utilization_percent: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    peer: Mapped[Peer] = relationship("Peer", back_populates="gpu_shares")
    vpn_network: Mapped[VpnNetwork] = relationship("VpnNetwork", back_populates="gpu_shares")


class Friendship(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "friendships"

    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    friend_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[FriendshipStatus] = mapped_column(
        Enum(FriendshipStatus), default=FriendshipStatus.PENDING, nullable=False, index=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(
        "User", foreign_keys=[user_id], back_populates="friendships_initiated", lazy="joined"
    )
    friend: Mapped[User] = relationship(
        "User", foreign_keys=[friend_id], back_populates="friendships_received", lazy="joined"
    )

    __table_args__ = (UniqueConstraint("user_id", "friend_id", name="uq_friendship_pair"),)


class VpnInvite(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "vpn_invites"

    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    creator_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    vpn_network_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vpn_networks.id", ondelete="CASCADE"), nullable=False
    )

    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    creator: Mapped[User] = relationship(
        "User", back_populates="vpn_invites_created", lazy="joined"
    )
    vpn_network: Mapped[VpnNetwork] = relationship("VpnNetwork", back_populates="invites")


class GpuShareQuota(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "gpu_share_quotas"

    peer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vpn_peers.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    max_gpu_hours_per_day: Mapped[float] = mapped_column(Float, default=4.0, nullable=False)
    max_concurrent_tasks: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    priority_boost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_usage_hours: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    peer: Mapped[Peer] = relationship("Peer", back_populates="quota")
