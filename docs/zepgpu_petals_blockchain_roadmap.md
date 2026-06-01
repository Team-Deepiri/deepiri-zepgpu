# ZepGPU Petals-Inspired Distributed GPU Room Network Roadmap

## Overview



The updated direction is:

> ZepGPU should evolve into a Petals-inspired distributed GPU room/network system. A host should be able to create a room, generate a virtualized network, invite GPU clients through built-in VPN credentials, view connected participants and their GPU metrics, and dispatch workloads across those connected machines.

## Final Review Direction

The latest review clarified the product direction:

- **No blockchain at this moment.**
- Do a deeper dive into the **Petals** repository and architecture.
- Understand architectural approaches Petals uses so ZepGPU can integrate similar ideas.
- Refactor the phases roadmap / implementation plan to be inspired by Petals.
- Focus on the user flow where a host creates a room/network, clients connect through VPN/config credentials, and connected GPU clients become visible and usable from the UI.

Blockchain is therefore **deferred**. It is not part of the active implementation plan. The near-term roadmap should focus on rooms, built-in VPN networking, node discovery, GPU capability reporting, metrics, distributed scheduling, and remote execution.

---

## Current ZepGPU Baseline

ZepGPU is currently a serverless GPU framework for kernel-as-a-service computing. The current system already includes or has been actively validating:

- FastAPI backend
- React/TypeScript frontend
- PostgreSQL persistence
- Redis/Celery task queue
- S3/MinIO result storage
- Docker and Kubernetes support
- JWT authentication
- Task submission and execution
- Multi-stage pipelines
- WebSocket monitoring
- Callback webhooks
- GPU tracking
- Prometheus/Grafana monitoring
- VPN-related backend/frontend work already present in the repo

The existing foundation is useful, but it is currently strongest as a centralized or cluster-local execution platform. The next major direction should turn ZepGPU into a **host-created distributed GPU room network**.

---

## Target User Experience

The desired user experience should look like this:

1. A user becomes a **host master**.
2. The host creates a **room**.
3. Creating the room creates or configures a **virtualized private network**.
4. ZepGPU generates connection credentials/configuration for other clients.
5. Other users/machines connect to the room through the built-in VPN.
6. Connected clients appear in the host UI.
7. The host can see:
   - who is connected
   - what GPUs they have
   - current GPU utilization
   - VRAM usage
   - node health
   - latency/connection status
   - task availability
8. The host can dispatch workloads to connected GPU clients.
9. ZepGPU schedules and combines utilization through async queues, distributed task routing, and eventually more advanced workload partitioning inspired by Petals.
10. The system can later be cloud-hosted or simulated locally for development.

This creates the bridge between the current ZepGPU task framework and the Petals-inspired distributed GPU network.

---

## Petals Architecture Deep Dive

Petals is an open-source BigScience project for collaborative inference and fine-tuning of large language models. Petals lets users run large models by connecting to a distributed network where peers host different parts of the model. The project describes this as running LLMs "BitTorrent-style."

### Key Architecture Concepts From Petals

ZepGPU should study and adapt these Petals concepts:

## 1. Peer Roles

Petals supports machines acting as:

- **Client**: sends requests into the network.
- **Server/peer**: hosts model blocks and serves compute.
- **Hybrid node**: can both use the network and contribute compute.

### ZepGPU Equivalent

ZepGPU should define:

- **Host master**: creates and manages a room.
- **Provider node**: joins the room and contributes GPU compute.
- **Requester/client**: submits workloads.
- **Coordinator/scheduler**: assigns work to available nodes.
- **Monitor/auditor**: tracks metrics, health, usage, and task events.

---

## 2. Peer Discovery

Petals uses a distributed network approach where clients can discover peers that host the model blocks they need.

### ZepGPU Equivalent

ZepGPU needs a room-scoped discovery layer:

- When a room is created, it should have a registry of connected nodes.
- Nodes should register when they connect through VPN.
- Nodes should advertise GPU capabilities.
- Scheduler should discover which nodes are available for work.

---

## 3. Resource Advertisement

Petals peers advertise what model blocks they can serve and their availability.

### ZepGPU Equivalent

ZepGPU nodes should advertise:

- GPU count
- GPU model/name
- VRAM total and available
- CUDA version
- driver version
- current utilization
- current memory usage
- supported runtimes
- active task count
- network latency
- health status
- heartbeat timestamp

---

## 4. Routing

Petals routes inference through peers that host different model blocks.

### ZepGPU Equivalent

ZepGPU should route work to the best available GPU node based on:

- GPU memory requirement
- GPU type
- node health
- node queue depth
- room membership
- latency
- provider availability
- task priority
- namespace/user quotas
- expected runtime

The first version should route whole tasks or pipeline stages. Later versions can research partitioning workloads across multiple nodes.

---

## 5. Fault Tolerance

Petals must handle unreliable peers because devices can leave or fail.

### ZepGPU Equivalent

ZepGPU must handle:

- provider disconnects
- missed heartbeats
- node crashes
- task timeout
- task retry
- rerouting work to another node
- marking nodes unhealthy
- preserving audit logs for failures

---

## 6. Workload Partitioning

Petals partitions LLMs into blocks/layers across peers.

### ZepGPU Equivalent

ZepGPU should not immediately split arbitrary Python functions across machines. That is too complex for the first version.

Instead:

1. Start with whole-task remote dispatch.
2. Then support pipeline-stage distribution.
3. Then research model-specific partitioning.
4. Only later consider Petals-style model sharding for LLM workloads.

---

## 7. Network Coordination

Petals relies on network coordination so clients can locate and use available peer compute.

### ZepGPU Equivalent

ZepGPU should coordinate rooms using:

- a host/coordinator service
- built-in VPN connectivity
- node registration
- node heartbeat
- capability reporting
- task assignment APIs
- WebSocket streams for real-time UI updates

---

# Updated Implementation Roadmap

## Phase Status Legend

- `[ ]` Not started
- `[~]` In progress / partially complete
- `[x]` Completed
- `[?]` Needs design decision

---

# Phase A: Stabilize Current ZepGPU Foundation — IN PROGRESS

## Goal

Finish stabilizing the current ZepGPU foundation so the distributed room/network architecture has a reliable base.

## Checklist

- [~] Complete Phase 8 integration validation
- [x] Verify Docker Compose local stack starts
- [x] Verify JWT authentication flow
- [x] Verify task creation, retrieval, result endpoint, and no-op execution
- [x] Verify pipeline creation and execution
- [x] Verify callback webhooks fire correctly
- [x] Verify WebSocket task stream connection, ping, and status responses
- [ ] Add Redis retry logic
- [ ] Review and harden GPU allocation race-condition handling
- [ ] Add validation so invalid `func_name` values fail early
- [ ] Update README quick start guide
- [ ] Add API examples
- [ ] Add deployment troubleshooting guide

## Proposed File/Module Changes

- `deepiri_zepgpu/api/server/routes/tasks.py`
  - Add `func_name` validation.
  - Keep UUID/string ownership checks consistent.
  - Keep response serialization safe.
- `deepiri_zepgpu/api/server/routes/pipelines.py`
  - Keep pipeline ownership checks consistent.
  - Keep pipeline Celery enqueue explicit.
- `deepiri_zepgpu/queue/tasks.py`
  - Keep callback hooks using database task ID, not Celery job ID.
  - Keep callback payload JSON-safe.
- `deepiri_zepgpu/database/session.py`
  - Keep async DB behavior stable inside Celery.
- `docker/docker-compose.yml`
  - Keep workers listening to required queues.
  - Add any missing local service dependencies.
- `README.md`
  - Add updated local quick start.
- `docs/deployment_troubleshooting.md`
  - Add common local startup and Docker issues.

## Acceptance Criteria

- `docker compose up -d --build` starts required services.
- `GET /api/v1/health` returns healthy backend status.
- Swagger/OpenAPI loads at `/docs`.
- User can register, login, authorize, and access protected routes.
- User can create a task and retrieve task status.
- Celery receives and executes a no-op task.
- Callback webhook fires on task completion.
- WebSocket `/api/v1/ws/tasks` accepts JWT token and responds to `ping`.
- Pipeline can be created and run successfully.
- Redis retry behavior is documented or implemented.
- GPU allocation logic has documented race-condition review.

---

# Phase B: Host Room and Virtual Network Layer — PLANNED

## Goal

Allow a host master to create a ZepGPU room that represents a private virtual GPU network.

## Main Concept

A room is the user-facing object that groups connected GPU clients. The room should act like the "network container" for connected provider nodes.

## Checklist

- [ ] Add `gpu_rooms` database model
- [ ] Add `gpu_room_members` database model
- [ ] Add room creation endpoint
- [ ] Add room list/detail endpoints
- [ ] Add room delete/archive endpoint
- [ ] Add host ownership rules
- [ ] Add room status states
- [ ] Add UI page for room creation
- [ ] Add UI page for room details
- [ ] Add room membership display

## Database Tables

### `gpu_rooms`

```sql
CREATE TABLE gpu_rooms (
    id UUID PRIMARY KEY,
    host_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    namespace_id UUID NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active',
    network_mode VARCHAR(50) DEFAULT 'vpn',
    coordinator_url VARCHAR(500),
    vpn_network_id UUID NULL,
    max_nodes INTEGER DEFAULT 32,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### `gpu_room_members`

```sql
CREATE TABLE gpu_room_members (
    id UUID PRIMARY KEY,
    room_id UUID REFERENCES gpu_rooms(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    node_id UUID NULL,
    role VARCHAR(50) DEFAULT 'provider',
    status VARCHAR(50) DEFAULT 'invited',
    joined_at TIMESTAMP,
    left_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/rooms` | Create GPU room |
| `GET` | `/api/v1/rooms` | List rooms |
| `GET` | `/api/v1/rooms/{room_id}` | Get room details |
| `DELETE` | `/api/v1/rooms/{room_id}` | Delete/archive room |
| `GET` | `/api/v1/rooms/{room_id}/members` | List room members |
| `POST` | `/api/v1/rooms/{room_id}/members/{member_id}/remove` | Remove member |

## Proposed File/Module Changes

- `deepiri_zepgpu/database/models/gpu_room.py`
- `deepiri_zepgpu/database/models/gpu_room_member.py`
- `deepiri_zepgpu/database/repositories/room_repository.py`
- `deepiri_zepgpu/api/server/routes/rooms.py`
- `alembic/versions/<new>_add_gpu_rooms.py`
- `zepgpu-ui/src/pages/Rooms.tsx`
- `zepgpu-ui/src/pages/RoomDetail.tsx`
- `zepgpu-ui/src/api/client.ts`
- `zepgpu-ui/src/types/index.ts`

## Acceptance Criteria

- Host user can create a room.
- Room appears in API list.
- Room detail page shows host, status, and members.
- Only host/admin can manage room membership.
- Room can later attach to VPN network configuration.

---

# Phase C: Built-In VPN Join Flow — PLANNED

## Goal

Allow clients to join a host-created room using generated VPN/config credentials.

## Main Concept

A host should create a room and generate connection configurations. Clients use those configs to tap into the room's virtual network.

## Checklist

- [ ] Reuse or extend existing VPN models/routes
- [ ] Add room-to-VPN network mapping
- [ ] Add invite/config generation
- [ ] Add one-time or expiring join credentials
- [ ] Add client join endpoint
- [ ] Add connected/disconnected status tracking
- [ ] Add UI for copying/downloading join configs
- [ ] Add UI for connected clients
- [ ] Add local simulation path for testing without real cloud

## Database Tables

### `room_invites`

```sql
CREATE TABLE room_invites (
    id UUID PRIMARY KEY,
    room_id UUID REFERENCES gpu_rooms(id) ON DELETE CASCADE,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    invite_code VARCHAR(255) UNIQUE NOT NULL,
    max_uses INTEGER DEFAULT 1,
    uses INTEGER DEFAULT 0,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### `room_connection_configs`

```sql
CREATE TABLE room_connection_configs (
    id UUID PRIMARY KEY,
    room_id UUID REFERENCES gpu_rooms(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    node_id UUID NULL,
    config_type VARCHAR(50) DEFAULT 'vpn',
    config_payload JSONB NOT NULL,
    revoked BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT NOW(),
    revoked_at TIMESTAMP
);
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/rooms/{room_id}/invites` | Create room invite |
| `GET` | `/api/v1/rooms/{room_id}/invites` | List room invites |
| `POST` | `/api/v1/rooms/join` | Join room with invite/config |
| `POST` | `/api/v1/rooms/{room_id}/connection-config` | Generate VPN/client config |
| `POST` | `/api/v1/rooms/{room_id}/connection-config/{config_id}/revoke` | Revoke config |
| `GET` | `/api/v1/rooms/{room_id}/connections` | List connected clients |

## Proposed File/Module Changes

- `deepiri_zepgpu/database/models/room_invite.py`
- `deepiri_zepgpu/database/models/room_connection_config.py`
- `deepiri_zepgpu/api/server/routes/room_invites.py`
- `deepiri_zepgpu/api/server/routes/room_connections.py`
- `deepiri_zepgpu/vpn/room_network.py`
- `deepiri_zepgpu/vpn/config_generator.py`
- `zepgpu-ui/src/pages/RoomInvites.tsx`
- `zepgpu-ui/src/components/ConnectionConfigPanel.tsx`

## Acceptance Criteria

- Host can generate a join invite/config.
- Client can join a room using credentials.
- Host can see connected clients.
- Configs can be revoked.
- Local/dev simulation works even without real cloud deployment.

---

# Phase D: GPU Node Discovery and Metrics — PLANNED

## Goal

Once clients connect to a room, they should become GPU provider nodes that report metrics and availability.

## Checklist

- [ ] Add `gpu_nodes` database model
- [ ] Add `gpu_node_devices` database model
- [ ] Add Alembic migration for node tables
- [ ] Add node registration endpoint
- [ ] Add node heartbeat endpoint
- [ ] Add node list/detail endpoints
- [ ] Add node drain endpoint
- [ ] Add GPU capability reporting
- [ ] Add node health states
- [ ] Build first `zepgpu-node-agent` prototype
- [ ] Add node status visibility in room UI

## Database Tables

### `gpu_nodes`

```sql
CREATE TABLE gpu_nodes (
    id UUID PRIMARY KEY,
    room_id UUID REFERENCES gpu_rooms(id) ON DELETE CASCADE,
    owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    namespace_id UUID NULL,
    node_name VARCHAR(255) NOT NULL,
    hostname VARCHAR(255),
    public_address VARCHAR(500),
    private_address VARCHAR(500),
    vpn_ip VARCHAR(100),
    region VARCHAR(100),
    status VARCHAR(50) DEFAULT 'unknown',
    node_version VARCHAR(100),
    agent_version VARCHAR(100),
    supported_runtimes JSONB DEFAULT '[]',
    capabilities JSONB DEFAULT '{}',
    trust_level VARCHAR(50) DEFAULT 'unverified',
    last_heartbeat_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### `gpu_node_devices`

```sql
CREATE TABLE gpu_node_devices (
    id UUID PRIMARY KEY,
    node_id UUID REFERENCES gpu_nodes(id) ON DELETE CASCADE,
    device_index INTEGER NOT NULL,
    uuid VARCHAR(255),
    name VARCHAR(255),
    gpu_type VARCHAR(50),
    total_memory_mb BIGINT,
    available_memory_mb BIGINT,
    utilization_percent FLOAT,
    memory_utilization_percent FLOAT,
    temperature_celsius INTEGER,
    power_draw_watts FLOAT,
    driver_version VARCHAR(100),
    cuda_version VARCHAR(100),
    state VARCHAR(50) DEFAULT 'unknown',
    last_seen_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(node_id, device_index)
);
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/rooms/{room_id}/nodes/register` | Register provider node |
| `POST` | `/api/v1/nodes/{node_id}/heartbeat` | Update node health/capacity |
| `GET` | `/api/v1/rooms/{room_id}/nodes` | List room nodes |
| `GET` | `/api/v1/nodes/{node_id}` | Get node details |
| `POST` | `/api/v1/nodes/{node_id}/drain` | Mark node as draining |
| `POST` | `/api/v1/nodes/{node_id}/disable` | Disable node scheduling |
| `GET` | `/api/v1/nodes/{node_id}/devices` | List node GPUs |

## Proposed File/Module Changes

- `deepiri_zepgpu/database/models/gpu_node.py`
- `deepiri_zepgpu/database/models/gpu_node_device.py`
- `deepiri_zepgpu/database/repositories/node_repository.py`
- `deepiri_zepgpu/api/server/routes/nodes.py`
- `deepiri_zepgpu/node_agent/agent.py`
- `deepiri_zepgpu/node_agent/config.py`
- `deepiri_zepgpu/node_agent/heartbeat.py`
- `deepiri_zepgpu/node_agent/gpu_reporter.py`
- `alembic/versions/<new>_add_gpu_nodes.py`
- `zepgpu-ui/src/pages/Nodes.tsx`
- `zepgpu-ui/src/components/RoomNodeMetrics.tsx`
- `zepgpu-ui/src/api/client.ts`
- `zepgpu-ui/src/types/index.ts`

## Acceptance Criteria

- A connected client can register as a room GPU node.
- Node appears under the host room.
- Node sends heartbeat updates.
- Node reports GPU metrics.
- Missed heartbeat marks node offline/unhealthy.
- Host UI shows connected nodes and GPU metrics.

---

# Phase E: Petals-Inspired Distributed Scheduler and Remote Execution — PLANNED

## Goal

Allow the host/coordinator to dispatch tasks to connected GPU nodes inside a room.

## Main Concept

The scheduler should pick the best connected node for a workload based on availability, GPU requirements, health, latency, and queue depth.

## Checklist

- [ ] Add `node_task_assignments` database model
- [ ] Add `node_task_events` database model
- [ ] Add room-aware scheduling policy
- [ ] Add node-aware scheduling policy
- [ ] Add remote task assignment flow
- [ ] Add remote task accept/reject flow
- [ ] Add remote execution lifecycle states
- [ ] Add remote result return path
- [ ] Add node failure detection
- [ ] Add retry/reroute logic for failed nodes
- [ ] Support distributed pipeline stage routing
- [ ] Add tests for node assignment and rerouting

## Database Tables

### `node_task_assignments`

```sql
CREATE TABLE node_task_assignments (
    id UUID PRIMARY KEY,
    room_id UUID REFERENCES gpu_rooms(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    node_id UUID REFERENCES gpu_nodes(id) ON DELETE SET NULL,
    device_id UUID REFERENCES gpu_node_devices(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'assigned',
    assigned_at TIMESTAMP DEFAULT NOW(),
    accepted_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    failed_at TIMESTAMP,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### `node_task_events`

```sql
CREATE TABLE node_task_events (
    id UUID PRIMARY KEY,
    room_id UUID REFERENCES gpu_rooms(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    node_id UUID REFERENCES gpu_nodes(id) ON DELETE SET NULL,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/rooms/{room_id}/tasks/{task_id}/assign` | Assign task to room node |
| `POST` | `/api/v1/node-tasks/{task_id}/accept` | Node accepts task |
| `POST` | `/api/v1/node-tasks/{task_id}/start` | Node reports task started |
| `POST` | `/api/v1/node-tasks/{task_id}/complete` | Node reports task completed |
| `POST` | `/api/v1/node-tasks/{task_id}/fail` | Node reports task failed |
| `POST` | `/api/v1/node-tasks/{task_id}/logs` | Node sends logs |
| `GET` | `/api/v1/node-tasks/{task_id}/assignment` | Get node assignment |

## Proposed File/Module Changes

- `deepiri_zepgpu/core/distributed_scheduler.py`
- `deepiri_zepgpu/core/node_selector.py`
- `deepiri_zepgpu/core/node_health.py`
- `deepiri_zepgpu/api/server/routes/node_tasks.py`
- `deepiri_zepgpu/database/models/node_task_assignment.py`
- `deepiri_zepgpu/database/models/node_task_event.py`
- `deepiri_zepgpu/database/repositories/node_task_repository.py`
- `deepiri_zepgpu/node_agent/task_runner.py`
- `deepiri_zepgpu/node_agent/result_uploader.py`
- `deepiri_zepgpu/node_agent/log_streamer.py`

## Scheduling Policy Inputs

- Room membership
- Required GPU memory
- GPU type
- Node health
- Node availability
- Queue depth
- Estimated wait time
- User quota
- Namespace quota
- Provider reliability
- Network latency
- Task priority

## Acceptance Criteria

- Scheduler can select a healthy node inside a room.
- Task assignment record is created.
- Node agent receives or polls assigned task.
- Node agent can execute no-op task.
- Coordinator receives completion update.
- Task status changes from pending → assigned → running → completed.
- Failed node assignment can be retried on another node.
- Assignment history is visible through API.

---

# Phase F: Host Master UI and Room Dashboard — PLANNED

## Goal

Build the UI experience the host master needs to manage the distributed GPU room.

## Checklist

- [ ] Add room creation page
- [ ] Add room detail dashboard
- [ ] Add invite/config generation UI
- [ ] Add connected clients list
- [ ] Add GPU metrics cards per node
- [ ] Add node health indicators
- [ ] Add task dispatch controls
- [ ] Add room activity/event log
- [ ] Add WebSocket updates for node metrics
- [ ] Add basic graph of total room compute

## UI Views

### Room List

Shows all rooms the user owns or belongs to.

### Room Detail

Shows:

- room name
- room status
- connection method
- host
- connected nodes
- connected users
- total GPUs
- total VRAM
- available VRAM
- running tasks
- node health

### Node Metrics Panel

Shows per-node:

- GPU name
- utilization
- memory usage
- temperature
- power draw
- active task
- latency
- last heartbeat

### Dispatch Panel

Allows the host to:

- choose a task/pipeline
- select auto-scheduling or specific node
- dispatch the workload
- watch status updates

## Proposed File/Module Changes

- `zepgpu-ui/src/pages/Rooms.tsx`
- `zepgpu-ui/src/pages/RoomDetail.tsx`
- `zepgpu-ui/src/components/RoomNodeList.tsx`
- `zepgpu-ui/src/components/RoomNodeMetrics.tsx`
- `zepgpu-ui/src/components/RoomInvitePanel.tsx`
- `zepgpu-ui/src/components/RoomDispatchPanel.tsx`
- `zepgpu-ui/src/components/RoomActivityLog.tsx`
- `zepgpu-ui/src/api/client.ts`
- `zepgpu-ui/src/types/index.ts`

## Acceptance Criteria

- Host can create room from UI.
- Host can generate invite/config from UI.
- Host can see connected clients.
- Host can see GPU metrics per connected node.
- Host can dispatch workload to room.
- UI updates status in near real time.

---

# Phase G: Workload Combination and Partitioning Research — RESEARCH

## Goal

Research how ZepGPU can combine utilization across connected GPUs using async queues, distributed execution, and memory-architecture-inspired approaches.

## Checklist

- [ ] Classify workload types
- [ ] Identify single-node workloads
- [ ] Identify distributed pipeline workloads
- [ ] Identify batch-parallel workloads
- [ ] Research model layer/block partitioning from Petals
- [ ] Research tensor parallelism
- [ ] Research pipeline parallelism
- [ ] Research async queue-based execution
- [ ] Research memory architecture-inspired scheduling
- [ ] Decide what ZepGPU should support first

## Practical Recommendation

Do not start with arbitrary multi-node function splitting.

Recommended order:

1. Whole task to one remote node.
2. Pipeline stages across different nodes.
3. Batch-parallel jobs across multiple nodes.
4. Model-specific partitioning for LLM workloads.
5. Advanced memory/pipeline parallel strategies.

## Proposed File/Module Changes

- `docs/distributed_workload_partitioning.md`
- `docs/model_partitioning_research.md`
- `deepiri_zepgpu/core/workload_classifier.py`
- `deepiri_zepgpu/core/pipeline_partition_planner.py`
- `deepiri_zepgpu/core/batch_distributor.py`

## Acceptance Criteria

- Workload categories are documented.
- Team decides first supported distributed workload type.
- Pipeline-stage distribution is selected as first practical target.
- Model sharding remains research until approved.
- Risks and constraints are documented.

---

# Phase H: Cloud / Decentralized Hosting Research — RESEARCH

## Goal

Decide how the host room/coordinator should run in real deployments.

## Context

If the system is only hosted from a local device with manual port forwarding, it is not truly decentralized or cloud-ready. A better architecture may require a cloud-hosted coordinator or relay so clients can join reliably.

## Options to Research

### Option 1: Local Host + Port Forwarding

Pros:

- Simple for early dev
- No cloud cost
- Easy to simulate

Cons:

- NAT/port issues
- not truly decentralized
- host machine must stay online
- poor reliability

### Option 2: Cloud-Hosted Coordinator

Pros:

- reliable room server
- easier for clients to connect
- better for production
- cleaner VPN management

Cons:

- cloud cost
- coordinator becomes centralized

### Option 3: Hybrid Coordinator + Local Providers

Pros:

- practical first production architecture
- providers still contribute local GPUs
- cloud only coordinates rooms, auth, and routing

Cons:

- still not fully decentralized
- requires cloud deployment work

### Option 4: Fully Decentralized Network

Pros:

- closest to Petals style
- no single central coordinator

Cons:

- hardest to build
- complex peer discovery
- harder auth/security
- harder UI/room management

## Recommendation

Start with:

> Hybrid coordinator + local provider nodes.

This allows ZepGPU to simulate and eventually deploy room-based distributed GPU networking without requiring full decentralization on day one.

## Acceptance Criteria

- Team chooses deployment architecture for room coordinator.
- Local simulation path is documented.
- Cloud deployment path is documented.
- NAT/VPN limitations are documented.

---

# Phase I: Blockchain Deferred — NOT ACTIVE

## Status

Blockchain is deferred based on final review.

## Current Decision

Blockchain should not be implemented at this moment.

The active direction is:

1. Petals-inspired room/network architecture
2. Built-in VPN join flow
3. GPU node discovery
4. Metrics visibility
5. Distributed scheduling
6. Remote execution
7. Cloud/decentralized hosting research

## When Blockchain May Be Revisited

Blockchain may be reconsidered later only if ZepGPU needs:

- marketplace payments
- provider identity
- public usage receipts
- reputation anchoring
- settlement between requesters and providers

## What Should Not Be Built Now

- token system
- smart contracts
- staking/slashing
- on-chain task execution
- on-chain result storage
- on-chain model artifact storage
- blockchain-required login

## Acceptance Criteria

- Blockchain is removed from active implementation phases.
- Roadmap focuses on Petals-inspired room/network architecture.
- Any blockchain discussion remains clearly marked as deferred.

---

# Proposed Updated Roadmap Summary

| Priority | Phase | Focus | Status |
|---|---|---|---|
| 1 | Phase A | Stabilize current ZepGPU foundation | In progress |
| 2 | Phase B | Host room and virtual network layer | Planned |
| 3 | Phase C | Built-in VPN join flow | Planned |
| 4 | Phase D | GPU node discovery and metrics | Planned |
| 5 | Phase E | Petals-inspired distributed scheduler and remote execution | Planned |
| 6 | Phase F | Host master UI and room dashboard | Planned |
| 7 | Phase G | Workload combination and partitioning research | Research |
| 8 | Phase H | Cloud/decentralized hosting research | Research |
| 9 | Phase I | Blockchain deferred | Not active |

---


# Sources

- Petals GitHub repository: https://github.com/bigscience-workshop/petals
- Petals project site: https://petals.dev/
- Petals ACL paper: https://aclanthology.org/2023.acl-demo.54/
- Petals arXiv paper: https://arxiv.org/abs/2209.01188
- Yandex Research Petals explainer: https://research.yandex.com/blog/petals-decentralized-inference-and-finetuning-of-large-language-models
- Existing ZepGPU README and implementation plan