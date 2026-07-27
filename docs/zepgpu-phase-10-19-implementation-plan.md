# ZepGPU Phase 10–19 Implementation Roadmap

## Project Vision

ZepGPU should continue evolving from a serverless GPU task framework into a **host-created distributed GPU room network**.

A host should be able to:

- Create a GPU room.
- Invite other users or machines into that room.
- See connected provider nodes and their GPU capacity.
- Dispatch GPU workloads to one or more connected providers.
- Track task execution, node health, failures, logs, and results in real time.
- Use the room as a practical foundation for multi-GPU LLM training and fine-tuning workflows.

The direction remains room-scoped GPU compute and remote task dispatch. ZepGPU should support general GPU workloads, but the flagship long-term workload is **multi-GPU LLM training/fine-tuning across N provider machines**.

---

# Current Baseline

This roadmap assumes Phases 0–9 already exist as the current baseline and should not be restarted or renumbered here.

Earlier work includes or is expected to include:

- Core task framework, API server, database, Redis/Celery queue, UI, monitoring, and deployment foundations.
- Room/VPN compatibility, room creation, invites, config generation, peer membership, and GPU pool reporting.
- Room-scoped node heartbeat and GPU metrics.
- Room-aware task assignment.
- Remote no-op execution through a node agent.
- Room dashboard and real-time task/node visibility.
- Local room simulation.
- Phase 9 cloud/deployment architecture research.

If any Phase 0–9 gaps remain, they are captured as hardening work in Phase 10+ instead of reopening old phases.

---

# Five Core Design Integrations

The Phase 10–19 roadmap includes five designs that turn the room network into a complete distributed training workflow.

| Design | Purpose | Primary Phase(s) |
|---|---|---|
| **Room Training Job Specification** | Gives ZepGPU a standard, first-class way to describe an LLM training or fine-tuning job. | Phase 15 and Phase 18 |
| **Training Readiness and Placement Planner** | Checks whether a room can realistically run a requested job and explains the placement decision. | Phase 15 |
| **Distributed Training Launcher** | Coordinates ranks, workers, GPU reservations, startup, failure handling, logs, and checkpoints. | Phase 18 |
| **Communication and Topology Profiler** | Measures or estimates how efficiently provider machines and GPUs can communicate. | Phase 15 and Phase 19 |
| **Training Run Dashboard** | Shows live workers, GPUs, logs, metrics, checkpoints, bottlenecks, and failure reasons. | Phase 19 |

These designs are integrated into existing phases rather than added as separate phases because they are parts of one end-to-end training workflow:

1. The **Training Job Specification** describes what should run.
2. The **Readiness and Placement Planner** determines whether the room can run it.
3. The **Communication and Topology Profiler** supplies network and hardware facts to that decision.
4. The **Distributed Training Launcher** starts and coordinates the job.
5. The **Training Run Dashboard** shows what happened and whether the run was efficient.

---

# Implementation Phases

Only implementation tasks that directly require code, docs, tests, or repo changes use checklist boxes. Explanatory sections, recommendations, acceptance criteria, and review criteria are written as plain bullets so the checklist stays focused on work that can actually be completed in the repo.

---

## Phase 10: Baseline Hardening and Local Simulation Gate

**Goal:** Make the existing room-network path reliable enough to serve as the foundation for cloud and multi-GPU work.

This phase does not restart Phase 8 or Phase 9. It verifies and hardens the current baseline so future phases can build on it safely.

### 10.1 Local Room Simulation

- [ ] Add or update `docs/room_network_local_testing.md`.
- [ ] Add or update a local simulation script such as `scripts/verify_room_network_local_simulation.py`.
- [ ] Verify local coordinator startup.
- [ ] Verify user registration and login.
- [ ] Verify room creation.
- [ ] Verify invite creation.
- [ ] Verify provider/node join.
- [ ] Verify simulated GPU heartbeat.
- [ ] Verify GPU pool summary.
- [ ] Verify room-aware no-op dispatch.
- [ ] Verify remote no-op completion.
- [ ] Verify task result visibility.
- [ ] Verify WebSocket or polling updates for room/task state.

### 10.2 Baseline Reliability Fixes

- [ ] Confirm room APIs do not break existing `/api/v1/vpn/*` compatibility.
- [ ] Confirm node task assignment lifecycle is idempotent where possible.
- [ ] Confirm failed no-op assignments release GPU locks.
- [ ] Confirm offline or stale providers become unhealthy after missed heartbeats.
- [ ] Add explicit test coverage for room access checks.
- [ ] Add explicit test coverage for cross-room task denial.
- [ ] Add regression tests for room creation, invite, join, heartbeat, GPU pool, and no-op dispatch.

### 10.3 Documentation

- [ ] Update README with a short room-network quick start.
- [ ] Document how to run one coordinator and one simulated provider locally.
- [ ] Document common local failure modes.
- [ ] Document which parts are simulation-only and which parts are ready for real providers.

### 10.4 Acceptance Criteria

- Local simulation can be run repeatedly by a new developer.
- A simulated provider appears in a room.
- Simulated GPU metrics appear in the room GPU pool.
- A room no-op task completes through the node-agent path.
- Existing VPN routes still work.
- Tests pass locally and in CI where practical.

---

## Phase 11: Cloud Coordinator Packaging and Runbooks

**Goal:** Package the coordinator so it can run as a managed service or a self-hosted service.

The coordinator should be the always-on control plane for rooms, invites, provider identity, scheduling, task lifecycle, Postgres, Redis, Celery, WebSockets, and UI/API access. It should not require a GPU.

### 11.1 Coordinator Deployment Artifact

- [ ] Add `docker/docker-compose.prod.yml` for coordinator-only deployment.
- [ ] Include API service.
- [ ] Include optional UI service.
- [ ] Include Postgres service or managed Postgres configuration.
- [ ] Include Redis service or managed Redis configuration.
- [ ] Include Celery worker.
- [ ] Include Celery beat if needed for heartbeat expiry, cleanup, or scheduling.
- [ ] Add health checks for critical services.
- [ ] Keep local development compose working.

### 11.2 Public URL, TLS, and Reverse Proxy

- [ ] Add a reverse proxy example using Caddy or nginx.
- [ ] Add configuration for `COORDINATOR_PUBLIC_URL` or equivalent.
- [ ] Document HTTPS and WSS requirements.
- [ ] Document CORS settings for the UI.
- [ ] Document when UDP 51820 is required for WireGuard rooms.
- [ ] Make clear that dial-out rooms should not require provider inbound ports.

### 11.3 Managed and Self-Hosted Runbooks

- [ ] Add `docs/deploy/cloud_coordinator.md`.
- [ ] Add a self-hosted coordinator section.
- [ ] Add a managed coordinator section.
- [ ] Document required CPU/RAM/storage assumptions.
- [ ] Document secret generation and rotation.
- [ ] Document Postgres backup and restore.
- [ ] Document Redis persistence expectations.
- [ ] Document troubleshooting for DNS, TLS, WSS, Redis, Postgres, and Celery.

### 11.4 Smoke Tests

- [ ] Add `scripts/smoke_cloud_coordinator.py` or equivalent.
- [ ] Smoke test health endpoint.
- [ ] Smoke test register/login.
- [ ] Smoke test room creation.
- [ ] Smoke test invite creation.
- [ ] Smoke test room listing from public coordinator URL.

### 11.5 Acceptance Criteria

- A fresh VM or laptop can run the coordinator stack.
- The coordinator works without a local GPU.
- A user can register, login, create a room, and create an invite.
- The coordinator can be reached through a documented public URL.
- Self-hosted limitations are clearly documented.
- Phase 10 local simulation still works.

---

## Phase 12: NAT-Friendly Provider Join and Agent Identity

**Goal:** Let GPU provider machines join rooms through outbound-only networking using an invite and coordinator URL.

Provider machines should not need inbound ports for the primary cloud-room workflow.

### 12.1 Provider Join UX

- [ ] Add or update `zepgpu-node join --invite <code> --coordinator <url>`.
- [ ] Add or update `zepgpu-node serve`.
- [ ] Add or update `zepgpu-node status`.
- [ ] Persist provider config under `~/.zepgpu/agent.json` or equivalent.
- [ ] Store coordinator URL.
- [ ] Store room ID.
- [ ] Store provider/peer ID.
- [ ] Store room-scoped agent token.
- [ ] Store heartbeat interval and agent metadata.
- [ ] Ensure token values are never printed in normal logs.

### 12.2 Agent Identity and Tokens

- [ ] Add or harden room-scoped provider tokens.
- [ ] Keep human JWT authentication separate from provider-agent authentication.
- [ ] Add token expiration fields if not already present.
- [ ] Add token revocation fields if not already present.
- [ ] Add token last-used tracking if practical.
- [ ] Ensure provider tokens are scoped to one room/network.
- [ ] Ensure cross-room heartbeat and task claim attempts are rejected.

### 12.3 Room Invite Integration

- [ ] Make room invite copy text include the coordinator URL and one-line provider join command.
- [ ] Ensure bad invite codes fail clearly.
- [ ] Ensure expired invite codes fail clearly.
- [ ] Ensure revoked invite codes fail clearly.
- [ ] Prevent duplicate provider joins where appropriate.
- [ ] Keep existing WireGuard config generation available for WireGuard rooms.

### 12.4 Provider Heartbeat

- [ ] Ensure provider heartbeat works with the room-scoped agent token.
- [ ] Include agent version.
- [ ] Include hostname or friendly node name if allowed.
- [ ] Include GPU inventory.
- [ ] Include available GPU memory.
- [ ] Include utilization metrics when available.
- [ ] Include provider mode such as real GPU, CPU/dev mode, or simulated mode.

### 12.5 Acceptance Criteria

- A provider can join a room with one copied command.
- Provider config persists locally.
- Provider can heartbeat using only outbound HTTPS.
- Host can see the provider online.
- Cross-room token use is rejected.
- Existing room/VPN join paths are not broken.

---

## Phase 13: Dial-Out Task Pull and Remote Execution Lifecycle

**Goal:** Make outbound-only provider execution reliable before adding real training workloads.

The MVP control path should be coordinator-mediated task pull/result upload. WebSockets can notify providers, but polling should remain a reliable fallback.

### 13.1 Task Claim and Lease Semantics

- [ ] Add or harden assignment claim flow.
- [ ] Add `claimed_at` if missing.
- [ ] Add `lease_expires_at` if missing.
- [ ] Add claim-token or equivalent idempotency guard if needed.
- [ ] Ensure a provider can only claim its own room assignments.
- [ ] Ensure claim/start/complete/fail transitions are idempotent where possible.
- [ ] Ensure cancelled tasks cannot later complete successfully.

### 13.2 Provider Polling and Notification

- [ ] Ensure provider can poll for pending assignments.
- [ ] Ensure WSS task assignment notification is optional, not required.
- [ ] Ensure polling works behind NAT with no inbound provider port.
- [ ] Add backoff behavior when no work exists.
- [ ] Add clear errors for invalid token, revoked token, and deleted room.

### 13.3 Failure Recovery

- [ ] Add timeout handling for accepted but never-started assignments.
- [ ] Add timeout handling for running assignments.
- [ ] Release GPU locks on fail, timeout, or cancel.
- [ ] Mark provider unhealthy after missed heartbeats.
- [ ] Requeue or mark failed assignments according to retry policy.
- [ ] Add tests for killed provider while task is assigned.
- [ ] Add tests for killed provider while task is running.

### 13.4 Results, Logs, and Events

- [ ] Standardize remote result metadata.
- [ ] Add or harden task log submission.
- [ ] Add or harden task result submission.
- [ ] Trigger callback webhook after remote completion.
- [ ] Broadcast WebSocket update after task status change.
- [ ] Add room activity events for assigned, claimed, started, completed, failed, cancelled, and timed out.

### 13.5 Acceptance Criteria

- Provider can poll, claim, start, complete, and fail a no-op task.
- No inbound provider ports are required.
- Failed or timed-out assignments release GPU capacity.
- Host can see task lifecycle state.
- Callback and WebSocket updates fire after terminal states.
- Tests cover success, failure, cancellation, timeout, and provider disconnect.

---

## Phase 14: Transport Modes and WireGuard Compatibility

**Goal:** Make WireGuard and dial-out execution coexist cleanly.

WireGuard remains supported for existing rooms and advanced L3 mesh use cases. New cloud-oriented rooms should default toward dial-out provider execution.

### 14.1 Transport Mode Model

- [ ] Add transport mode enum: `wireguard`, `dialout`, `overlay`.
- [ ] Add `transport_mode` to the room/network model.
- [ ] Default existing rows to `wireguard`.
- [ ] Default new cloud rooms to `dialout`.
- [ ] Add config such as `ROOM_DEFAULT_TRANSPORT`.
- [ ] Expose `transport_mode` in room API responses.
- [ ] Show transport mode in the room UI.

### 14.2 Dispatch Strategy

- [ ] Keep existing WireGuard task routing path.
- [ ] Add or formalize a dial-out task router.
- [ ] Select routing strategy from `transport_mode`.
- [ ] Ensure dial-out rooms do not require UDP 51820.
- [ ] Ensure WireGuard rooms can still generate configs.
- [ ] Add tests for WireGuard room behavior.
- [ ] Add tests for dial-out room behavior.

### 14.3 Overlay Stub

- [ ] Add a proposed overlay interface or stub only if useful.
- [ ] Keep overlay disabled by default.
- [ ] Document overlay as future work for large payloads or direct peer paths.
- [ ] Do not introduce a mandatory relay dependency in this phase.

### 14.4 Acceptance Criteria

- Existing WireGuard rooms still work.
- New dial-out rooms work without provider inbound ports.
- API and UI expose the active transport mode.
- Scheduler uses the correct strategy for the room mode.
- Overlay is clearly marked as future or experimental.

---

## Phase 15: Multi-GPU Capability Inventory and Training-Aware Scheduling

**Goal:** Extend provider reporting and scheduling so ZepGPU can reason about multi-GPU LLM training workloads before launching them.

This phase integrates three core designs:

- **Room Training Job Specification**
- **Training Readiness and Placement Planner**
- **Communication and Topology Profiler**

Together, these designs let the coordinator understand what the user wants to run, what each provider can supply, how well provider groups can communicate, and whether the requested training job is realistic.

The phase must not claim that aggregate VRAM behaves exactly like one larger GPU. Feasibility depends on the selected distributed strategy, per-GPU memory, runtime support, topology, and communication performance.

### 15.1 Provider Capability Reporting

- [ ] Extend heartbeat or provider inventory to report GPU count.
- [ ] Report GPU model/name.
- [ ] Report total VRAM per GPU.
- [ ] Report available VRAM per GPU.
- [ ] Report compute capability.
- [ ] Report CUDA version when available.
- [ ] Report driver version when available.
- [ ] Report NVLink availability if detectable.
- [ ] Report PCIe topology if detectable.
- [ ] Report peer-to-peer access support if detectable.
- [ ] Report supported runtimes such as PyTorch, CUDA, Docker, NCCL, and optional DeepSpeed.
- [ ] Report provider network hints such as RTT or measured bandwidth when available.

### 15.2 Design 4 — Communication and Topology Profiler

- [ ] Add lightweight provider-to-coordinator latency measurement.
- [ ] Add optional provider-to-provider bandwidth/latency measurement where safe.
- [ ] Add optional NCCL or `torch.distributed` communication smoke test for compatible environments.
- [ ] Track whether a provider group is same-machine, same-LAN, same-region, or WAN/unknown.
- [ ] Store recent communication profile results for scheduler decisions.
- [ ] Clearly mark communication metrics as estimates unless measured directly.

### 15.3 Design 1 — Room Training Job Specification

**Purpose:** Give ZepGPU a standard, first-class description of a distributed training or fine-tuning request.

Without this design, training jobs would be treated as generic remote tasks and the scheduler would not know how many GPUs to reserve, which runtime is required, how much memory is needed, or where checkpoints should be stored.

#### Data Model

- [ ] Add a first-class training job model or task subtype.
- [ ] Add a stable training job ID.
- [ ] Link the training job to the room, submitting user, and underlying task records.
- [ ] Add lifecycle states such as `pending`, `planning`, `reserved`, `starting`, `running`, `checkpointing`, `completed`, `failed`, `cancelled`, and `timed_out`.
- [ ] Store creation, planning, startup, completion, and failure timestamps.
- [ ] Store a machine-readable failure reason.
- [ ] Store the final placement plan used for the run.

#### User-Supplied Job Fields

- [ ] Support model reference.
- [ ] Support dataset reference.
- [ ] Support training script or container image.
- [ ] Support command/entrypoint.
- [ ] Support number of nodes.
- [ ] Support GPUs per node.
- [ ] Support total required GPU count.
- [ ] Support minimum VRAM per GPU.
- [ ] Support preferred or required GPU type.
- [ ] Support framework/runtime requirement.
- [ ] Support precision such as fp32, fp16, bf16, or adapter/quantized mode where applicable.
- [ ] Support an initial distributed strategy hint such as single-node, DDP, or FSDP.
- [ ] Preserve future strategy values such as ZeRO-style, pipeline parallelism, and tensor parallelism without promising immediate support.
- [ ] Support expected model size or parameter count.
- [ ] Support batch-size and sequence-length hints where available.
- [ ] Support checkpoint interval.
- [ ] Support checkpoint output artifact reference.
- [ ] Support final model artifact reference.
- [ ] Support maximum runtime.
- [ ] Support retry policy.
- [ ] Support environment variables with secret filtering.
- [ ] Support input and output artifact references.

#### API and Validation

- [ ] Add create, inspect, cancel, and list endpoints for training jobs.
- [ ] Validate required fields before scheduling.
- [ ] Reject unsupported strategy/runtime combinations clearly.
- [ ] Reject impossible GPU-count requests clearly.
- [ ] Keep generic room task APIs working.
- [ ] Add Pydantic schemas and frontend TypeScript types.
- [ ] Add API examples to the documentation.

### 15.4 Scheduler Policy

- [ ] Filter providers by online status.
- [ ] Filter providers by GPU count.
- [ ] Filter providers by VRAM requirements.
- [ ] Filter providers by runtime requirements.
- [ ] Prefer same-machine multi-GPU when possible.
- [ ] Prefer same-LAN or low-latency groups before WAN groups for communication-heavy training.
- [ ] Prefer higher bandwidth provider groups for distributed training.
- [ ] Avoid providers with recent failures or stale heartbeats.
- [ ] Reserve multiple GPUs atomically for a training job.
- [ ] Release all reserved GPUs if any reservation fails.

### 15.5 Design 2 — Training Readiness and Placement Planner

**Purpose:** Check whether the room can realistically run the requested job before any GPU is reserved.

The planner should produce both a machine-readable placement plan and a human-readable explanation. It should be conservative and clearly identify estimates.

#### Readiness Analysis

- [ ] Estimate required model memory.
- [ ] Estimate optimizer-state memory where applicable.
- [ ] Estimate gradient memory.
- [ ] Estimate activation memory from available batch-size and sequence-length hints.
- [ ] Consider precision.
- [ ] Consider checkpointing and activation recomputation settings if known.
- [ ] Compare estimated requirements against per-GPU VRAM, not only aggregate room VRAM.
- [ ] Consider whether sharding is required.
- [ ] Consider whether the selected distributed strategy is supported.
- [ ] Consider runtime compatibility across all selected providers.
- [ ] Consider provider health and recent failures.
- [ ] Consider communication profile quality.
- [ ] Consider same-machine, same-LAN, same-region, and WAN placement classes.

#### Placement Planning

- [ ] Generate one or more candidate provider groups.
- [ ] Prefer same-machine multi-GPU placement.
- [ ] Prefer same-LAN or low-latency providers for communication-heavy jobs.
- [ ] Avoid mixing incompatible CUDA/runtime environments.
- [ ] Avoid stale or unreliable providers.
- [ ] Ensure the proposed group satisfies the requested GPU count.
- [ ] Ensure each selected GPU satisfies the per-GPU VRAM requirement.
- [ ] Produce a reasoned placement score.
- [ ] Store the selected plan with the training job.
- [ ] Allow the scheduler to reject the run if no safe placement exists.

#### Planner Output

- [ ] Return readiness state: `capable`, `marginal`, or `insufficient`.
- [ ] Return estimated memory requirement.
- [ ] Return selected strategy or strategy recommendation.
- [ ] Return selected providers and GPUs.
- [ ] Return topology classification.
- [ ] Return communication-quality summary.
- [ ] Return warnings.
- [ ] Return actionable failure reasons.
- [ ] Clearly label estimates as approximate.
- [ ] Expose the explanation in API and UI.

#### Example Failure Reasons

- Not enough GPUs.
- Insufficient VRAM on one or more GPUs.
- Aggregate VRAM is sufficient, but per-GPU VRAM is not.
- Required runtime is missing.
- Selected GPUs have incompatible runtime versions.
- Provider group is too unreliable.
- Communication profile is too weak for the requested strategy.
- No provider group can be reserved atomically.


### 15.5A Scheduling Philosophy

The scheduler should optimize for predictable, reliable execution rather than simply selecting the first available GPUs.

#### Scheduling Objectives

- [ ] Prefer successful execution over aggressive placement.
- [ ] Prefer same-machine placement whenever possible.
- [ ] Prefer same-LAN placement before WAN for communication-heavy workloads.
- [ ] Prefer lower-latency provider groups when multiple valid placements exist.
- [ ] Maximize GPU utilization without sacrificing reliability.
- [ ] Produce deterministic placement decisions where practical.
- [ ] Record why a placement was selected.
- [ ] Expose scheduler reasoning through the API and UI.
- [ ] Keep scheduling policy configurable as the platform evolves.

### 15.6 UI Updates

- [ ] Show per-node GPU count.
- [ ] Show total room VRAM.
- [ ] Show available room VRAM.
- [ ] Show grouped provider capacity for multi-GPU jobs.
- [ ] Show communication/topology hints.
- [ ] Show training readiness warnings.
- [ ] Show why a training job cannot be scheduled.

### 15.7 Acceptance Criteria

- Room dashboard shows multi-GPU capacity.
- Scheduler can reserve multiple GPUs atomically.
- Training jobs can express multi-GPU requirements.
- System explains why a job is or is not schedulable.
- Communication/topology hints are available when measured.
- Existing single-GPU and no-op workflows still work.

---

## Phase 16: Secure Provider Revocation, Audit, and Room Trust

**Goal:** Harden provider trust before running real distributed workloads.

Remote GPU sharing requires strong room-scoped authorization, revocation, and audit trails.

### 16.1 Provider Revocation

- [ ] Add or harden provider revoke endpoint.
- [ ] Ensure revoked providers cannot heartbeat.
- [ ] Ensure revoked providers cannot poll tasks.
- [ ] Ensure revoked providers cannot claim tasks.
- [ ] Ensure revoked providers cannot submit logs.
- [ ] Ensure revoked providers cannot complete tasks.
- [ ] Release or fail active assignments when a provider is revoked.
- [ ] Add UI action for room host/admin to revoke a provider.

### 16.2 Room Authorization

- [ ] Verify only room members can view room details.
- [ ] Verify only room host/admin can create invites.
- [ ] Verify only room host/admin can revoke invites.
- [ ] Verify only authorized users can dispatch room tasks.
- [ ] Verify providers can only act within their room.
- [ ] Add cross-room deny tests for all node-task routes.

### 16.3 Audit Events

- [ ] Log room created.
- [ ] Log invite created.
- [ ] Log invite used.
- [ ] Log invite revoked.
- [ ] Log provider joined.
- [ ] Log provider heartbeat stale/offline.
- [ ] Log provider revoked.
- [ ] Log task assigned.
- [ ] Log task claimed.
- [ ] Log task started.
- [ ] Log task completed.
- [ ] Log task failed.
- [ ] Log task cancelled.
- [ ] Log multi-GPU reservation created and released.

### 16.4 Optional Node Identity Groundwork

- [ ] Add persistent node identity key field if useful.
- [ ] Add output checksum fields for future signed results.
- [ ] Document signed results as future hardening unless implemented.

### 16.5 Acceptance Criteria

- Revoked providers lose all room/task privileges.
- Cross-room provider actions are rejected.
- Room host/admin can see meaningful audit history.
- Security tests cover room, provider, and node-task authorization.
- Tokens are redacted in logs and UI.

---

## Phase 17: Real Containerized Remote Execution

**Goal:** Move from remote no-op execution to real provider-side workloads.

This phase turns ZepGPU from a room-network demo into a usable remote compute platform.

### 17.1 Remote Execution Spec

- [ ] Define a remote execution spec.
- [ ] Support Docker image.
- [ ] Support command/entrypoint.
- [ ] Support environment variables with secret filtering.
- [ ] Support GPU requirement.
- [ ] Support timeout.
- [ ] Support input artifact references.
- [ ] Support output artifact references.
- [ ] Support stdout/stderr logs.
- [ ] Support exit code.
- [ ] Support result metadata.


### 17.1A Extensible Workload Model

The execution framework should support multiple workload types without coupling the platform exclusively to LLM training.

#### Workload Abstraction

- [ ] Introduce a first-class workload abstraction.
- [ ] Support Generic Task workloads.
- [ ] Support Training Job workloads.
- [ ] Reserve API support for Inference Job workloads.
- [ ] Reserve API support for Benchmark workloads.
- [ ] Reserve API support for Interactive Session workloads.
- [ ] Allow workload type to determine validation and execution behavior.
- [ ] Preserve backwards compatibility with existing task APIs.
- [ ] Document supported workload lifecycle and transitions.

### 17.2 Provider Container Runner

- [ ] Add provider-side container runner.
- [ ] Pull or use local Docker image.
- [ ] Run container with GPU access when available.
- [ ] Apply timeout and kill behavior.
- [ ] Capture stdout and stderr.
- [ ] Capture exit code.
- [ ] Upload logs to coordinator.
- [ ] Upload result metadata to coordinator.
- [ ] Upload artifacts or artifact references.
- [ ] Clean up containers after completion.

### 17.3 Safety Controls

- [ ] Disable privileged containers by default.
- [ ] Add image allowlist or trust policy for MVP.
- [ ] Limit mounted paths.
- [ ] Redact secrets from logs.
- [ ] Document sandbox limitations.
- [ ] Add safe dev/test images.
- [ ] Add timeout tests.
- [ ] Add failure tests.
- [ ] Add artifact tests.

### 17.4 Acceptance Criteria

- Provider can run a safe container task.
- Task lifecycle updates correctly.
- Logs are visible from coordinator/API/UI.
- Exit code determines completed or failed state.
- Timeout kills long-running job.
- Output artifact metadata is stored.
- No-op runner still works.

---

## Phase 18: Distributed LLM Training MVP

**Goal:** Prove that a ZepGPU room can launch and coordinate a small multi-GPU LLM training or fine-tuning job.

This phase integrates the **Distributed Training Launcher** design and consumes the Training Job Specification, readiness result, communication profile, and placement plan created in Phase 15.

The first implementation should support one controlled strategy rather than attempting DDP, FSDP, ZeRO, pipeline parallelism, and tensor parallelism at the same time. The recommended first target is PyTorch DDP or FSDP on one machine or a controlled LAN environment before attempting unstable WAN training.

### 18.1 Training Job Spec

- [ ] Add `training` task kind or equivalent metadata.
- [ ] Support model reference.
- [ ] Support dataset reference.
- [ ] Support training script or container image.
- [ ] Support number of nodes.
- [ ] Support GPUs per node.
- [ ] Support precision such as fp32, fp16, bf16, or quantized/adapter mode where applicable.
- [ ] Support strategy such as DDP, FSDP, or ZeRO-style.
- [ ] Support checkpoint interval.
- [ ] Support output checkpoint artifact.
- [ ] Support max runtime.

### 18.2 Design 3 — Distributed Training Launcher

- [ ] Choose first supported strategy for MVP.
- [ ] Start with the simplest reliable target, preferably same-machine multi-GPU or LAN multi-node before WAN training.
- [ ] Prefer a small practical first target such as PyTorch DDP or FSDP over many strategies at once.
- [ ] Generate rank/world-size configuration.
- [ ] Assign coordinator-selected providers to a training group.
- [ ] Reserve all required GPUs atomically.
- [ ] Start all assigned provider workers.
- [ ] Fail the training job if not all workers start.
- [ ] Collect status from each worker.
- [ ] Collect logs from each worker.
- [ ] Mark job failed if a required worker fails.
- [ ] Release all GPUs on completion or failure.

#### Training Group Creation

- [ ] Create a training group record for each launch attempt.
- [ ] Attach the approved placement plan.
- [ ] Assign each selected provider a stable worker ID.
- [ ] Assign global rank.
- [ ] Assign local rank.
- [ ] Set world size.
- [ ] Select rendezvous host and port or coordinator mechanism.
- [ ] Generate a short-lived training-group credential.
- [ ] Keep training-group credentials separate from human and provider tokens.

#### Atomic Reservation and Startup

- [ ] Reserve all required GPUs atomically.
- [ ] Fail before startup if any reservation cannot be acquired.
- [ ] Send each provider its worker configuration.
- [ ] Require every worker to acknowledge startup.
- [ ] Enforce a startup deadline.
- [ ] Start the run only after the required worker set is ready.
- [ ] Fail and clean up if any required worker does not start.
- [ ] Prevent duplicate worker starts.
- [ ] Record startup events for each worker.

#### Runtime Coordination

- [ ] Track worker states such as assigned, preparing, ready, running, checkpointing, completed, and failed.
- [ ] Collect heartbeat or progress signals from every worker.
- [ ] Stream or batch worker logs.
- [ ] Propagate cancellation to every worker.
- [ ] Enforce max runtime.
- [ ] Mark the full training job failed if a required worker fails.
- [ ] Release every GPU reservation after terminal state.
- [ ] Preserve enough state to debug partial startup and partial failure.

#### Failure Policy

- [ ] Define behavior for provider disconnect before startup.
- [ ] Define behavior for provider disconnect during training.
- [ ] Define behavior for one worker exiting with a nonzero code.
- [ ] Define behavior for rendezvous timeout.
- [ ] Define behavior for checkpoint failure.
- [ ] Define whether the MVP retries the full group or fails immediately.
- [ ] Avoid silently replacing a worker mid-run unless the selected framework and checkpoint state make that safe.

### 18.3 Training Artifacts

- [ ] Store training logs.
- [ ] Store metrics such as loss, step time, samples/sec, tokens/sec if available.
- [ ] Store checkpoints or checkpoint references.
- [ ] Store final model artifact reference.
- [ ] Store distributed config used for the run.
- [ ] Add checkpoint resume support or document it as future work.

### 18.4 First Demo Workload

- [ ] Add a small example training container.
- [ ] Add a tiny dataset or documented sample dataset.
- [ ] Add a controlled fine-tuning example.
- [ ] Add a local/simulated test path where real GPUs are not required.
- [ ] Add an optional real multi-GPU test path.

### 18.5 Acceptance Criteria

- Host can submit a small distributed training job.
- Scheduler reserves multiple GPUs.
- Providers receive their roles/ranks.
- Training workers start.
- Logs return to coordinator.
- Training metrics are visible.
- Checkpoint or final artifact reference is stored.
- Failures release all reserved GPUs.

---

## Phase 19: Performance, Efficiency, and Release-Ready Demo

**Goal:** Optimize, measure, and present the multi-GPU room training system clearly.

This phase completes two designs:

- **Communication and Topology Profiler**, by comparing measured communication behavior with actual training performance.
- **Training Run Dashboard**, by giving hosts and reviewers one place to understand workers, GPUs, metrics, checkpoints, bottlenecks, and failures.

This phase makes the project demonstrable and helps the team evaluate whether distributed room training is actually efficient rather than merely functional.

### 19.1 Performance Measurement

- [ ] Track queue wait time.
- [ ] Track assignment latency.
- [ ] Track provider claim latency.
- [ ] Track startup latency.
- [ ] Track training step time.
- [ ] Track samples/sec or tokens/sec where available.
- [ ] Track GPU utilization.
- [ ] Track memory utilization.
- [ ] Track network transfer volume where available.
- [ ] Track job failure rate.

### 19.2 Efficiency and Topology Feedback

- [ ] Show whether training is bottlenecked by memory, compute, network, startup, or queueing when detectable.
- [ ] Show provider group latency/bandwidth hints.
- [ ] Show same-node vs multi-node placement warnings.
- [ ] Add scheduler notes explaining why a provider group was selected.
- [ ] Add NCCL or `torch.distributed` benchmark output where available.
- [ ] Add retry or fallback policy for slow/unhealthy providers.
- [ ] Add benchmark task for room throughput.


### 19.2A Observability Layer

Beyond the training dashboard, the platform should expose operational visibility suitable for long-running distributed systems.

#### Platform Observability

- [ ] Integrate metrics collection for coordinator and providers.
- [ ] Support Grafana dashboards where available.
- [ ] Centralize application logs.
- [ ] Add distributed tracing hooks.
- [ ] Monitor coordinator health.
- [ ] Monitor provider health.
- [ ] Record historical resource utilization.
- [ ] Record historical job metrics.
- [ ] Add alerting hooks for failed or unhealthy jobs.
- [ ] Add capacity-planning metrics.
- [ ] Support historical performance comparisons across runs.

### 19.3 Design 5 — Training Run Dashboard

**Purpose:** Give the host a clear control panel for understanding the entire distributed run.

Without this dashboard, a user may only know that a run failed or completed. The dashboard should make it possible to determine which worker failed, whether GPUs were underused, whether the network was the bottleneck, and whether adding GPUs improved training speed.

#### Run Overview

- [ ] Add training run detail page.
- [ ] Show job name and ID.
- [ ] Show room.
- [ ] Show model and dataset references.
- [ ] Show selected strategy.
- [ ] Show start time, elapsed time, and terminal status.
- [ ] Show planner readiness result.
- [ ] Show placement explanation.
- [ ] Show active warnings.

#### Worker and GPU View

- [ ] Show participating providers.
- [ ] Show worker IDs.
- [ ] Show global and local ranks.
- [ ] Show GPU model and device index.
- [ ] Show worker state.
- [ ] Show provider heartbeat status.
- [ ] Show GPU utilization.
- [ ] Show VRAM usage.
- [ ] Show temperature and power when available.
- [ ] Highlight failed, disconnected, or stalled workers.

#### Training Metrics

- [ ] Show current step or epoch.
- [ ] Show loss when reported.
- [ ] Show step time.
- [ ] Show samples/sec or tokens/sec.
- [ ] Show scaling efficiency.
- [ ] Show estimated completion time when practical.
- [ ] Show checkpoint progress.
- [ ] Show final artifact reference.

#### Logs and Failure Diagnosis

- [ ] Show combined logs.
- [ ] Allow filtering logs by worker.
- [ ] Show startup errors.
- [ ] Show runtime errors.
- [ ] Show cancellation and timeout reasons.
- [ ] Show the first failing worker.
- [ ] Show cleanup and GPU release status.
- [ ] Redact secrets.

#### Communication and Bottleneck View

- [ ] Show provider-group topology.
- [ ] Show measured or estimated latency.
- [ ] Show measured or estimated bandwidth.
- [ ] Show NCCL or `torch.distributed` benchmark result when available.
- [ ] Show whether the run appears memory-bound, compute-bound, communication-bound, startup-bound, or queue-bound.
- [ ] Show scheduler notes explaining why the provider group was selected.
- [ ] Compare predicted readiness with observed performance.

#### Reporting

- [ ] Show checkpoint and artifact links.
- [ ] Add exportable run summary.
- [ ] Include configuration, placement, metrics, warnings, and outcome.
- [ ] Add a compact reviewer/demo mode if practical.

### 19.4 SDK, CLI, and Demo Polish

- [ ] Add or update Python SDK commands for rooms, providers, tasks, training jobs, logs, and results.
- [ ] Add CLI commands for common room/training workflows.
- [ ] Add one-command or guided local demo.
- [ ] Add cloud coordinator demo.
- [ ] Add multi-GPU training demo instructions.
- [ ] Add architecture diagram.
- [ ] Add troubleshooting guide.
- [ ] Add release checklist.

### 19.5 Acceptance Criteria

- Team can run a clear demo from fresh clone or documented setup.
- Demo shows room creation, provider join, GPU reporting, multi-GPU scheduling, and a training/fine-tuning run.
- Dashboard shows performance and efficiency metrics.
- README explains the product clearly.
- Docs explain limits and realistic expectations.
- CI validates the no-GPU smoke path.

---

# End-to-End Success Criteria for the Five Designs

The Phase 10–19 roadmap is complete only when the five designs work together as one workflow.

## Functional Flow

- Host creates or selects a room.
- Providers join through the supported room transport.
- Providers report GPU and runtime capabilities.
- Host submits a first-class training job.
- Readiness planner evaluates feasibility.
- Communication/topology information contributes to placement.
- Scheduler selects and atomically reserves a compatible GPU group.
- Distributed launcher assigns ranks and starts all workers.
- Workers report logs, metrics, checkpoints, and terminal state.
- Dashboard shows the full run and explains performance or failure.
- All GPU reservations are released after completion, failure, cancellation, or timeout.

## Reliability

- No partial GPU reservation remains after a failed launch.
- A revoked provider cannot participate.
- A disconnected provider causes a clear, deterministic run outcome.
- Worker startup and completion calls are idempotent where practical.
- Checkpoint and artifact references remain attached to the run.
- Failure reasons are visible to both API clients and UI users.

## Realism

- The system does not describe aggregate VRAM as automatically equivalent to one larger GPU.
- Readiness output distinguishes per-GPU memory from aggregate room memory.
- Same-machine and same-LAN placement are preferred before WAN placement for the MVP.
- Unsupported strategies are rejected rather than silently approximated.
- Performance claims are backed by measured metrics.

## Demo Readiness

- A documented small-model training or fine-tuning example exists.
- The example can run in a controlled multi-GPU environment.
- A no-GPU simulation path exists for CI and contributor development.
- The demo includes room creation, provider join, scheduling, launch, live monitoring, and artifacts.
- README and architecture docs explain limitations honestly.


# Future Expansion Gates

These are not part of the Phase 10–19 implementation plan unless the team explicitly promotes them.

## OpenAI-Compatible Inference Gateway

- [ ] Consider only after real execution and model/runtime inventory are stable.
- [ ] Add `/v1/models`.
- [ ] Add `/v1/chat/completions`.
- [ ] Add `/v1/embeddings`.
- [ ] Route inference to compatible room providers.

## Model Registry and Runtime-Aware Routing

- [ ] Track installed models per provider.
- [ ] Track runtime support per provider.
- [ ] Route jobs based on model availability and warm/cold state.

## Usage Accounting, Credits, and Quotas

- [ ] Track GPU seconds.
- [ ] Track VRAM-hours.
- [ ] Track provider contribution.
- [ ] Track user/room quotas.
- [ ] Add reports for teams/labs.

## Cloud Bursting

- [ ] Use room GPUs first.
- [ ] Launch cloud GPU only when policy allows.
- [ ] Auto-join cloud instance as temporary provider.
- [ ] Shut down idle cloud provider.

## Overlay or Relay Data Plane

- [ ] Add direct or relay path for large payloads only if coordinator-mediated transfer becomes a bottleneck.
- [ ] Track path type and relay bytes.
- [ ] Keep dial-out control path as the primary reliable base.

## Advanced Distributed Training Strategies

- [ ] Add deeper FSDP support.
- [ ] Add ZeRO-style optimizer sharding.
- [ ] Add pipeline parallelism.
- [ ] Add tensor parallelism.
- [ ] Add topology-aware automatic strategy selection.

