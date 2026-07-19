"""Peer lifecycle helpers (heartbeat sweep, registration orchestration)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.room_events import emit_room_event
from deepiri_zepgpu.vpn.config import vpn_settings
from deepiri_zepgpu.vpn.repositories import PeerRepository


async def mark_stale_peers_offline(db: AsyncSession) -> int:
    """Mark peers that missed heartbeats as AWOL/offline and emit room events."""
    repo = PeerRepository(db)
    peers = await repo.mark_awol_peers(vpn_settings.heartbeat_timeout_seconds)
    for peer in peers:
        await emit_room_event(
            str(peer.vpn_network_id),
            "room_node_offline",
            {
                "peer_id": str(peer.id),
                "room_id": str(peer.vpn_network_id),
                "user_id": str(peer.user_id) if peer.user_id else None,
                "status": "awol",
                "is_online": False,
                "last_seen": peer.last_seen.isoformat() if peer.last_seen else None,
            },
        )
    return len(peers)
