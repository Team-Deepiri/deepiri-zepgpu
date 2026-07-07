"""Room-aware GPU task dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.database.models.node_task_assignment import NodeTaskAssignment
from deepiri_zepgpu.database.models.vpn_models import GpuShare, GpuShareState, PeerOnlineStatus
from deepiri_zepgpu.database.repositories.node_task_repository import NodeTaskRepository
from deepiri_zepgpu.vpn.remote_gpu_lock import RemoteGpuLock
from deepiri_zepgpu.vpn.repositories import GpuShareRepository, PeerRepository, VpnNetworkRepository

DispatchMode = Literal["local", "room_auto", "room_specific_node"]

ROOM_DISPATCH_MODES = frozenset({"room_auto", "room_specific_node"})


class RoomDispatchError(Exception):
    """Base error for room dispatch failures."""


class RoomAccessError(RoomDispatchError):
    """User does not have access to the room."""


class RoomValidationError(RoomDispatchError):
    """Invalid room dispatch request."""


class NoRoomGpuAvailable(RoomDispatchError):
    """No eligible GPU found in the room."""


class RoomGpuLockError(RoomDispatchError):
    """Could not acquire GPU lock for any candidate."""


@dataclass
class RoomDispatchResult:
    """Result of a successful room GPU assignment."""

    assignment: NodeTaskAssignment
    peer_id: str
    gpu_share_id: str
    vpn_network_id: str


async def ensure_room_access(
    db: AsyncSession,
    user_id: str,
    room_id: str,
) -> None:
    """Verify the user is a member of the room."""
    network_repo = VpnNetworkRepository(db)
    room = await network_repo.get_by_id(room_id)
    if not room:
        raise RoomValidationError("Room not found")

    user_rooms = await network_repo.list_user_networks(user_id)
    if not any(str(user_room.id) == str(room_id) for user_room in user_rooms):
        raise RoomAccessError("You do not have access to this room")


def _share_is_eligible(
    share: GpuShare,
    *,
    required_memory_mb: int,
    gpu_type: str | None,
    target_peer_id: str | None,
    target_gpu_share_id: str | None,
) -> bool:
    peer = share.peer
    if not peer:
        return False
    if not share.is_active:
        return False
    if share.state != GpuShareState.IDLE:
        return False
    if share.available_memory_mb < required_memory_mb:
        return False
    if peer.online_status != PeerOnlineStatus.ONLINE:
        return False
    if not peer.is_gpu_host:
        return False
    if gpu_type and share.gpu_type != gpu_type:
        return False
    if target_peer_id and str(share.peer_id) != str(target_peer_id):
        return False
    if target_gpu_share_id and str(share.id) != str(target_gpu_share_id):
        return False
    return True


def rank_eligible_shares(
    shares: list[GpuShare],
    *,
    required_memory_mb: int,
    gpu_type: str | None = None,
    target_peer_id: str | None = None,
    target_gpu_share_id: str | None = None,
) -> list[GpuShare]:
    """Return eligible shares sorted by policy: higher memory, lower utilization."""
    eligible = [
        share
        for share in shares
        if _share_is_eligible(
            share,
            required_memory_mb=required_memory_mb,
            gpu_type=gpu_type,
            target_peer_id=target_peer_id,
            target_gpu_share_id=target_gpu_share_id,
        )
    ]
    eligible.sort(
        key=lambda s: (
            -int(s.available_memory_mb),
            float(s.utilization_percent or 0.0),
        )
    )
    return eligible


async def select_and_assign_room_gpu(
    db: AsyncSession,
    *,
    user_id: str,
    room_id: str,
    task_id: str,
    required_memory_mb: int,
    dispatch_mode: DispatchMode,
    gpu_type: str | None = None,
    target_peer_id: str | None = None,
    target_gpu_share_id: str | None = None,
    remote_lock: RemoteGpuLock | None = None,
) -> RoomDispatchResult:
    """Select a room GPU and create an assignment with lock."""
    if dispatch_mode not in ROOM_DISPATCH_MODES:
        raise RoomValidationError(f"Unsupported dispatch mode: {dispatch_mode}")

    if dispatch_mode == "room_specific_node" and not target_peer_id and not target_gpu_share_id:
        raise RoomValidationError(
            "room_specific_node requires target_peer_id or target_gpu_share_id"
        )

    await ensure_room_access(db, user_id, room_id)

    if target_peer_id:
        peer_repo = PeerRepository(db)
        peer = await peer_repo.get_by_id(target_peer_id)
        if not peer or str(peer.vpn_network_id) != str(room_id):
            raise RoomValidationError("Target peer does not belong to this room")

    if target_gpu_share_id:
        gpu_repo = GpuShareRepository(db)
        share = await gpu_repo.get_by_id(target_gpu_share_id)
        if not share or str(share.vpn_network_id) != str(room_id):
            raise RoomValidationError("Target GPU share does not belong to this room")
        if not share.is_active or share.state != GpuShareState.IDLE:
            raise RoomValidationError("Target GPU share is not active and available")

    gpu_repo = GpuShareRepository(db)
    shares = await gpu_repo.list_by_network(room_id, active_only=True)
    candidates = rank_eligible_shares(
        shares,
        required_memory_mb=required_memory_mb,
        gpu_type=gpu_type,
        target_peer_id=target_peer_id,
        target_gpu_share_id=target_gpu_share_id,
    )

    if not candidates:
        raise NoRoomGpuAvailable("No eligible GPU available in this room")

    lock = remote_lock or RemoteGpuLock()
    assignment_repo = NodeTaskRepository(db)
    last_share_id: str | None = None
    last_task_id: str | None = None

    try:
        for share in candidates:
            share_id = str(share.id)
            if not lock.acquire(share_id, task_id):
                continue

            last_share_id = share_id
            last_task_id = task_id
            try:
                updated = await gpu_repo.update_state(
                    share_id,
                    GpuShareState.ALLOCATED,
                    current_task_id=task_id,
                )
                if not updated:
                    lock.release(share_id, task_id)
                    last_share_id = None
                    last_task_id = None
                    continue

                assignment = await assignment_repo.create_assignment(
                    vpn_network_id=str(room_id),
                    task_id=task_id,
                    peer_id=str(share.peer_id),
                    gpu_share_id=share_id,
                )
                return RoomDispatchResult(
                    assignment=assignment,
                    peer_id=str(share.peer_id),
                    gpu_share_id=share_id,
                    vpn_network_id=str(room_id),
                )
            except Exception:
                lock.release(share_id, task_id)
                await gpu_repo.update_state(share_id, GpuShareState.IDLE, current_task_id=None)
                last_share_id = None
                last_task_id = None
                raise

        raise RoomGpuLockError("Could not acquire lock for any eligible GPU share")
    except Exception:
        if last_share_id and last_task_id:
            lock.release(last_share_id, last_task_id)
            await gpu_repo.update_state(last_share_id, GpuShareState.IDLE, current_task_id=None)
        raise


async def release_room_assignment(
    db: AsyncSession,
    *,
    task_id: str,
    remote_lock: RemoteGpuLock | None = None,
) -> None:
    """Release GPU lock and share state for a room-assigned task."""
    assignment_repo = NodeTaskRepository(db)
    assignment = await assignment_repo.get_by_task_id(task_id)
    if not assignment or not assignment.gpu_share_id:
        return

    lock = remote_lock or RemoteGpuLock()
    share_id = str(assignment.gpu_share_id)
    lock.release(share_id, task_id)

    gpu_repo = GpuShareRepository(db)
    await gpu_repo.update_state(share_id, GpuShareState.IDLE, current_task_id=None)
