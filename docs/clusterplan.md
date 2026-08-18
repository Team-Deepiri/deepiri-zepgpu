# ZepGPU Network GPU Pool - Implementation Plan

## Overview

**Goal:** Enable local computers to share GPU compute via a WireGuard VPN, combining all GPUs into a single unified pool that any authorized user can tap into.

**Architecture:** Central relay server (runs on one machine, has the ZepGPU server) + WireGuard mesh VPN + peer nodes (friends who share their GPUs).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CENTRAL RELAY SERVER                     │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐  │
│  │ ZepGPU API │  │ Peer Hub   │  │ WireGuard Config Gen │  │
│  │ (existing) │  │ Registry   │  │                      │  │
│  └─────────────┘  └─────────────┘  └──────────────────────┘  │
│         ↑                ↑                   ↑             │
│         │         ┌──────┴──────┐            │             │
│  ┌──────┴─────────┴─────────────┴────────────┴───────┐     │
│  │              GPU Pool Aggregator                  │     │
│  │  (integrates remote GPUs into local scheduler)    │     │
│  └───────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
        │ WireGuard VPN Mesh │
        │ 10.8.0.0/24       │
        ▼                    ▼
┌───────────────┐    ┌───────────────┐
│  Peer Node A  │    │  Peer Node B  │
│  (GPU: RTX3090│    │  (GPU: A100)   │
│   24GB VRAM)  │    │   80GB VRAM)  │
│  ┌─────────┐  │    │  ┌─────────┐  │
│  │WireGuard│  │    │  │WireGuard│  │
│  │  Agent  │  │    │  │  Agent  │  │
│  └─────────┘  │    │  └─────────┘  │
│  ┌─────────┐  │    │  ┌─────────┐  │
│  │  GPU    │  │    │  │  GPU    │  │
│  │ Exposer │  │    │  │ Exposer │  │
│  └─────────┘  │    │  └─────────┘  │
└───────────────┘    └───────────────┘
```

### Data Flow

1. **Join Flow:** Peer installs WireGuard → gets config from relay → joins VPN network
2. **GPU Advertisement:** Peer agent queries local GPUs via NVML → reports to relay via secure WebSocket/REST
3. **Task Routing:** User submits task to relay → relay selects peer GPU → sends task over VPN → peer executes → returns result
4. **Invitation Flow:** User creates invite code → friend joins with code → auto-authorized

---

## New Dependencies

| Package | Purpose |
|---------|---------|
| `python-wireguard` / `wgconfig` | WireGuard config parsing |
| `websockets` | WebSocket communication (relay <-> peer) |
| `httpx` | HTTP client (already used) |
| `sqlalchemy` (already used) | Database |

---

## Database Models (New)

Location: `deepiri_zepgpu/database/models/`

### VpnNetwork
```
vpn_networks table:
- id: UUID (PK)
- name: str
- cidr: str (default "10.8.0.0/24")
- listen_port: int
- relay_endpoint: str (public IP/host of relay)
- created_at: datetime
```

### Peer
```
peers table:
- id: UUID (PK)
- user_id: FK → users.id
- vpn_network_id: FK → vpn_networks.id
- wireguard_public_key: str
- wireguard_private_key: str (encrypted)
- vpn_ip: str (e.g. "10.8.0.2")
- endpoint: str (peer public IP:port)
- last_seen: datetime
- is_online: bool
- is_gpu_host: bool
- created_at: datetime
```

### GpuShare (remote GPU entry)
```
gpu_shares table:
- id: UUID (PK)
- peer_id: FK → peers.id
- device_index: int
- name: str
- total_memory_mb: int
- available_memory_mb: int
- compute_capability: str
- state: str
- last_updated: datetime
- is_active: bool
```

### Friendship
```
friendships table:
- id: UUID (PK)
- user_id: FK → users.id
- friend_id: FK → users.id
- status: enum (pending/accepted/blocked)
- created_at: datetime
- accepted_at: datetime
```

### VpnInvite
```
vpn_invites table:
- id: UUID (PK)
- code: str (unique, 8-char)
- creator_id: FK → users.id
- vpn_network_id: FK → vpn_networks.id
- max_uses: int
- used_count: int
- expires_at: datetime
- created_at: datetime
```

### GpuShareQuota
```
gpu_share_quotas table:
- id: UUID (PK)
- peer_id: FK → peers.id
- max_gpu_hours_per_day: float
- max_concurrent_tasks: int
- priority_boost: int
```

---

## Module Structure

### New Modules

```
deepiri_zepgpu/vpn/
├── __init__.py
├── config.py              # VPN settings
├── keygen.py              # WireGuard key generation
├── models.py              # Pydantic models for VPN/Peer/GpuShare
├── peer_manager.py        # Peer lifecycle: register, heartbeat, deregister
├── gpu_exposer.py         # On peer: query local GPUs, advertise to relay
├── gpu_pool.py            # On relay: aggregate remote GPUs into unified pool
├── task_router.py         # Route tasks to remote peers, collect results
├── relay_client.py        # On peer: REST client to relay
├── wg_config.py           # Generate WireGuard .conf files
└── cli.py                 # CLI: vpn create-network, vpn join, vpn status, gpu advertise
```

---

## Implementation Steps

### Phase 1: Relay Server - Identity & Friends System

**1.1 Database models**
- New models: `VpnNetwork`, `Peer`, `Friendship`, `VpnInvite`
- Migration via Alembic
- Extend `User` model with relationships to friendships and invites

**1.2 Friends & Invites API**
- `POST /api/vpn/friends/invite` - create invite code
- `GET /api/vpn/friends/invites` - list invites
- `POST /api/vpn/friends/request` - send friend request
- `GET /api/vpn/friends` - list friends
- `POST /api/vpn/friends/{id}/accept` - accept friend request
- `POST /api/vpn/friends/{id}/block` - block user
- `POST /api/vpn/join` - join VPN using invite code

**1.3 Relay Hub API**
- `POST /api/vpn/networks` - create VPN network (admin)
- `GET /api/vpn/networks` - list networks user belongs to
- `GET /api/vpn/networks/{id}/peers` - list peers in network
- `GET /api/vpn/networks/{id}/config` - get WireGuard config for this peer
- `POST /api/vpn/networks/{id}/leave` - leave network

**1.4 WireGuard config generator**
- `wg genkey` → private key, `wg pubkey` → public key
- Generate per-peer .conf: `[Interface]`, `[Peer]` entries
- Store private key encrypted in DB
- API endpoint streams .conf file to peer

### Phase 2: Relay Server - Peer Registry & Heartbeat

**2.1 Peer registration**
- On first connect, peer receives persistent auth token
- Peer calls `POST /api/vpn/peers/register`
- Peer sends: public_key, endpoint, is_gpu_host

**2.2 Peer heartbeat**
- Peers send heartbeat every 30s via REST
- Heartbeat includes current GPU status (if gpu_host)
- Relay marks peer online/offline based on heartbeat
- Auto-removes peers that miss 3+ heartbeats

**2.3 GPU advertisement**
- Peer GPU agent queries NVML locally
- Sends GPU list to relay: name, memory, compute capability
- Relay stores in `gpu_shares` table
- Relay exposes aggregated GPU pool via `GET /api/vpn/gpu-pool`

### Phase 3: Peer Node - WireGuard Agent

**3.1 CLI commands (peer side)**
- `deepiri-gpu vpn join --config ./wg0.conf` - apply WireGuard config
- `deepiri-gpu gpu advertise` - start GPU advertising agent
- `deepiri-gpu vpn status` - show VPN and GPU status
- `deepiri-gpu gpu withdraw` - stop advertising GPUs

**3.2 WireGuard integration**
- Write .conf to `/etc/wireguard/wg0.conf`
- Use `wg-quick up wg0` to bring interface up (Linux)
- Detect OS: Linux (wg-quick), macOS (wg), Windows (WireGuardNT)
- Store .conf in `~/.zepgpu/wireguard/` with restricted permissions

**3.3 GPU Exposer**
- On peer node: lightweight HTTP server (port 9091)
- `GET /gpu/status` endpoint: local GPU list via NVML
- Relay uses heartbeat payload for GPU data

### Phase 4: Relay Server - GPU Pool Aggregator

**4.1 Remote GPU integration into scheduler**
- `GpuPool` class: aggregates local + remote GPUs
- `RemoteGPUDevice` dataclass: wraps remote GPU info
- Scheduler calls `gpu_manager.get_available_device()` spans local + remote
- The legacy WireGuard `TaskRouter` accepts only authenticated, room-scoped allowlisted messages;
  arbitrary callable execution is unsupported. Normal room execution uses node-task assignments.

**4.2 Task routing**
- Task arrives at relay scheduler
- If local GPU available → execute locally (existing flow)
- If remote GPU available → create a room-scoped node-task assignment
- The authenticated provider agent claims the assignment and returns a primitive result
- Relay stores result and notifies user

**4.3 GPU allocation tracking**
- Relay tracks allocation state for remote GPUs via Redis locks
- `acquire_remote_gpu(peer_id, gpu_id)` / `release_remote_gpu(peer_id, gpu_id)`

### Phase 5: Peer Node - Task Execution

**5.1 Task receiver on peer**
- Lightweight HTTP server on port 9092
- `POST /execute` - compatibility diagnostic endpoint for a fixed no-op message
- Sender-specific bearer authentication and HMAC integrity are required
- Pickle/base64 callable payloads are rejected without fallback
- Supported work is delivered through the authenticated node-task workflow

**5.2 Security**
- Peers accept only configured sender-specific bearer credentials
- Every request and response is room/sender/recipient scoped and HMAC protected
- The compatibility endpoint exposes only a fixed diagnostic no-op; it runs no submitted code
- Replay, expiry, duplicate task, malformed JSON, and oversized-message checks fail closed

### Phase 6: Frontend (zepgpu-ui)

**6.1 VPN Network Dashboard**
- My VPN networks list
- Create/join network
- Invite friends to network

**6.2 GPU Pool View**
- Total combined GPU pool: count, VRAM, compute capability
- Per-peer breakdown
- Real-time availability indicators
- Usage charts

**6.3 Friend Management**
- Friend list with online status
- Send/accept friend requests
- Invite codes management

### Phase 7: CLI Enhancements

**7.1 Admin commands**
- `deepiri-gpu vpn-admin networks list`
- `deepiri-gpu vpn-admin networks create --name "team-alpha"`
- `deepiri-gpu vpn-admin peers list`
- `deepiri-gpu vpn-admin gpu-pool status`

**7.2 User commands**
- `deepiri-gpu vpn invite --network-id <id> --expires 7d`
- `deepiri-gpu vpn join --code ABCD1234`
- `deepiri-gpu vpn status`
- `deepiri-gpu gpu-host start`
- `deepiri-gpu gpu-host stop`
- `deepiri-gpu gpu-host status`

---

## API Endpoints Summary

### Relay (existing server)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/vpn/networks` | Create VPN network |
| GET | `/api/vpn/networks` | List user's networks |
| GET | `/api/vpn/networks/{id}` | Get network details |
| POST | `/api/vpn/networks/{id}/leave` | Leave network |
| GET | `/api/vpn/networks/{id}/config` | Download WireGuard config |
| GET | `/api/vpn/networks/{id}/peers` | List peers in network |
| POST | `/api/vpn/networks/{id}/invite` | Create invite code |
| GET | `/api/vpn/invites` | List user's invites |
| DELETE | `/api/vpn/invites/{code}` | Revoke invite |
| POST | `/api/vpn/join` | Join with invite code |
| GET | `/api/vpn/friends` | List friends |
| POST | `/api/vpn/friends/request` | Send friend request |
| POST | `/api/vpn/friends/{id}/accept` | Accept friend request |
| POST | `/api/vpn/friends/{id}/block` | Block user |
| GET | `/api/vpn/gpu-pool` | Aggregated GPU pool status |
| GET | `/api/vpn/peers` | List peers |
| POST | `/api/vpn/peers/heartbeat` | Peer heartbeat |
| POST | `/api/vpn/peers/register` | Register peer |
| GET | `/api/vpn/peers/{id}/gpus` | Get peer's GPUs |

### Peer (on peer node, port 9092)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/execute` | Authenticated fixed no-op compatibility diagnostic |
| GET | `/health` | Health check |
| GET | `/gpu/status` | Local GPU status |

---

## Configuration Additions

In `config.py`, add `VPNSettings`:

```python
class VPNSettings(BaseSettings):
    relay_host: str = Field(default="relay.zepgpu.local")
    relay_port: int = Field(default=51820)
    vpn_cidr: str = Field(default="10.8.0.0/24")
    heartbeat_interval_seconds: int = Field(default=30)
    heartbeat_timeout_seconds: int = Field(default=90)
    default_max_gpu_hours_per_day: float = Field(default=4.0)
    peer_server_port: int = Field(default=9092)
    gpu_advertise_port: int = Field(default=9091)
    wg_config_dir: Path = Field(default=Path.home() / ".zepgpu" / "wireguard")
```

---

## Key Technical Decisions

### Why WireGuard over Tailscale?
- Full control over the mesh
- No dependency on third-party relay services
- WireGuard natively supported on Linux
- Can self-host the relay endpoint
- Lower latency at higher throughput

### Why a central relay for discovery?
- Solves NAT traversal (peers behind NAT can still advertise GPUs)
- Single source of truth for GPU pool state
- Invite-based auth built into the relay
- Simplifies peer-to-peer task routing (relay decides allocation)

### Why authenticated REST over WireGuard for compatibility diagnostics?
- WireGuard creates a full VPN tunnel — all traffic routes through it
- Peers get a VPN IP (e.g. 10.8.0.3), relay gets 10.8.0.1
- Strict JSON diagnostic messages are sent over the VPN; generic work uses node-task assignments
- The application protocol adds HMAC integrity, sender credentials, scope, expiry, and replay protection

### Security model
- Relay authenticates peers, and peer endpoints require sender-specific application credentials
- Friends list provides social authorization layer
- Invite codes are single-use with expiry
- The compatibility peer endpoint never executes submitted task functions
- Arbitrary callable/base64/pickle messages are rejected for every transport mode
- Supported remote work uses authenticated, room-scoped node-task assignments

---

## Testing Strategy

- Unit tests for keygen, wg config generation, GPU pool aggregation
- Integration tests: peer join → GPU advertise → task route → result
- VPN mesh tests: multiple peers, relay failover
- Security test: unauthorized peer cannot access tasks

---

## Backward Compatibility

- Existing ZepGPU API and flow remains unchanged
- VPN/GPU sharing is a new opt-in feature
- Existing deployments work without modification
- VPN components live in new `deepiri_zepgpu/vpn/` module
- No breaking changes to existing database models

---

## Implementation note (ZepGPU API layout)

The main FastAPI app mounts the API under **`/api/v1`**. VPN routes are registered with prefix **`/vpn`**, so the live relay paths are:

**`/api/v1/vpn/...`** (for example `POST /api/v1/vpn/join`, `GET /api/v1/vpn/gpu-pool`).

Tables in this document that show `/api/vpn/...` are shorthand for the same resources; clients (CLI, UI, peer heartbeat) should use the **`/api/v1/vpn`** prefix unless you add a separate legacy mount.
