"""Sync GpuPoolAggregator from database (remote VPN peers)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from deepiri_zepgpu.database.models.vpn_models import GpuShare, Peer, PeerOnlineStatus

if TYPE_CHECKING:
    from deepiri_zepgpu.vpn.gpu_pool import GpuPoolAggregator

_registered_pool: GpuPoolAggregator | None = None


def register_gpu_pool(pool: GpuPoolAggregator) -> None:
    """Called when TaskSubmitter starts so API/lifespan can refresh the same pool."""
    global _registered_pool
    _registered_pool = pool


def get_registered_gpu_pool() -> GpuPoolAggregator | None:
    return _registered_pool


async def refresh_gpu_pool_from_db(
    db: AsyncSession,
    pool: GpuPoolAggregator,
    network_id: str | None = None,
) -> int:
    """Load active GPU shares from online peers into the aggregator. Returns count synced."""
    query = (
        select(GpuShare)
        .options(joinedload(GpuShare.peer).joinedload(Peer.user))
        .where(GpuShare.is_active.is_(True))
    )
    if network_id is not None:
        query = query.where(GpuShare.vpn_network_id == network_id)

    result = await db.execute(query)
    shares = list(result.unique().scalars().all())
    remote_payload: list[dict] = []
    for s in shares:
        peer = s.peer
        if not peer or peer.online_status != PeerOnlineStatus.ONLINE:
            continue
        if not peer.is_gpu_host:
            continue
        username = peer.user.username if peer.user else "unknown"
        remote_payload.append(
            {
                "share_id": str(s.id),
                "peer_id": str(s.peer_id),
                "peer_username": username,
                "device_index": s.device_index,
                "name": s.name or "GPU",
                "gpu_type": s.gpu_type,
                "total_memory_mb": int(s.total_memory_mb),
                "available_memory_mb": int(s.available_memory_mb),
                "compute_capability": s.compute_capability or "0.0",
                "state": s.state.value,
                "current_task_id": s.current_task_id,
                "utilization_percent": s.utilization_percent or 0.0,
                "vpn_ip": peer.vpn_ip or "",
                "vpn_network_id": str(s.vpn_network_id),
            }
        )
    await pool.refresh_remote_gpus(remote_payload)
    return len(remote_payload)
