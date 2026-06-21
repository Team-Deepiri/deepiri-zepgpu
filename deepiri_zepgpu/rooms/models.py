"""Room-facing API schemas.

These models expose the existing VPN network functionality using
product-level room terminology.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RoomCreateRequest(BaseModel):
    """Request body for creating a GPU room."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class RoomResponse(BaseModel):
    """Room-facing response for an underlying VPN network."""

    id: UUID
    name: str
    description: str | None = None
    host_id: UUID | None = None
    status: str
    created_at: datetime
    updated_at: datetime | None = None


class RoomMemberResponse(BaseModel):
    """Room-facing response for a peer/member."""

    id: UUID
    user_id: UUID | None = None
    display_name: str | None = None
    status: str
    joined_at: datetime | None = None
    last_seen_at: datetime | None = None


class RoomGpuPoolSummary(BaseModel):
    """GPU availability summary for a room."""

    room_id: UUID
    total_gpus: int = 0
    available_gpus: int = 0
    allocated_gpus: int = 0
    total_memory_mb: int = 0
    available_memory_mb: int = 0
    providers: list[str] = Field(default_factory=list)


class RoomInviteCreateRequest(BaseModel):
    """Request body for creating a room invite."""

    expires_at: datetime | None = None
    max_uses: int = Field(default=1, ge=1)


class RoomInviteResponse(BaseModel):
    """Room-facing response for an underlying VPN invite."""

    id: UUID
    room_id: UUID
    code: str
    created_by: UUID
    expires_at: datetime | None = None
    max_uses: int
    use_count: int
    is_revoked: bool
    created_at: datetime


class RoomJoinRequest(BaseModel):
    """Request body for joining a room by invite code."""

    invite_code: str = Field(..., min_length=1)


class RoomJoinResponse(BaseModel):
    """Response returned after joining a room."""

    room: RoomResponse
    member: RoomMemberResponse
    config_available: bool = True


class RoomConnectionConfigResponse(BaseModel):
    """WireGuard/client configuration response for the current user."""

    room_id: UUID
    peer_id: UUID
    config: str
    filename: str
