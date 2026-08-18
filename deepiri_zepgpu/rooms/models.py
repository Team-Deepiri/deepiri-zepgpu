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
    transport_mode: str | None = Field(
        default=None,
        max_length=32,
        description="wireguard | dialout | overlay (default: coordinator dialout)",
    )


class RoomResponse(BaseModel):
    """Room-facing response for an underlying VPN network."""

    id: UUID
    name: str
    description: str | None = None
    host_id: UUID | None = None
    status: str
    transport_mode: str = "wireguard"
    transport_experimental: bool = False
    requires_wireguard_udp: bool = True
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
    coordinator_url: str | None = None
    join_command: str | None = Field(
        default=None,
        description="One-line zepgpu-node join command for providers",
    )


class RoomJoinRequest(BaseModel):
    """Request body for joining a room by invite code."""

    invite_code: str = Field(..., min_length=1)
    node_name: str | None = Field(default=None, max_length=255)
    provider_mode: str | None = Field(default=None, max_length=32)


class RoomJoinResponse(BaseModel):
    """Response returned after joining a room."""

    room: RoomResponse
    member: RoomMemberResponse
    config_available: bool = True
    auth_token: str | None = Field(
        default=None,
        description=(
            "Room-scoped provider authentication token. Treat as a secret; "
            "never log or display to other room members."
        ),
    )
    token_expires_at: datetime | None = None
    heartbeat_interval_seconds: int | None = None


class RoomConnectionConfigResponse(BaseModel):
    """Mode-specific connection configuration for the current user."""

    room_id: UUID
    peer_id: UUID
    config: str
    filename: str
    transport_mode: str = "wireguard"
    requires_wireguard_udp: bool = True
    vpn_ip: str | None = None
    hub_reachable: bool = False
    overlay_backend: str | None = None
    auth_token: str | None = Field(
        default=None,
        description=(
            "Room-scoped provider authentication token used for node-task API "
            "requests. Treat this value as a secret and do not log or expose it "
            "to other room members."
        ),
    )
    token_expires_at: datetime | None = None


class RoomNodeGpuResponse(BaseModel):
    id: UUID
    peer_id: UUID
    room_id: UUID
    device_index: int
    name: str | None = None
    total_memory_mb: int
    available_memory_mb: int
    compute_capability: str | None = None
    gpu_type: str = "nvidia"
    state: str = "idle"
    utilization_percent: float | None = None
    temperature_celsius: float | None = None
    power_watts: float | None = None
    is_active: bool = True
    last_updated: datetime


class RoomNodePathResponse(BaseModel):
    path_type: str = "unknown"
    path_class: str = "wan"
    coordinator_rtt_ms: float | None = None
    measurement_kind: str = "estimated"
    freshness_at: datetime | None = None
    p2p_rtt_ms: float | None = None
    bandwidth_mbps: float | None = None
    is_measured: bool = False


class RoomNodeCapabilitiesSummary(BaseModel):
    gpu_count: int = 0
    reported_at: datetime | str | None = None
    cuda_version: str | None = None
    pytorch_version: str | None = None
    driver_version: str | None = None
    runtime: dict[str, object] = Field(default_factory=dict)
    topology: dict[str, object] = Field(default_factory=dict)
    pairwise_paths: list[dict[str, object]] = Field(default_factory=list)


class RoomNodeResponse(BaseModel):
    id: UUID
    room_id: UUID
    user_id: UUID
    username: str
    vpn_ip: str
    status: str
    is_gpu_host: bool
    is_online: bool
    last_seen: datetime
    gpu_count: int = 0
    available_gpu_count: int = 0
    total_memory_mb: int = 0
    available_memory_mb: int = 0
    node_name: str | None = None
    agent_version: str | None = None
    provider_mode: str | None = None
    revoked_at: datetime | None = None
    health_state: str | None = None
    health_reason: str | None = None
    last_claim_at: datetime | None = None
    recent_failures: int = 0
    capabilities: RoomNodeCapabilitiesSummary | None = None
    path: RoomNodePathResponse | None = None


class RoomNodeHeartbeatGpu(BaseModel):
    device_index: int
    name: str | None = None
    total_memory_mb: int
    available_memory_mb: int
    compute_capability: str | None = None
    gpu_type: str = "nvidia"
    state: str = "idle"
    utilization_percent: float | None = None
    temperature_celsius: float | None = None
    power_watts: float | None = None


class RoomNodeHeartbeatCapabilities(BaseModel):
    """Optional extended capability inventory on heartbeat."""

    runtime: dict[str, object] | None = None
    topology: dict[str, object] | None = None
    gpus: list[RoomNodeHeartbeatGpu] | None = None
    pairwise_paths: list[dict[str, object]] | None = None


class RoomNodeHeartbeatPath(BaseModel):
    path_type: str | None = Field(default=None, max_length=32)
    path_class: str | None = Field(default=None, max_length=32)
    coordinator_rtt_ms: float | None = None
    measurement_kind: str | None = Field(default=None, max_length=32)
    p2p_rtt_ms: float | None = None
    bandwidth_mbps: float | None = None


class RoomNodeHeartbeatRequest(BaseModel):
    gpu_status: list[RoomNodeHeartbeatGpu] = Field(default_factory=list)
    is_online: bool = True
    endpoint: str | None = None
    agent_version: str | None = Field(default=None, max_length=64)
    node_name: str | None = Field(default=None, max_length=255)
    provider_mode: str | None = Field(default=None, max_length=32)
    capabilities: RoomNodeHeartbeatCapabilities | None = None
    path: RoomNodeHeartbeatPath | None = None
    # Agent-measured RTT shortcut (also accepted via path.coordinator_rtt_ms).
    coordinator_rtt_ms: float | None = None


class RoomProviderRevokeResponse(BaseModel):
    """Result of host/admin provider revocation."""

    peer_id: UUID
    room_id: UUID
    revoked_at: datetime
    failed_assignments: int = 0
