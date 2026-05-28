# ZepGPU Petals + Blockchain Research Roadmap

## Overview

The recommendation is:

> ZepGPU should continue as a serverless GPU task framework, but its next major direction should be a Petals-inspired distributed GPU network where independent nodes can join, advertise GPU capacity, receive workloads, execute tasks, and report results. Blockchain should not be used for running GPU execution itself. It should be considered later for identity, accounting, reputation, usage receipts, and marketplace/payment settlement.

This document is a **research roadmap**, not a final implementation replacement. It is meant to guide the next planning discussion before more execution work continues.

---

## Summary

ZepGPU currently has a strong foundation as a serverless GPU task execution platform:

- Users can submit GPU tasks.
- Tasks are queued through Redis/Celery.
- Task metadata is persisted in PostgreSQL.
- Results can be stored through S3/MinIO.
- Pipelines, WebSockets, callback webhooks, authentication, Docker, and Kubernetes support already exist or are in progress.

However, the current architecture is strongest as a **centralized or cluster-local GPU execution framework**. Petals suggests a larger direction: a distributed peer GPU network where machines can contribute compute resources and workloads can be routed across them.

Blockchain may be useful later, but only after the distributed compute network works off-chain. Blockchain should be treated as an optional trust, accounting, reputation, receipt, and settlement layer.

Recommended next direction:

1. Finish the Phase 8 stabilization work that directly supports future distributed execution.
2. Add a Petals-inspired GPU node layer.
3. Add distributed scheduling and remote task execution.
4. Add usage accounting, receipts, provider reputation, and audit trails.
5. Research blockchain as an optional settlement/receipt layer.
6. Only prototype blockchain after the off-chain distributed compute layer is proven.

---

## Current ZepGPU Baseline

ZepGPU is currently positioned as a serverless GPU framework for kernel-as-a-service computing. The current system includes:

- FastAPI backend
- React/TypeScript frontend
- PostgreSQL persistence
- Redis/Celery distributed task queue
- S3/MinIO result storage
- Docker and Kubernetes deployment support
- JWT authentication
- Task submission and execution
- Multi-stage pipelines
- WebSocket monitoring
- Callback webhooks
- GPU tracking
- Prometheus/Grafana monitoring

The current implementation plan describes ZepGPU as a production-grade serverless GPU framework where users submit GPU tasks to a shared pool and the system handles scheduling, isolation, execution, and result delivery.

The main architectural gap is that ZepGPU is currently designed around a local or centrally coordinated execution stack. To become more Petals-like, ZepGPU needs a distributed node layer where GPU providers can join the network, advertise capacity, receive work, execute tasks, and report results.

---

## Petals Research Summary

Petals is an open-source BigScience project for running very large language models collaboratively. Its core idea is to let users load part of a model and join a network where other peers serve the remaining parts. Petals describes this as running LLMs “BitTorrent-style.”

Key Petals ideas:

- A machine can act as a **server**, **client**, or both.
- Servers host pieces of a model, usually layers or blocks.
- Clients discover available peers and route requests through multiple servers.
- The system allows collaborative inference/fine-tuning by joining resources from multiple parties.
- Petals is designed to make large model usage possible without every user owning all required GPU resources.
- The design depends heavily on peer discovery, routing, health, fault tolerance, and distributed execution.

## What ZepGPU Should Copy From Petals

ZepGPU should not copy Petals exactly. Petals is focused on distributed LLM inference/fine-tuning, while ZepGPU is a broader GPU task execution framework.

ZepGPU should copy the design principles:

1. **Peer-based GPU nodes**
   - Machines should be able to join the network as GPU providers.
   - A provider node should advertise GPU type, memory, health, load, latency, and availability.

2. **Resource discovery**
   - ZepGPU needs a node discovery layer so the scheduler can find available GPUs across machines.

3. **Distributed routing**
   - Workloads should be routed to the best available node, not just to a local worker.

4. **Health and heartbeat tracking**
   - Nodes should send heartbeat updates.
   - Dead or unhealthy nodes should be removed from scheduling.

5. **Fault tolerance**
   - If a node disappears or fails, ZepGPU should retry or reroute the workload.

6. **Partial workload distribution**
   - Future ZepGPU could support splitting certain jobs across multiple nodes, especially LLM/model workloads, batch workloads, and multi-stage pipelines.

7. **Client/provider separation**
   - ZepGPU should define clear roles:
     - Requester/client: submits tasks.
     - Provider/node: contributes GPU resources.
     - Coordinator/scheduler: matches tasks to resources.
     - Auditor/monitor: tracks status, usage, and reliability.

---

## Blockchain Research Summary

Blockchain is potentially useful for ZepGPU, but not for running GPU computation directly.

GPU execution should stay **off-chain** because blockchain is too slow and expensive for direct compute workloads. The better model is:

> Off-chain GPU execution + optional on-chain accounting, reputation, receipts, and settlement.

This is similar to decentralized compute projects such as Akash and Golem. These projects use decentralized networks/marketplaces for compute resources, while actual computation happens off-chain on provider machines.

## Blockchain Areas That May Fit ZepGPU

Blockchain could be useful for:

1. **Provider identity**
   - Nodes could register with wallet-based identities.
   - This can help distinguish providers and track reliability.

2. **Usage receipts**
   - ZepGPU can generate signed receipts showing:
     - task ID
     - requester ID
     - provider ID
     - GPU type
     - runtime
     - cost estimate
     - completion status
     - result hash

3. **Reputation**
   - Providers can build reputation based on successful task completion, uptime, latency, and failure rate.

4. **Payment settlement**
   - If ZepGPU becomes a marketplace, blockchain can handle payments between requesters and GPU providers.

5. **Audit trail**
   - Critical task events can be recorded as hashes or receipts.
   - Full logs should stay off-chain; only hashes/receipts should be considered for on-chain anchoring.

6. **Slashing or penalties**
   - If providers stake tokens/collateral, unreliable or malicious behavior could be penalized later.

7. **Marketplace incentives**
   - Providers may be rewarded for making GPUs available.
   - Requesters can pay for GPU execution without centralized billing.

## Blockchain Areas That Should Not Be Done First

Avoid these early:

- Running task execution on-chain
- Storing large task data on-chain
- Storing model artifacts on-chain
- Making blockchain required for basic ZepGPU operation
- Adding tokens before the distributed compute layer works
- Overbuilding smart contracts before the network design is proven

---

# Recommended Restructure of the Implementation Plan

The remaining execution work should pause long enough for the team to review whether ZepGPU should move toward a distributed GPU node network.

The recommended restructure is:

| Priority | Phase | Focus | Recommendation |
|---|---|---|---|
| 1 | Phase A | Stabilize current ZepGPU foundation | Do immediately |
| 2 | Phase B | Petals-style GPU node layer | Do next |
| 3 | Phase C | Distributed scheduler and remote execution | Do after node layer |
| 4 | Phase D | Petals-inspired workload partitioning research | Research in parallel |
| 5 | Phase E | Trust, accounting, and reputation | Needed before marketplace |
| 6 | Phase F | Blockchain feasibility/prototype | Optional, after off-chain accounting |


---

# Roadmap Checklist

This checklist mirrors the style of the existing ZepGPU implementation plan so the team can track the research roadmap as actionable work instead of only reading it as notes.

## Phase Status Legend

- `[ ]` Not started
- `[~]` In progress / partially complete
- `[x]` Completed
- `[?]` Needs decision or research approval

## Phase A: Stabilize Current ZepGPU Foundation — IN PROGRESS

Goal: finish validating the existing ZepGPU MVP before expanding into distributed GPU networking.

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

Acceptance checkpoint: ZepGPU can be started locally, authenticated users can submit tasks and pipelines, workers can execute them, callbacks and WebSockets work, and failures are documented clearly.

## Phase B: Petals-Inspired GPU Node Layer — PLANNED

Goal: allow independent GPU machines to join ZepGPU as provider nodes.

- [ ] Add `gpu_nodes` database model
- [ ] Add `gpu_node_devices` database model
- [ ] Add Alembic migration for node tables
- [ ] Add node registration endpoint
- [ ] Add node heartbeat endpoint
- [ ] Add node list/detail endpoints
- [ ] Add node drain endpoint
- [ ] Add GPU capability reporting
- [ ] Add node health states: `online`, `offline`, `busy`, `draining`, `unhealthy`, `unknown`
- [ ] Build first `zepgpu-node-agent` prototype
- [ ] Add node status visibility in API and/or UI

Acceptance checkpoint: a separate node process can register with the coordinator, report GPU resources, heartbeat regularly, and appear in the scheduler's available resource inventory.

## Phase C: Distributed Scheduler and Remote Execution — PLANNED

Goal: route work to local or remote GPU nodes based on availability, requirements, and health.

- [ ] Add `node_task_assignments` database model
- [ ] Add `node_task_events` database model
- [ ] Add node-aware scheduling policy
- [ ] Add remote task assignment flow
- [ ] Add remote task accept/reject flow
- [ ] Add remote execution lifecycle states
- [ ] Add remote result return path
- [ ] Add node failure detection
- [ ] Add retry/reroute logic for failed nodes
- [ ] Support distributed pipeline stage routing
- [ ] Add tests for node assignment and rerouting

Acceptance checkpoint: a task can be assigned to a provider node, executed remotely, reported back to the coordinator, and retried or rerouted if the node fails before completion.

## Phase D: Petals-Inspired Workload Partitioning Research — RESEARCH

Goal: decide whether ZepGPU should eventually support partitioned model workloads like Petals, or focus on distributed task/pipeline routing only.

- [ ] Classify supported workload types
- [ ] Identify which workloads are single-node only
- [ ] Identify which workloads can be distributed by pipeline stage
- [ ] Research model layer/block partitioning
- [ ] Research tensor parallelism and pipeline parallelism
- [ ] Research latency impact and node churn risks
- [ ] Research model artifact distribution strategy
- [ ] Decide whether Petals-style model sharding belongs in ZepGPU

Acceptance checkpoint: the team has a written decision on whether ZepGPU should support model partitioning, pipeline-only distribution, or both.

## Phase E: Trust, Accounting, and Reputation Layer — PLANNED

Goal: track who provided compute, who used it, how much was used, and how reliable each provider is.

- [ ] Add `usage_ledger` database model
- [ ] Add `execution_receipts` database model
- [ ] Add `provider_reputation` database model
- [ ] Generate signed off-chain receipts after task completion
- [ ] Track GPU seconds by requester and provider
- [ ] Track provider success/failure/timeout rates
- [ ] Add provider reputation scoring
- [ ] Add audit events for node/task lifecycle
- [ ] Add provider usage/reputation endpoints
- [ ] Add provider dashboard or admin view

Acceptance checkpoint: ZepGPU can produce trustworthy off-chain records of GPU usage and provider reliability without requiring blockchain.

## Phase F: Blockchain Feasibility Layer — OPTIONAL / RESEARCH

Goal: evaluate blockchain only after off-chain distributed execution and accounting are proven.

- [?] Decide whether wallet identity is required or optional
- [ ] Add optional `wallet_identities` model
- [ ] Design off-chain receipt format
- [ ] Research on-chain receipt anchoring
- [ ] Research payment settlement options
- [ ] Research escrow/payment channel options
- [ ] Research provider staking/slashing risks
- [ ] Add optional on-chain receipt anchor prototype if approved
- [?] Decide whether blockchain should be implemented, deferred, or rejected

Acceptance checkpoint: the team has a clear go/no-go decision on blockchain, supported by an off-chain receipt/accounting prototype and risk analysis.

## Recommended Execution Order

1. Review this roadmap with the team.
2. Finish Phase A items that support distributed execution.
3. Start Phase B node registration and heartbeat work.
4. Build a minimal provider node agent.
5. Add Phase C remote task assignment.
6. Add Phase E off-chain usage receipts and reputation.
7. Continue Phase D workload partitioning research in parallel.
8. Only start Phase F blockchain work after the off-chain system is stable.

---

# MVP vs Later Scope

## MVP Scope for the Petals-Inspired Direction

The MVP should prove that ZepGPU can operate as a distributed GPU node network without blockchain.

MVP should include:

- Node registration
- Node heartbeat
- GPU capability reporting
- Node health state tracking
- Task assignment to a remote node
- Remote node task acceptance
- Remote task execution
- Result/status return to coordinator
- Basic retry if node fails before task starts
- Basic provider usage accounting
- Admin/API visibility into nodes and node tasks

MVP should not include:

- Token launch
- On-chain smart contracts
- Slashing
- Marketplace bidding
- Arbitrary multi-node model sharding
- Payment settlement
- Complex proof-of-compute
- Full decentralized consensus

## Later Scope

Later phases can include:

- Blockchain wallet identity
- Signed execution receipts
- On-chain receipt anchoring
- Provider reputation scoring
- Marketplace pricing
- Payment settlement
- Staking/slashing
- Distributed model partitioning
- Multi-node LLM inference
- Proof/attestation research

---

# Phase A: Stabilize Current ZepGPU Foundation

## Goal

Finish validating and hardening the current ZepGPU MVP before expanding into distributed GPU networking.

## Why This Matters

Petals-style distributed compute requires a stable base first. If local task execution, auth, Redis/Celery, callbacks, and WebSockets are unstable, distributed execution will be much harder to debug.

## Work Items

- Complete Phase 8 validation.
- Keep Docker Compose startup reliable.
- Keep backend/frontend local development reliable.
- Confirm JWT authentication works.
- Confirm task creation, retrieval, result retrieval, and execution work.
- Confirm pipeline creation and execution work.
- Confirm callback webhooks work.
- Confirm WebSocket streams work.
- Add Redis retry logic.
- Review GPU allocation race conditions.
- Add validation for task `func_name` so invalid values fail early.
- Update README and troubleshooting docs.

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

- `docker compose up -d --build` starts all required services.
- `GET /api/v1/health` returns healthy backend status.
- Swagger/OpenAPI loads at `/docs`.
- User can register, login, authorize, and access protected routes.
- User can create a task and retrieve task status.
- Celery receives and executes a no-op task.
- Callback webhook fires on task completion.
- WebSocket `/api/v1/ws/tasks` accepts a JWT token and responds to `ping`.
- Pipeline can be created and run successfully.
- Redis retry behavior is documented or implemented.
- GPU allocation logic has a documented race-condition review.

---

# Phase B: Petals-Inspired GPU Node Layer

## Goal

Add the foundation for ZepGPU to operate across multiple independent GPU nodes.

## Main Concept

A ZepGPU node should be able to join the network and advertise available GPU resources, similar to how Petals peers contribute parts of model capacity to a distributed network.

## Database Tables

### `gpu_nodes`

Tracks provider machines that can execute work.

Suggested fields:

```sql
CREATE TABLE gpu_nodes (
    id UUID PRIMARY KEY,
    owner_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    namespace_id UUID NULL,
    node_name VARCHAR(255) NOT NULL,
    hostname VARCHAR(255),
    public_address VARCHAR(500),
    private_address VARCHAR(500),
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

Tracks GPUs attached to a node.

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
    temperature_celsius INTEGER,
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
| `POST` | `/api/v1/nodes/register` | Register a provider node |
| `POST` | `/api/v1/nodes/{node_id}/heartbeat` | Update node health/capacity |
| `GET` | `/api/v1/nodes` | List nodes |
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
- `zepgpu-ui/src/api/client.ts`
- `zepgpu-ui/src/types/index.ts`

## Implementation Order

1. Add database models and migration.
2. Add repository layer for node CRUD and heartbeat updates.
3. Add API schemas and routes.
4. Register the route in the FastAPI router.
5. Add simple node agent CLI prototype.
6. Make node agent register with coordinator.
7. Make node agent send periodic heartbeats.
8. Add node list endpoint testing.
9. Add basic UI page for nodes.
10. Document local testing.

## Acceptance Criteria

- A node can register with the coordinator.
- Registered node appears in `GET /api/v1/nodes`.
- Node can send heartbeat updates.
- Missed heartbeat causes node to become `offline` or `unhealthy`.
- Node device capability data is stored.
- API can list node GPUs.
- Node agent can run locally in dev mode.

---

# Phase C: Distributed Scheduler and Remote Execution

## Goal

Evolve ZepGPU from local Celery execution into distributed GPU task routing.

## Main Concept

The scheduler should pick the best GPU node for a task based on availability, requirements, health, latency, and reliability.

## Database Tables

### `node_task_assignments`

Tracks which node is assigned to each task.

```sql
CREATE TABLE node_task_assignments (
    id UUID PRIMARY KEY,
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

Tracks lifecycle events for debugging and auditing.

```sql
CREATE TABLE node_task_events (
    id UUID PRIMARY KEY,
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
| `POST` | `/api/v1/node-tasks/{task_id}/assign` | Assign task to a node |
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

## Implementation Order

1. Add assignment/event database models.
2. Add assignment repository.
3. Add node selector that filters healthy nodes.
4. Add basic scheduling policy.
5. Add node task API routes.
6. Add node agent polling or control channel.
7. Make agent accept assigned task.
8. Make agent execute no-op task.
9. Make agent report completion.
10. Add failure retry path.
11. Add distributed pipeline stage assignment.
12. Add integration tests.

## Scheduling Policy Inputs

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

- Scheduler can select a healthy node for a task.
- Task assignment record is created.
- Node agent receives or polls assigned task.
- Node agent can execute no-op task.
- Coordinator receives completion update.
- Task status changes from pending → assigned → running → completed.
- Failed node assignment can be retried on another node.
- Assignment history is visible through API.

---

# Phase D: Petals-Inspired Workload Partitioning Research

## Goal

Research whether ZepGPU should support partitioned workloads across nodes, especially for AI/model tasks.

## Why This Matters

Petals splits large models into blocks/layers across peer machines. ZepGPU may not need this for all GPU tasks, but it could be powerful for LLM inference, batch inference, and distributed ML workflows.

## Work Items

### D1. Identify Workload Categories

Classify workloads into:

1. Single-node tasks
2. Multi-GPU single-node tasks
3. Multi-node pipeline tasks
4. Multi-node partitioned model tasks
5. Batch distributed tasks

### D2. Start With Pipeline Distribution

Do not start by splitting arbitrary Python functions. Start by distributing pipeline stages across nodes.

### D3. Research Model Partitioning

Study:

- layer/block partitioning
- tensor parallelism
- pipeline parallelism
- batch routing
- model shard placement
- latency impact

### D4. Define Constraints

Distributed model execution has risks:

- network latency
- node churn
- inconsistent GPU speeds
- result verification
- model artifact distribution
- privacy/security

## Proposed File/Module Changes

- `docs/distributed_workload_partitioning.md`
- `docs/model_partitioning_research.md`
- `deepiri_zepgpu/core/workload_classifier.py`
- `deepiri_zepgpu/core/pipeline_partition_planner.py`

## Acceptance Criteria

- Workload categories are documented.
- Team decides which workload types ZepGPU will support first.
- Pipeline-stage distribution is selected as the first practical target.
- Model sharding is treated as research until a clear use case is approved.
- Risks and constraints are documented.

---

# Phase E: Trust, Accounting, and Reputation Layer

## Goal

Add the non-blockchain trust layer required before any marketplace or blockchain integration.

## Why Before Blockchain?

ZepGPU should first track usage, reliability, and receipts internally. Blockchain should only be added after the off-chain data model is correct.

## Database Tables

### `usage_ledger`

```sql
CREATE TABLE usage_ledger (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    requester_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    provider_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    node_id UUID REFERENCES gpu_nodes(id) ON DELETE SET NULL,
    gpu_type VARCHAR(100),
    gpu_seconds DECIMAL(15, 4),
    memory_mb INTEGER,
    status VARCHAR(50),
    cost_estimate DECIMAL(15, 6),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### `execution_receipts`

```sql
CREATE TABLE execution_receipts (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    requester_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    provider_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    node_id UUID REFERENCES gpu_nodes(id) ON DELETE SET NULL,
    receipt_hash VARCHAR(255) NOT NULL,
    result_hash VARCHAR(255),
    payload JSONB NOT NULL,
    signature TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### `provider_reputation`

```sql
CREATE TABLE provider_reputation (
    id UUID PRIMARY KEY,
    provider_user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    node_id UUID REFERENCES gpu_nodes(id) ON DELETE CASCADE,
    successful_tasks INTEGER DEFAULT 0,
    failed_tasks INTEGER DEFAULT 0,
    timeout_tasks INTEGER DEFAULT 0,
    average_latency_ms DECIMAL(15, 2),
    average_runtime_ms DECIMAL(15, 2),
    uptime_percent DECIMAL(5, 2),
    reputation_score DECIMAL(10, 4),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/accounting/usage` | List usage records |
| `GET` | `/api/v1/accounting/usage/me` | Current user's usage |
| `GET` | `/api/v1/accounting/receipts/{task_id}` | Get task receipt |
| `POST` | `/api/v1/accounting/receipts/{task_id}/generate` | Generate receipt |
| `GET` | `/api/v1/reputation/providers` | List provider reputation |
| `GET` | `/api/v1/reputation/providers/{provider_id}` | Get provider reputation |

## Proposed File/Module Changes

- `deepiri_zepgpu/database/models/usage_ledger.py`
- `deepiri_zepgpu/database/models/execution_receipt.py`
- `deepiri_zepgpu/database/models/provider_reputation.py`
- `deepiri_zepgpu/database/repositories/accounting_repository.py`
- `deepiri_zepgpu/database/repositories/reputation_repository.py`
- `deepiri_zepgpu/api/server/routes/accounting.py`
- `deepiri_zepgpu/api/server/routes/reputation.py`
- `deepiri_zepgpu/core/receipt_generator.py`
- `deepiri_zepgpu/core/reputation.py`

## Acceptance Criteria

- Usage record is created for completed tasks.
- Receipt can be generated for a completed task.
- Receipt hash is deterministic.
- Provider reputation updates after task completion/failure.
- API exposes usage, receipts, and reputation.
- Data model works without blockchain.

---

# Phase F: Blockchain Feasibility Layer

## Goal

Evaluate and optionally prototype blockchain support after the distributed compute system and accounting layer work off-chain.

## Recommendation

Blockchain should be optional and modular.

ZepGPU should work without blockchain. Blockchain should only add:

- public receipts
- marketplace settlement
- wallet identity
- provider staking
- reputation anchoring

## Database Tables

### `wallet_identities`

```sql
CREATE TABLE wallet_identities (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    wallet_address VARCHAR(255) NOT NULL,
    chain VARCHAR(100),
    verified BOOLEAN DEFAULT false,
    verification_message TEXT,
    verified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(wallet_address, chain)
);
```

### `onchain_receipt_anchors`

```sql
CREATE TABLE onchain_receipt_anchors (
    id UUID PRIMARY KEY,
    receipt_id UUID REFERENCES execution_receipts(id) ON DELETE CASCADE,
    chain VARCHAR(100),
    contract_address VARCHAR(255),
    tx_hash VARCHAR(255),
    block_number BIGINT,
    status VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    confirmed_at TIMESTAMP
);
```

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/blockchain/wallets/connect` | Connect wallet identity |
| `POST` | `/api/v1/blockchain/wallets/verify` | Verify wallet signature |
| `GET` | `/api/v1/blockchain/wallets/me` | Get current user's wallets |
| `POST` | `/api/v1/blockchain/receipts/{receipt_id}/anchor` | Anchor receipt hash on-chain |
| `GET` | `/api/v1/blockchain/receipts/{receipt_id}/anchor` | Get anchoring status |

## Proposed File/Module Changes

- `deepiri_zepgpu/database/models/wallet_identity.py`
- `deepiri_zepgpu/database/models/onchain_receipt_anchor.py`
- `deepiri_zepgpu/database/repositories/blockchain_repository.py`
- `deepiri_zepgpu/api/server/routes/blockchain.py`
- `deepiri_zepgpu/blockchain/wallets.py`
- `deepiri_zepgpu/blockchain/receipts.py`
- `deepiri_zepgpu/blockchain/contracts/`
- `docs/blockchain_feasibility.md`

## Implementation Order

1. Write blockchain feasibility report.
2. Add wallet identity model without requiring wallet login.
3. Add wallet verification endpoint.
4. Generate off-chain execution receipts first.
5. Add optional receipt hash anchoring.
6. Compare whether settlement should be on-chain, off-chain, or not included.
7. Only then consider smart contracts.

## Acceptance Criteria

- ZepGPU works without blockchain enabled.
- Wallet identity is optional.
- Receipts can be generated off-chain.
- Receipt hash can be anchored on-chain in a prototype.
- No task payloads, logs, model artifacts, or results are stored on-chain.
- Team has a written go/no-go decision for blockchain settlement.

---



# Final Recommendation

The best next step is not to immediately build blockchain features. The best next step is to use Petals as inspiration to evolve ZepGPU into a distributed GPU node network.

Recommended order:

1. Finish the current stabilization work that supports distributed execution.
2. Add GPU node registration, heartbeat, and capability reporting.
3. Add node agent prototype.
4. Add distributed scheduler and remote execution.
5. Add accounting, receipts, and reputation off-chain.
6. Research blockchain as an optional receipt/payment/reputation layer.
7. Only prototype blockchain if the off-chain distributed compute layer works and the team confirms it is useful.

---



## Sources

- Petals GitHub repository: https://github.com/bigscience-workshop/petals
- Petals project site: https://petals.dev/
- Petals ACL paper: https://aclanthology.org/2023.acl-demo.54/
- Petals arXiv paper: https://arxiv.org/abs/2209.01188
- Yandex Research Petals explainer: https://research.yandex.com/blog/petals-decentralized-inference-and-finetuning-of-large-language-models
- Akash Network: https://akash.network/
- Akash documentation: https://akash.network/docs/getting-started/what-is-akash/
- Golem Network: https://golem.network/
- Golem provider documentation: https://docs.golem.network/docs/providers
