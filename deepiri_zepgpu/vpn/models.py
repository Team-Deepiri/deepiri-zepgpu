"""Pydantic schemas for VPN API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PeerBase(BaseModel):
    wireguard_public_key: str
    endpoint: Optional[str] = None
    is_gpu_host: bool = False


class PeerRegisterRequest(PeerBase):
    vpn_network_id: str
    is_relay: bool = False


class PeerHeartbeatRequest(BaseModel):
    peer_id: str
    gpu_status: list["GpuStatusPayload"] = Field(default_factory=list)
    is_online: bool = True
    endpoint: Optional[str] = None


class GpuStatusPayload(BaseModel):
    device_index: int
    name: Optional[str] = None
    total_memory_mb: int
    available_memory_mb: int
    compute_capability: Optional[str] = None
    gpu_type: str = "nvidia"
    state: str = "idle"
    utilization_percent: Optional[float] = None


class PeerResponse(BaseModel):
    id: str
    user_id: str
    username: str
    vpn_ip: str
    online_status: str
    is_gpu_host: bool
    is_online: bool
    last_seen: datetime
    gpu_count: int = 0

    class Config:
        from_attributes = True


class GpuShareResponse(BaseModel):
    id: str
    peer_id: str
    username: str
    device_index: int
    name: Optional[str]
    total_memory_mb: int
    available_memory_mb: int
    compute_capability: Optional[str]
    gpu_type: str
    state: str
    utilization_percent: Optional[float]
    is_active: bool
    last_updated: datetime

    class Config:
        from_attributes = True


class GpuPoolSummary(BaseModel):
    total_gpus: int
    total_memory_mb: int
    available_memory_mb: int
    online_peers: int
    online_gpu_hosts: int
    gpu_breakdown: list[GpuShareResponse]


class VpnNetworkCreate(BaseModel):
    name: str
    cidr: str = "10.8.0.0/24"
    listen_port: int = 51820
    relay_endpoint: Optional[str] = None


class VpnNetworkResponse(BaseModel):
    id: str
    name: str
    cidr: str
    listen_port: int
    relay_endpoint: Optional[str]
    is_active: bool
    peer_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class VpnConfigResponse(BaseModel):
    config_text: str
    vpn_ip: str
    peer_id: str


class NetworkInviteRequest(BaseModel):
    """Body for POST /vpn/networks/{id}/invite (network id is in the path)."""

    max_uses: int = 1
    expires_in_days: int = 7


class InviteResponse(BaseModel):
    id: str
    code: str
    vpn_network_id: str
    vpn_network_name: str
    max_uses: int
    used_count: int
    expires_at: Optional[datetime]
    is_revoked: bool
    created_at: datetime

    class Config:
        from_attributes = True


class JoinNetworkRequest(BaseModel):
    invite_code: str
    wireguard_public_key: Optional[str] = None
    is_gpu_host: bool = False


class FriendRequest(BaseModel):
    friend_id: str


class FriendResponse(BaseModel):
    id: str
    user_id: str
    username: str
    email: str
    status: str
    created_at: datetime
    accepted_at: Optional[datetime]

    class Config:
        from_attributes = True


class FriendListResponse(BaseModel):
    friends: list[FriendResponse]
    pending: list[FriendResponse]
    sent_requests: list[FriendResponse]


class TaskExecutionRequest(BaseModel):
    task_id: str
    func_encoded: str
    args_encoded: str
    kwargs_encoded: str
    gpu_device_id: int
    gpu_memory_mb: int
    timeout_seconds: int = 3600


class TaskExecutionResponse(BaseModel):
    task_id: str
    success: bool
    result_encoded: Optional[str] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    execution_time: float = 0.0


from pydantic import ConfigDict
