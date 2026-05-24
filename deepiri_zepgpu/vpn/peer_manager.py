"""Peer lifecycle helpers (heartbeat sweep, registration orchestration)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.vpn.config import vpn_settings
from deepiri_zepgpu.vpn.repositories import PeerRepository


async def mark_stale_peers_offline(db: AsyncSession) -> int:
    """Mark peers that missed heartbeats as AWOL/offline."""
    repo = PeerRepository(db)
    return await repo.mark_awol_peers(vpn_settings.heartbeat_timeout_seconds)
