# ZepGPU - Petals-Inspired Room Network Implementation Plan



## Project Vision

ZepGPU should evolve from a serverless GPU task framework into a **host-created distributed GPU room network**.

A host should be able to:

- Create a GPU room.
- Generate or attach a virtual private network for that room.
- Invite other users or machines through VPN/config credentials.
- See connected clients in the UI.
- See each client's GPU metrics and compute availability.
- Dispatch tasks or pipeline stages to connected GPU clients.
- Track task execution, node health, failures, and results in real time.

This direction is inspired by Petals, but ZepGPU should not copy Petals directly. Petals is focused on distributed LLM inference/fine-tuning. ZepGPU should first apply the same architectural principles to room-scoped GPU discovery, routing, fault tolerance, and remote execution.

---

# Current Codebase Baseline

The current repo already contains major pieces that should be reused instead of rebuilt from scratch.

## Existing Systems to Reuse

- `deepiri_zepgpu/api/server/routes/vpn.py`
  - Existing VPN and GPU sharing API routes.
  - Already supports networks, invites, joining, configs, peers, heartbeats, GPU pool, and peer listing.

- `deepiri_zepgpu/database/models/vpn_models.py`
  - Existing VPN database models.
  - Includes VPN networks, peers, GPU shares, invites, friendships, and quotas.

- `deepiri_zepgpu/vpn/repositories.py`
  - Existing repository layer for VPN networks, peers, GPU shares, invites, and peer heartbeat updates.

- `deepiri_zepgpu/vpn/models.py`
  - Existing Pydantic schemas for VPN requests and responses.
  - Includes peer registration, heartbeat, GPU status payloads, invites, joining, config responses, and GPU pool summaries.

- `zepgpu-ui/src/pages/Vpn.tsx`
  - Existing frontend page for networks, invite codes, joining, configs, peers, and GPU pool display.

- `zepgpu-ui/src/api/client.ts`
  - Existing frontend API client with VPN API support.

- `zepgpu-ui/src/types/index.ts`
  - Existing frontend types for VPN networks, peers, GPU shares, invites, and config responses.

## Mapping Existing Code to New Product Language

| Current Concept | New Product Concept | Recommendation |
|---|---|---|
| `VpnNetwork` | GPU Room / Room Network | Reuse as the first room network backend model or wrap with a `GpuRoom` abstraction |
| `Peer` | Connected room client / provider node | Reuse as the connected client identity inside a room |
| `GpuShare` | Provider GPU inventory / metrics | Reuse for GPU reporting and host dashboard metrics |
| `VpnInvite` | Room invite / join credential | Reuse for generated room join codes |
| `Vpn.tsx` | Room dashboard starting point | Refactor into room-oriented UI |
| `PeerHeartbeatRequest` | Node heartbeat | Reuse and extend for room-scoped node health |
| `GpuPoolSummary` | Room compute summary | Reuse for total room GPU capacity |

---

# Implementation Phases

Only implementation tasks that directly require code, docs, tests, or repo changes use checklist boxes. Explanatory sections, recommendations, acceptance criteria, and review criteria are written as plain bullets so the checklist stays focused on work that can actually be completed in the repo.

## Phase 0: Complete Original Phase 8 Stabilization — IN PROGRESS

**Goal:** Finish the original ZepGPU Phase 8 integration validation before building the Petals-inspired room/network layer.

This phase maps directly to the original implementation plan's **Phase 8: Integration Testing & End-to-End Validation**. It remains the foundation for the new room architecture because rooms, VPN joining, node discovery, remote dispatch, callbacks, and live dashboards all depend on the current local stack being stable.

### 0.1 End-to-End Testing

- [x] Run Docker Compose and verify local stack startup.
- [x] Verify backend container starts.
- [x] Verify frontend container starts.
- [x] Verify PostgreSQL container starts.
- [x] Verify Redis container starts.
- [x] Verify Celery workers start.
- [x] Verify Celery beat starts.
- [x] Verify Swagger/OpenAPI loads.
- [x] Validate JWT authentication flow.
- [x] Verify user registration.
- [x] Verify login returns access token.
- [x] Verify protected auth route works.
- [x] Verify authorized task creation.
- [x] Verify task retrieval.
- [x] Verify task result endpoint.
- [x] Verify Celery receives task.
- [x] Verify Celery executes no-op task.
- [x] Verify task completes successfully.
- [x] Test pipeline creation and execution.
- [x] Verify callback webhooks fire correctly.
- [x] Test WebSocket real-time updates.

### 0.2 Integration Fixes

- [x] Fix async/await issues in `ResultStore`.
- [x] Handle local S3/MinIO connection errors gracefully.
- [x] Fix password verification/login issue.
- [x] Fix task ownership UUID/string comparison.
- [x] Fix task response UUID serialization.
- [x] Fix Celery default queue listener.
- [x] Fix asyncpg/Celery event-loop issue.
- [x] Fix pipeline ownership UUID/string comparison.
- [x] Fix pipeline response UUID serialization.
- [x] Fix pipeline Celery enqueue path.
- [x] Fix callback webhook DB task ID issue.
- [x] Fix callback payload UUID serialization.
- [ ] Add explicit Redis retry logic.
- [ ] Review and harden GPU allocation race-condition handling.
- [ ] Add validation so invalid `func_name` values fail early.

### 0.3 Documentation Tasks From Original Phase 8

- [x] Update README quick start guide with current Docker Compose flow.
- [x] Add API documentation with examples for auth, tasks, pipelines, callbacks, and WebSockets.
- [x] Create deployment troubleshooting guide for Docker, Redis, Postgres, Celery, MinIO/S3, and GPU/NVIDIA runtime issues.

### 0.4 Proposed Files/Modules To Finish or Review

- [ ] `deepiri_zepgpu/api/server/routes/tasks.py`
  - Keep task ownership checks safe.
  - Keep task response serialization safe.
  - Add `func_name` validation.
- [ ] `deepiri_zepgpu/api/server/routes/pipelines.py`
  - Keep pipeline ownership checks safe.
  - Keep Celery enqueue explicit.
- [ ] `deepiri_zepgpu/queue/tasks.py`
  - Keep callbacks using the database task ID, not the Celery job ID.
  - Keep callback payloads JSON-safe.
- [ ] `deepiri_zepgpu/database/session.py`
  - Keep async DB behavior safe inside Celery workers.
- [ ] `deepiri_zepgpu/storage/result_store.py`
  - Keep local MinIO/S3 failure graceful.
- [ ] `docker/docker-compose.yml`
  - Ensure workers listen to required queues.
  - Ensure dependencies and healthchecks support local development.
- [ ] `README.md`
  - Update current quick start.
- [ ] `docs/deployment_troubleshooting.md`
  - Add common startup/debugging issues.

### 0.5 Acceptance Criteria

- `docker compose up -d --build` starts required services.
- `GET /api/v1/health` returns healthy backend status.
- Swagger/OpenAPI loads at `/docs`.
- User can register, login, authorize, and access protected routes.
- User can create a task and retrieve task status/result.
- Celery receives and executes a no-op task.
- Pipeline can be created and run successfully.
- Callback webhook fires on task completion.
- WebSocket `/api/v1/ws/tasks` accepts a JWT token and responds to `ping`.
- Redis retry behavior is implemented or explicitly documented.
- GPU allocation race-condition review is documented.
- README/API/troubleshooting docs are updated.

---

## Phase 1: Refactor Product Language Around Rooms

**Goal:** Keep existing VPN functionality but expose it as a host-created GPU room/network experience.

### 1.1 Backend Route Strategy

- [ ] Keep existing `/api/v1/vpn/*` routes working for compatibility.
- [ ] Add new room-facing API routes under `/api/v1/rooms/*`.
- [ ] Internally reuse existing VPN repositories where possible.
- [ ] Do not duplicate VPN logic unless needed.
- [ ] Add room terminology to schemas and responses.

### 1.2 New Route File

- [ ] Create `deepiri_zepgpu/api/server/routes/rooms.py`.
- [ ] Register `rooms.py` in `deepiri_zepgpu/api/server/routes/__init__.py` or the main router wiring.
- [ ] Add tags such as `Rooms` or `GPU Rooms`.

### 1.3 Room API Wrappers

Implement room wrappers around existing VPN logic:

- [ ] `POST /api/v1/rooms`
  - Creates a room.
  - Internally creates or maps to a `VpnNetwork`.

- [ ] `GET /api/v1/rooms`
  - Lists rooms available to the current user.
  - Internally calls `VpnNetworkRepository.list_user_networks()`.

- [ ] `GET /api/v1/rooms/{room_id}`
  - Gets room details.
  - Maps room ID to VPN network ID or room wrapper model.

- [ ] `DELETE /api/v1/rooms/{room_id}`
  - Archives/deactivates room if supported.
  - Should not hard-delete active peer history without design review.

- [ ] `GET /api/v1/rooms/{room_id}/members`
  - Lists peers/connected clients.
  - Internally reuses `PeerRepository.get_by_network()`.

- [ ] `GET /api/v1/rooms/{room_id}/gpu-pool`
  - Returns room GPU summary.
  - Reuses `GpuShareRepository.list_by_network()` or existing pool sync utilities.

### 1.4 Schema Changes

- [ ] Add room-specific schemas to `deepiri_zepgpu/vpn/models.py` or a new `deepiri_zepgpu/rooms/models.py`.
- [ ] Suggested schemas:
  - [ ] `RoomCreateRequest`
  - [ ] `RoomResponse`
  - [ ] `RoomMemberResponse`
  - [ ] `RoomGpuPoolSummary`
  - [ ] `RoomConnectionConfigResponse`

### 1.5 Acceptance Criteria

- Host can create a room through `/api/v1/rooms`.
- Creating a room creates or links to a VPN network.
- Current VPN routes still work.
- Current VPN UI does not break.
- Room list returns rooms/networks for authenticated user.
- Room details show name, status, network mode, peer count, and created time.

---

## Phase 2: Wire Built-In VPN Join Flow Into Rooms

**Goal:** Make room joining feel like a product-level room invite/config flow instead of a raw VPN operation.

### 2.1 Existing Code to Reuse

- `VpnInviteRepository`
- `create_invite()` route in `vpn.py`
- `join_network()` route in `vpn.py`
- `generate_peer_config()` in `deepiri_zepgpu/vpn/wg_config.py`
- `allocate_vpn_ip()` in `deepiri_zepgpu/vpn/wg_config.py`
- `generate_keypair()` in `deepiri_zepgpu/vpn/keygen.py`

### 2.2 Room Invite API

Add room-facing wrappers:

- [ ] `POST /api/v1/rooms/{room_id}/invites`
  - Creates a room invite.
  - Internally creates `VpnInvite`.

- [ ] `GET /api/v1/rooms/{room_id}/invites`
  - Lists active invites for a room.

- [ ] `DELETE /api/v1/rooms/{room_id}/invites/{invite_id}`
  - Revokes invite.

- [ ] `POST /api/v1/rooms/join`
  - Joins a room using invite code.
  - Internally calls existing VPN join logic.

- [ ] `GET /api/v1/rooms/{room_id}/config`
  - Returns WireGuard/client config for the current user.

### 2.3 Security and Ownership Checks

- [ ] Ensure only room host/admin can create invites.
- [ ] Ensure only invite creator or room host/admin can revoke invites.
- [ ] Prevent joining a room twice.
- [ ] Validate invite expiration and max usage.
- [ ] Ensure UUID/string comparisons are safe.

### 2.4 Frontend Wiring

- [ ] Keep `Vpn.tsx` working.
- [ ] Create or refactor into `Rooms.tsx` and `RoomDetail.tsx`.
- [ ] Add invite creation panel.
- [ ] Add copy invite code button.
- [ ] Add download/copy config panel.
- [ ] Add join room form.

### 2.5 Acceptance Criteria

- Host can generate an invite from room UI.
- Client can join using invite code.
- Client receives VPN config.
- Host can see joined client in room members list.
- Invite usage count increments correctly.
- Revoked/expired invites cannot be used.

---

## Phase 3: Room-Scoped GPU Node Discovery and Metrics

**Goal:** Connected clients should become visible GPU provider nodes inside a room.

### 3.1 Existing Code to Reuse

- `PeerHeartbeatRequest`
- `GpuStatusPayload`
- `PeerRepository.heartbeat()`
- `PeerRepository.mark_awol_peers()`
- `GpuShareRepository.upsert()`
- `GpuShareRepository.list_by_network()`
- `GpuPoolSummary`
- Existing GPU pool UI in `Vpn.tsx`

### 3.2 Backend Work

- [ ] Confirm `/api/v1/vpn/peers/heartbeat` updates peer status and GPU shares correctly.
- [ ] Add room-facing heartbeat endpoint if needed:
  - [ ] `POST /api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat`
- [ ] Ensure heartbeat payload can include all needed GPU metrics:
  - [ ] device index
  - [ ] GPU name
  - [ ] total memory
  - [ ] available memory
  - [ ] utilization percent
  - [ ] compute capability
  - [ ] GPU type
  - [ ] state
  - [ ] temperature, if available later
  - [ ] power draw, if available later
- [ ] Add periodic AWOL/offline detection job if not already scheduled.
- [ ] Make room GPU pool summary room-scoped.

### 3.3 Node Agent MVP

Create a lightweight provider-side agent that can run on a client machine.

- [ ] Create `deepiri_zepgpu/node_agent/__init__.py`.
- [ ] Create `deepiri_zepgpu/node_agent/agent.py`.
- [ ] Create `deepiri_zepgpu/node_agent/config.py`.
- [ ] Create `deepiri_zepgpu/node_agent/gpu_reporter.py`.
- [ ] Create `deepiri_zepgpu/node_agent/heartbeat.py`.
- [ ] Agent should load room/config credentials.
- [ ] Agent should register or identify peer.
- [ ] Agent should collect GPU metrics from NVML when available.
- [ ] Agent should send heartbeat on interval.
- [ ] Agent should support CPU/dev simulation mode.

### 3.4 Frontend Work

- [ ] Add connected node list.
- [ ] Add GPU metric cards per peer/node.
- [ ] Add online/offline/AWOL status indicators.
- [ ] Add total room GPU summary:
  - [ ] total GPUs
  - [ ] total VRAM
  - [ ] available VRAM
  - [ ] online peers
  - [ ] online GPU hosts
- [ ] Add auto-refresh or WebSocket updates.

### 3.5 Acceptance Criteria

- A joined client can send heartbeat.
- Heartbeat marks peer online.
- Heartbeat upserts GPU shares.
- Host can see connected client in UI.
- Host can see GPU metrics in UI.
- Peer becomes AWOL/offline after missed heartbeats.
- GPU pool summary matches connected clients.

---

## Phase 4: Refactor Scheduler for Room-Aware Dispatch

**Goal:** Allow tasks to be dispatched to GPUs connected inside a room.

### 4.1 Existing Code to Review

- [ ] `deepiri_zepgpu/core/scheduler.py`
- [ ] `deepiri_zepgpu/core/executor.py`
- [ ] `deepiri_zepgpu/queue/tasks.py`
- [ ] `deepiri_zepgpu/api/server/routes/tasks.py`
- [ ] `deepiri_zepgpu/database/repositories/task_repository.py`
- [ ] `deepiri_zepgpu/vpn/task_router.py`
- [ ] `deepiri_zepgpu/vpn/remote_gpu_lock.py`
- [ ] `deepiri_zepgpu/vpn/gpu_pool.py`

### 4.2 Required Data Model Additions

Add a room/node assignment layer. If existing VPN task routing already has partial support, reuse it; otherwise add:

- [ ] `node_task_assignments`
- [ ] `node_task_events`

Suggested model fields:

- [ ] assignment ID
- [ ] room/network ID
- [ ] task ID
- [ ] peer ID
- [ ] GPU share ID
- [ ] status
- [ ] assigned timestamp
- [ ] accepted timestamp
- [ ] started timestamp
- [ ] completed timestamp
- [ ] failed timestamp
- [ ] error
- [ ] retry count

### 4.3 Task Create / Dispatch Changes

- [ ] Add optional `room_id` or `vpn_network_id` to task creation.
- [ ] Add optional `dispatch_mode`:
  - [ ] `local`
  - [ ] `room_auto`
  - [ ] `room_specific_node`
- [ ] Add optional `target_peer_id` or `target_gpu_share_id`.
- [ ] Validate user has access to the room.
- [ ] Validate target peer belongs to the room.
- [ ] Validate GPU share is active and available.

### 4.4 Scheduler Policy

Implement first simple room-aware policy:

- [ ] Filter GPU shares by room/network.
- [ ] Only include online peers.
- [ ] Only include active GPU shares.
- [ ] Filter by GPU memory requirement.
- [ ] Prefer idle GPU shares.
- [ ] Prefer higher available memory.
- [ ] Avoid AWOL/offline peers.
- [ ] Lock selected GPU share during assignment.
- [ ] Create assignment record.

### 4.5 Remote GPU Locking

- [ ] Review `remote_gpu_lock.py`.
- [ ] Ensure GPU share allocation is atomic.
- [ ] Prevent two tasks from being assigned to the same remote GPU.
- [ ] Release lock on completion/failure/timeout.
- [ ] Add retry path if lock fails.

### 4.6 Acceptance Criteria

- User can submit task with room dispatch mode.
- Scheduler selects an online GPU peer inside the room.
- GPU share is locked/marked allocated.
- Assignment record is created.
- Task status changes to assigned or running.
- Same GPU share cannot be assigned to two tasks at once.
- Failed assignment releases GPU share.

---

## Phase 5: Remote Execution MVP

**Goal:** Prove a task can be sent to a connected node agent and reported back to the coordinator.

### 5.1 Control Channel Decision

Choose one MVP control strategy:

- Option A: node agent polls coordinator for assigned tasks.
- Option B: coordinator sends tasks over WebSocket.
- Option C: Redis stream per node.
- Option D: HTTP callback from coordinator to node agent.

Recommended MVP:

- Start with polling because it is easiest to test locally and does not require inbound connectivity to client nodes.

### 5.2 Node Agent Task Polling

Add agent endpoints/client logic:

- [ ] Agent authenticates with peer token/config.
- [ ] Agent polls for assigned tasks.
- [ ] Agent accepts assignment.
- [ ] Agent marks task started.
- [ ] Agent executes no-op task first.
- [ ] Agent reports completion/failure.
- [ ] Agent uploads or returns result metadata.

### 5.3 Coordinator Endpoints

Add endpoints if not already present:

- [ ] `GET /api/v1/rooms/{room_id}/nodes/{peer_id}/tasks/pending`
- [ ] `POST /api/v1/node-tasks/{assignment_id}/accept`
- [ ] `POST /api/v1/node-tasks/{assignment_id}/start`
- [ ] `POST /api/v1/node-tasks/{assignment_id}/complete`
- [ ] `POST /api/v1/node-tasks/{assignment_id}/fail`
- [ ] `POST /api/v1/node-tasks/{assignment_id}/logs`

### 5.4 Result Handling

- [ ] Reuse existing task result system when possible.
- [ ] Store small results directly or in existing result store.
- [ ] Store large results through S3/MinIO when available.
- [ ] Return result reference to task record.
- [ ] Trigger callback webhook after remote completion.
- [ ] Broadcast WebSocket update after completion.

### 5.5 Acceptance Criteria

- Node agent polls and receives assigned no-op task.
- Node agent accepts task.
- Node agent reports running state.
- Node agent reports completed state.
- Coordinator updates task status.
- Callback fires after remote task completion.
- WebSocket emits task update.
- Result endpoint returns remote task result/status.

---

## Phase 6: Room Dashboard UI Refactor

**Goal:** Turn the current VPN/GPU pool UI into the host master room dashboard.

### 6.1 Existing UI to Reuse

- `zepgpu-ui/src/pages/Vpn.tsx`
- `vpnApi` in `zepgpu-ui/src/api/client.ts`
- VPN/GPU types in `zepgpu-ui/src/types/index.ts`

### 6.2 New UI Pages / Components

- [ ] `zepgpu-ui/src/pages/Rooms.tsx`
- [ ] `zepgpu-ui/src/pages/RoomDetail.tsx`
- [ ] `zepgpu-ui/src/components/RoomInvitePanel.tsx`
- [ ] `zepgpu-ui/src/components/RoomConnectionConfigPanel.tsx`
- [ ] `zepgpu-ui/src/components/RoomNodeList.tsx`
- [ ] `zepgpu-ui/src/components/RoomNodeMetrics.tsx`
- [ ] `zepgpu-ui/src/components/RoomDispatchPanel.tsx`
- [ ] `zepgpu-ui/src/components/RoomActivityLog.tsx`

### 6.3 Frontend API Client Changes

- [ ] Add `roomsApi` to `zepgpu-ui/src/api/client.ts`.
- [ ] Keep `vpnApi` for compatibility.
- [ ] `roomsApi.createRoom()`
- [ ] `roomsApi.listRooms()`
- [ ] `roomsApi.getRoom()`
- [ ] `roomsApi.createInvite()`
- [ ] `roomsApi.joinRoom()`
- [ ] `roomsApi.getConfig()`
- [ ] `roomsApi.listMembers()`
- [ ] `roomsApi.getGpuPool()`
- [ ] `roomsApi.dispatchTask()`

### 6.4 Frontend Type Changes

Add or alias types:

- [ ] `GpuRoom`
- [ ] `GpuRoomMember`
- [ ] `RoomInvite`
- [ ] `RoomConnectionConfig`
- [ ] `RoomNode`
- [ ] `RoomGpuShare`
- [ ] `RoomGpuPoolSummary`
- [ ] `RoomTaskAssignment`

### 6.5 Router / Navigation

- [ ] Add `/rooms` route.
- [ ] Add `/rooms/:roomId` route.
- [ ] Add sidebar/nav link for Rooms.
- [ ] Decide whether old `/vpn` page stays, redirects, or becomes an advanced page.

### 6.6 Acceptance Criteria

- Host can create room from UI.
- Host can view room details.
- Host can create invite from UI.
- Client can join room from UI.
- Host can copy/download config from UI.
- Host can see connected clients.
- Host can see GPU metrics per client.
- Host can dispatch task to room.
- Room UI updates without full page reload where possible.

---

## Phase 7: WebSocket and Metrics Wiring

**Goal:** Make room/node/task state update in real time.

### 7.1 Existing WebSocket Routes

- `/api/v1/ws/tasks`
- `/api/v1/ws/gpus`
- `/api/v1/ws/metrics`

### 7.2 New Room WebSocket Events

- [ ] `room_member_joined`
- [ ] `room_member_left`
- [ ] `room_node_online`
- [ ] `room_node_offline`
- [ ] `room_gpu_update`
- [ ] `room_task_assigned`
- [ ] `room_task_started`
- [ ] `room_task_completed`
- [ ] `room_task_failed`

### 7.3 Backend Wiring

- [ ] Extend websocket manager to support room channels.
- [ ] Add room subscription message.
- [ ] Add room unsubscribe message.
- [ ] Publish events when peer heartbeat updates.
- [ ] Publish events when GPU share updates.
- [ ] Publish events when task assignment changes.
- [ ] Publish events when remote task completes/fails.

### 7.4 Frontend Wiring

- [ ] Add room WebSocket hook.
- [ ] Subscribe to selected room.
- [ ] Update node list on events.
- [ ] Update GPU metrics cards on events.
- [ ] Update task assignment panel on events.

### 7.5 Acceptance Criteria

- Room dashboard receives real-time node status updates.
- GPU metrics update without manual refresh.
- Task dispatch state updates in real time.
- WebSocket auth still uses JWT.
- Disconnect/reconnect behavior is handled safely.

---

## Phase 8: Local Simulation and Testing

**Goal:** Provide a reproducible way to test room networking without needing real cloud deployment immediately.

### 8.1 Local Simulation

- [ ] Add dev instructions for one coordinator + one simulated node.
- [ ] Add simulated GPU heartbeat payload.
- [ ] Add no-op remote task execution.
- [ ] Add fake GPU metrics mode.
- [ ] Add Docker Compose optional service for node agent if practical.

### 8.2 Integration Tests

- [ ] Test room creation.
- [ ] Test invite creation.
- [ ] Test room join.
- [ ] Test config generation.
- [ ] Test peer heartbeat.
- [ ] Test GPU share upsert.
- [ ] Test GPU pool summary.
- [ ] Test room-aware task assignment.
- [ ] Test remote no-op completion.
- [ ] Test WebSocket room event.

### 8.3 Documentation

- [ ] Add `docs/room_network_local_testing.md`.
- [ ] Add room quick start to README.
- [ ] Add API examples.
- [ ] Add node agent dev instructions.
- [ ] Add troubleshooting notes for VPN/port/NAT issues.

### 8.4 Acceptance Criteria

- Developer can run coordinator locally.
- Developer can run simulated node locally.
- Simulated node appears in room dashboard.
- Simulated GPU metrics appear in room dashboard.
- Host can dispatch no-op task to simulated node.
- Task completes and result/status is visible.

---

## Phase 9: Cloud / Deployment Research

**Goal:** Decide how the coordinator and room network should run outside local development.

### 9.1 Research Areas

- Local host with port forwarding.
- Cloud-hosted coordinator.
- Hybrid coordinator with local provider nodes.
- Relay-based networking.
- Fully decentralized network.
- NAT traversal limitations.
- VPN relay requirements.

### 9.2 Recommendation

- Start with hybrid coordinator + local provider nodes.
- Keep local simulation path for development.
- Treat full decentralization as later research.

### 9.3 Acceptance Criteria

- Deployment options are documented.
- Team chooses MVP deployment architecture.
- Cloud coordinator requirements are documented.
- Local simulation remains supported.

---





# Priority Queue

| Priority | Task | Phase | Status |
|---|---|---|---|
| P0 | Commit implementation plan | Docs | Now |
| P0 | Complete original Phase 8 stabilization items | Phase 0 | In progress |
| P0 | Add room API wrappers | Phase 1 | Next |
| P0 | Wire room invites/configs to existing VPN logic | Phase 2 | Next |
| P1 | Room-scoped GPU pool and node heartbeat | Phase 3 | Planned |
| P1 | Node agent MVP | Phase 3 / 5 | Planned |
| P1 | Room-aware scheduler | Phase 4 | Planned |
| P1 | Remote no-op task execution | Phase 5 | Planned |
| P2 | Room dashboard UI | Phase 6 | Planned |
| P2 | Room WebSocket events | Phase 7 | Planned |
| P2 | Local simulation docs/tests | Phase 8 | Planned |
| P3 | Cloud/deployment research | Phase 9 | Research |
| Deferred | Blockchain | Phase 10 | Not active |

---

# Success Criteria

## Functional

- Host can create a room.
- Host can generate invite/config.
- Client can join room.
- Client can report GPU metrics.
- Host can see connected clients and GPUs.
- Host can dispatch no-op task to connected client.
- Remote task completes and updates central task status.

## Reliable

- Missed heartbeats mark clients unhealthy.
- Remote GPU allocation is atomic.
- Failed assignments can be retried or released.
- Existing local task execution still works.

## Observable

- Room events are logged.
- Node metrics are visible.
- Task assignment lifecycle is visible.
- WebSocket updates are available for room UI.

## Secure

- Room access checks are enforced.
- Invite codes expire or revoke correctly.
- Configs can be revoked.
- Users cannot dispatch to rooms they do not belong to.

## Documented

- Room local testing guide exists.
- Node agent dev instructions exist.
- API examples exist.
- VPN/NAT/cloud limitations are documented.

---



