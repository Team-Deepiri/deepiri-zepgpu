# ZepGPU Phase 10–19 Revised Implementation Roadmap

## Project Vision

ZepGPU should evolve from a serverless GPU task framework into a **host-created distributed GPU room network** that can support real fine-tuning and distributed training over heterogeneous provider machines.

A host should be able to:

- Create a GPU room.
- Invite provider machines through NAT-friendly, outbound-only networking.
- See provider identity, health, GPU capacity, runtime compatibility, and path quality.
- Dispatch work through a reliable coordinator-mediated lifecycle.
- Run reproducible single-node and multi-node LoRA/QLoRA workloads.
- Exchange training updates through a binary data path that never depends on the legacy pickle task router.
- Coordinate compressed WAN training and topology-aware high-bandwidth GPU islands.
- Recover runs from provider failure, coordinator restart, and checkpoint restore.
- Understand performance, bottlenecks, failures, and artifacts through a production-ready dashboard.

The flagship workload is **multi-GPU LLM training and fine-tuning across provider machines connected through consumer internet**, while preserving support for general GPU workloads.

---

# Current Baseline

This roadmap assumes Phases 0–9 already exist and should not be restarted or renumbered.

The baseline includes:

- Core task framework, API, database, Redis/Celery queue, UI, monitoring, and deployment foundations.
- Room and VPN compatibility.
- Room creation, invites, peer membership, and GPU-pool reporting.
- Room-scoped heartbeat and GPU metrics.
- Room-aware task assignment.
- Remote no-op execution through a node agent.
- Room dashboard and room/task visibility.
- Local room simulation.
- Phase 9 research on cloud deployment, NAT-friendly connectivity, low-communication distributed training, GPU islands, compression, and the memory wall.

Phases 10 and 11 are complete. Later phases build on that verified baseline.

---

# Architecture Principles

## Control Plane vs Training Data Plane

| Plane | Responsibilities | Primary Technologies |
|---|---|---|
| **Control plane** | Rooms, invites, provider identity, authorization, heartbeats, assignment lifecycle, scheduling, checkpoints, audit, WebSockets | FastAPI, Postgres, Redis, Celery, HTTPS/WSS |
| **Provider agent** | Join, persist identity, heartbeat, receive assignments, run workloads, report status, logs, metrics, and artifacts | Python CLI/agent, HTTPS/WSS |
| **Training data plane** | Binary update transfer, compressed synchronization, direct or relayed exchange, persistent workers | PCCL or equivalent, binary HTTPS/WSS relay fallback, later overlay |
| **High-bandwidth island** | Pool memory and execute FSDP/tensor-parallel workloads inside same-host or LAN-class groups | PyTorch FSDP2, NCCL, optional TP |
| **WAN synchronization** | Exchange infrequent compressed updates between workers or islands | LoRA/QLoRA, DeMo or equivalent, DiLoCo, overlap, min-k sync |

## Non-Negotiable Constraints

- Training code must not use the legacy pickle/base64 task path.
- Aggregate room VRAM must never be described as automatically equivalent to one larger GPU.
- FSDP or tensor parallelism must be limited to high-bandwidth groups.
- WAN training should use infrequent and compressed synchronization.
- Providers should not require inbound ports for the normal cloud-room workflow.
- Existing WireGuard rooms must remain compatible until deliberately migrated.
- Metrics and measured evidence must begin before the final phase.
- Literature-class utilization is aspirational, not guaranteed on consumer hardware.

---

# Revised Phase Summary

| Phase | Title | Primary Outcome |
|---|---|---|
| 10 | Baseline Hardening and Local Simulation Gate | Reliable, repeatable room-network baseline |
| 11 | Cloud Coordinator Packaging and Runbooks | Deployable always-on coordinator |
| 12 | NAT-Friendly Provider Join, Identity, and Trust | Secure outbound-only provider onboarding |
| 13 | Dial-Out Assignment Lifecycle and Provider Recovery | Reliable claims, leases, results, cancellation, and restart recovery |
| 14 | Transport Modes, Provider Capabilities, and Path Observability | WireGuard/dial-out coexistence with hardware and path visibility |
| 15 | Single-Node LoRA/QLoRA Training Baseline | Reproducible single-GPU training and metric foundation |
| 16 | Persistent Training Workers and Binary Data Channel | Long-lived workers and non-pickle transfer |
| 17 | Two-Node WAN LoRA with Compressed Updates | First real communication-efficient WAN training run |
| 18 | Elastic DiLoCo Training and Topology-Aware GPU Islands | Elastic WAN training plus island-local memory pooling |
| 19 | Overlay Networking, Recovery, Mixed Hardware, and Production Pilot | Hard-NAT data plane, recovery, integrity, observability, and pilot release |

---

# Implementation Phases

## Phase 10: Baseline Hardening and Local Simulation Gate

**Status:** Complete

**Goal:** Make the existing room-network path reliable enough to serve as the foundation for cloud and distributed-training work.

### 10.1 Local Room Simulation

- [x] Add or update `docs/room_network_local_testing.md`.
- [x] Add or update `scripts/verify_room_network_local_simulation.py`.
- [x] Verify coordinator startup, registration/login, room creation, invite creation, provider join, heartbeat, GPU pool, no-op dispatch, completion, results, and live updates.

### 10.2 Reliability

- [x] Preserve `/api/v1/vpn/*` compatibility.
- [x] Harden assignment lifecycle idempotency where practical.
- [x] Release GPU locks after failure.
- [x] Mark stale providers unhealthy.
- [x] Add room-access, cross-room denial, and regression tests.

### 10.3 Documentation

- [x] Add room-network quick start.
- [x] Document one coordinator plus one simulated provider.
- [x] Document common failure modes.
- [x] Separate simulation-only behavior from real-provider-ready behavior.

### 10.4 Acceptance Criteria

- Local simulation is repeatable.
- A simulated provider and its GPU metrics appear in the room.
- A room no-op task completes through the node-agent path.
- Existing VPN routes still work.
- Tests pass locally.

---

## Phase 11: Cloud Coordinator Packaging and Runbooks

**Status:** Complete

**Goal:** Package the coordinator for managed or self-hosted deployment without requiring a GPU.

### 11.1 Deployment Artifact

- [x] Add production Compose.
- [x] Include API, optional UI, Postgres, Redis, Celery worker, and Celery beat.
- [x] Add critical-service health checks.
- [x] Keep development Compose working.

### 11.2 URL, TLS, and Reverse Proxy

- [x] Add Caddy or nginx reverse-proxy example.
- [x] Add public coordinator URL configuration.
- [x] Document HTTPS, WSS, CORS, and WireGuard UDP requirements.
- [x] Document that dial-out providers require no inbound ports.

### 11.3 Runbooks and Smoke Tests

- [x] Add `docs/deploy/cloud_coordinator.md`.
- [x] Document managed and self-hosted deployment.
- [x] Document resource assumptions, secrets, backup/restore, persistence, and troubleshooting.
- [x] Add smoke tests for health, register/login, room creation, invite creation, and room listing.

### 11.4 Acceptance Criteria

- A fresh laptop can run the coordinator stack.
- Coordinator operation does not require a GPU.
- UI and API are reachable through documented HTTPS routing.
- Phase 10 simulation still works.

---

## Phase 12: NAT-Friendly Provider Join, Identity, and Trust

**Goal:** Let providers join rooms through outbound-only HTTPS/WSS using one invite command, persistent agent identity, and room-scoped credentials.

This phase absorbs the critical provider-security work that previously appeared in the old Phase 16.

### 12.1 Provider CLI and Join UX

- [ ] Add or update `zepgpu-node join --invite <code> --coordinator <url>`.
- [ ] Add or update `zepgpu-node serve`.
- [ ] Add or update `zepgpu-node status`.
- [ ] Add logout, disconnect, or credential-reset command.
- [ ] Include coordinator URL and one-line command in invite copy text.
- [ ] Return clear errors for invalid, expired, exhausted, or revoked invites.
- [ ] Reject non-HTTPS coordinator URLs outside localhost/dev.
- [ ] Require no inbound provider ports.

### 12.2 Persistent Provider Identity

- [ ] Persist config under `~/.zepgpu/agent.json` or equivalent.
- [ ] Store coordinator URL, room ID, provider ID, node name, token, token expiry, heartbeat interval, and agent version.
- [ ] Never print token values in normal logs.
- [ ] Define reconnect behavior for an already-registered provider.

### 12.3 Room-Scoped Provider Tokens

- [ ] Keep provider tokens separate from human JWTs.
- [ ] Scope each token to one room and provider identity.
- [ ] Add expiration, rotation, revocation, and optional last-used tracking.
- [ ] Ensure revoked providers cannot heartbeat, poll, claim, submit logs, or complete tasks.
- [ ] Reject cross-room heartbeat, claim, status, log, and completion requests.
- [ ] Redact provider tokens from logs, API errors, UI, and audit payloads.

### 12.4 Invite and Membership Rules

- [ ] Enforce invite expiry, maximum uses, and revocation.
- [ ] Prevent unintended duplicate provider joins.
- [ ] Preserve WireGuard config generation for WireGuard rooms.
- [ ] Add host/admin provider revoke action.
- [ ] Release or fail active assignments after provider revocation.

### 12.5 Authenticated Heartbeat

- [ ] Authenticate heartbeat with the room-scoped provider token.
- [ ] Include agent version, node name, provider mode, basic GPU inventory, free memory, and utilization.
- [ ] Update token last-used timestamp where practical.
- [ ] Reject expired, revoked, stale, or cross-room credentials clearly.

### 12.6 Tests

- [ ] Test successful join and persisted identity.
- [ ] Test invalid, expired, exhausted, and revoked invites.
- [ ] Test expired, rotated, and revoked provider tokens.
- [ ] Test cross-room heartbeat and claim denial.
- [ ] Test HTTPS enforcement.
- [ ] Test token redaction.

### 12.7 Acceptance Criteria

- A provider joins with one copied command.
- Provider identity persists across restarts.
- Provider heartbeats through outbound HTTPS/WSS.
- Revoked or expired credentials stop working.
- Cross-room access is rejected.
- Existing room and WireGuard join paths remain intact.

---

## Phase 13: Dial-Out Assignment Lifecycle and Provider Recovery

**Goal:** Harden assignment delivery, claims, leases, completion, logs, cancellation, retries, stale-task cleanup, and provider restart recovery.

This phase builds the **control-plane lifecycle**, not the training data channel.

### 13.1 Assignment Delivery

- [ ] Prefer WSS push notification when available.
- [ ] Keep HTTPS polling/claim as fallback.
- [ ] Add backoff and jitter when no work exists.
- [ ] Add reconnect behavior after coordinator or network interruption.
- [ ] Define behavior when room or provider access disappears.

### 13.2 Claims and Leases

- [ ] Add or harden assignment claim endpoint.
- [ ] Add `claimed_at`, `lease_expires_at`, and a claim token/generation if missing.
- [ ] Restrict claim to the assigned room/provider.
- [ ] Make duplicate claim/start/complete/fail calls deterministic.
- [ ] Prevent cancelled tasks from completing.
- [ ] Prevent expired leases from reviving silently.

### 13.3 Provider Restart and Reconnect

- [ ] Persist enough local state to identify in-flight assignments.
- [ ] Add coordinator reconciliation endpoint.
- [ ] Define resume, fail, or abandon behavior by state.
- [ ] Recover valid leases after restart.
- [ ] Reject stale local state after lease expiry.
- [ ] Reconcile buffered logs/results after temporary disconnection.

### 13.4 Cancellation, Timeout, and Cleanup

- [ ] Add accepted-but-never-started timeout.
- [ ] Add running timeout.
- [ ] Propagate cancellation to provider.
- [ ] Release GPU locks on failure, timeout, cancellation, or lease expiry.
- [ ] Requeue or fail according to explicit retry policy.
- [ ] Record deterministic terminal reasons.
- [ ] Prevent duplicate cleanup from releasing another task's reservation.

### 13.5 Logs, Results, and Events

- [ ] Standardize result metadata.
- [ ] Add batched/chunked log submission.
- [ ] Add result and artifact-reference submission.
- [ ] Broadcast task state through WebSocket.
- [ ] Trigger callback webhook after terminal state.
- [ ] Add activity events for assigned, claimed, started, reconnecting, completed, failed, cancelled, timed out, and lease expired.
- [ ] Record the first terminal cause and ignore conflicting later calls.

### 13.6 Tests

- [ ] Test success, failure, cancellation, timeout, lease expiry, and disconnect.
- [ ] Test restart with valid and expired leases.
- [ ] Test duplicate lifecycle calls.
- [ ] Test callback and WebSocket terminal updates.
- [ ] Test GPU release for every terminal path.

### 13.7 Acceptance Criteria

- Provider receives work through WSS or HTTPS fallback.
- Provider can claim, start, complete, fail, and cancel assignments.
- Duplicate lifecycle calls are safe.
- Restarted providers reconcile state deterministically.
- Timed-out and failed assignments release capacity.
- No training payloads are transferred through this lifecycle.

---

## Phase 14: Transport Modes, Provider Capabilities, and Path Observability

**Goal:** Support WireGuard and dial-out modes while reporting provider GPU inventory, runtime compatibility, health reasons, and path characteristics.

This phase absorbs the capability-inventory portion of the old Phase 15.

### 14.1 Transport Modes

- [ ] Add `wireguard`, `dialout`, and `overlay` modes.
- [ ] Persist `transport_mode` on rooms/networks.
- [ ] Default existing rows to `wireguard` and new cloud rooms to `dialout`.
- [ ] Add a configurable default.
- [ ] Expose mode in API and UI.
- [ ] Keep overlay experimental until Phase 19.

### 14.2 Routing Compatibility

- [ ] Preserve legacy WireGuard routing.
- [ ] Formalize dial-out routing.
- [ ] Select strategy from room mode.
- [ ] Ensure dial-out requires no UDP 51820.
- [ ] Preserve WireGuard config generation.
- [ ] Quarantine legacy pickle execution to WireGuard-only generic tasks.
- [ ] Add a guard preventing training modules from using the legacy task router.

### 14.3 Provider Capability Inventory

- [ ] Report GPU count, model, device index, total/free VRAM, utilization, temperature, and power where available.
- [ ] Report compute capability, driver, CUDA, PyTorch, container runtime, NCCL, and optional FSDP/DeepSpeed support.
- [ ] Report P2P access, NVLink, and PCIe/topology hints where detectable.
- [ ] Timestamp capability reports and mark unavailable fields explicitly.

### 14.4 Provider Health Reasons

- [ ] Distinguish healthy, degraded, stale, offline, revoked, incompatible, and claim-timeout states.
- [ ] Record last heartbeat, last claim, recent failures, and version mismatch.
- [ ] Expose a human-readable health reason through API, events, and UI.

### 14.5 Path Observability

- [ ] Record path type: `direct`, `relay`, or `unknown`.
- [ ] Record path class: `same_host`, `lan`, `wan`, or `relay`.
- [ ] Measure provider-to-coordinator RTT.
- [ ] Add optional provider-to-provider RTT and bandwidth samples.
- [ ] Track measurement freshness.
- [ ] Distinguish measured values from estimates.
- [ ] Add Prometheus metrics and NAT/path troubleshooting docs.

### 14.6 Tests and Acceptance

- [ ] Test migration defaults and mode coexistence.
- [ ] Test capability validation and stale data.
- [ ] Test provider-health transitions.
- [ ] Test path reporting.
- [ ] Test training-code prohibition on legacy task router.

Acceptance criteria:

- Existing WireGuard rooms still work.
- Dial-out rooms work without inbound provider ports.
- API/UI expose transport mode, capabilities, health reason, and path data.
- Training code cannot use the legacy pickle path.

---

## Phase 15: Single-Node LoRA/QLoRA Training Baseline

**Goal:** Build a reproducible single-GPU fine-tuning harness with LoRA or QLoRA, mixed precision, checkpointing, peak-VRAM tracking, throughput metrics, and communication-to-compute instrumentation.

This phase starts real training earlier. Full multi-GPU scheduling and reservations move to Phase 18.

### 15.1 Training Package

- [ ] Add `deepiri_zepgpu/training/`.
- [ ] Keep ML dependencies optional.
- [ ] Add a versioned training-run configuration model.
- [ ] Add local training CLI/script.
- [ ] Ensure no dependency on the legacy pickle task router.
- [ ] Add a small reproducible model and dataset example.

### 15.2 LoRA/QLoRA Baseline

- [ ] Support LoRA and compatible QLoRA.
- [ ] Support bf16/fp16 and 4-bit base loading where available.
- [ ] Support gradient accumulation and activation/gradient checkpointing.
- [ ] Support configurable sequence length, batch size, and seed.
- [ ] Add short smoke-run mode.
- [ ] Support checkpoint save/resume.
- [ ] Save adapter or final artifact reference.

### 15.3 Metric Harness

- [ ] Record tokens/s, samples/s, step time, useful compute time, sync time, bytes sent/received, communication-to-compute ratio, peak allocated/reserved VRAM, and GPU utilization.
- [ ] Record model, dataset, precision, batch size, sequence length, software versions, and hardware.
- [ ] Emit JSON metrics and a human-readable summary.
- [ ] Report single-node synchronization bytes/time and ratio as zero.

### 15.4 Reproducibility and Tests

- [ ] Document one RTX-class setup, minimum VRAM, and tested runtime versions.
- [ ] Store at least one baseline result.
- [ ] Add no-GPU schema/metric tests for CI.
- [ ] Add optional GPU integration test.
- [ ] Test config validation, ratio math, checkpoint metadata, resume state, secret filtering, and task-router isolation.

### 15.5 Acceptance Criteria

- One GPU completes a short LoRA/QLoRA run.
- Training produces a checkpoint or adapter artifact.
- Harness reports throughput, VRAM, compute, sync, bytes, and ratio.
- Single-node ratio is zero.
- The baseline is reproducible and becomes the Phase 17 comparison target.

---

## Phase 16: Persistent Training Workers and Binary Data Channel

**Goal:** Create long-lived provider training workers and a direct-or-relayed binary channel that avoids the legacy pickle and JSON task path.

### 16.1 Training-Run Lifecycle

- [ ] Add first-class training-run records and states: `created`, `preparing`, `ready`, `running`, `syncing`, `checkpointing`, `completed`, `failed`, `cancelled`, and `timed_out`.
- [ ] Link runs to room, user, providers, and artifacts.
- [ ] Add create, inspect, start, abort, and list APIs.
- [ ] Keep training runs separate from generic one-shot tasks.

### 16.2 Persistent Worker

- [ ] Add long-lived training-worker mode.
- [ ] Keep workers alive across synchronization rounds.
- [ ] Authenticate with provider identity and optional short-lived run credentials.
- [ ] Add ready, heartbeat/progress, graceful shutdown, forced abort, restart, and reconnect behavior.
- [ ] Buffer progress/logs during short coordinator outages.

### 16.3 Binary Exchange Format

- [ ] Define a versioned binary envelope with run ID, worker ID, round, payload type, shape/dtype, compression metadata, length, checksum, and timestamp.
- [ ] Reject malformed, mismatched, duplicate-conflicting, or cross-room payloads.
- [ ] Keep the format extensible for later mixed hardware.

### 16.4 Direct and Relayed Transfer

- [ ] Prefer direct worker-to-worker or collective transfer.
- [ ] Add coordinator binary relay fallback using chunked HTTPS or WSS binary.
- [ ] Avoid JSON/base64 and pickle.
- [ ] Add transfer IDs, idempotency, retries, size limits, cleanup, and direct-vs-relay metrics.
- [ ] Evaluate PCCL as the default direct channel while keeping an abstract interface.

### 16.5 Integrity and Tests

- [ ] Verify checksum, run ID, worker ID, round, and room scope.
- [ ] Test persistent worker lifecycle, direct exchange, relay fallback, corruption, malformed metadata, duplicates, retry, cleanup, and cross-room denial.
- [ ] Test that no training module imports or calls pickle task routing.

### 16.6 Acceptance Criteria

- Two simulated workers remain alive across multiple rounds.
- Workers exchange binary payloads directly and through relay fallback.
- Checksums detect corruption.
- Transfer metrics record bytes, path, and duration.
- Training traffic never uses the legacy pickle path.

---

## Phase 17: Two-Node WAN LoRA with Compressed Updates

**Goal:** Run real two-node LoRA fine-tuning over consumer internet using compressed updates, communication overlap, and measured efficiency improvements.

Container execution is supporting infrastructure; the main outcome is real WAN training.

### 17.1 Safe Training Runtime

- [ ] Define a training workload/container spec with image/runtime, command, GPU assignment, secret-filtered environment, model/dataset references, timeout, logs, checkpoints, and artifacts.
- [ ] Disable privileged containers by default.
- [ ] Restrict mounts and add an MVP image trust policy.
- [ ] Clean up containers and temporary data after terminal state.

### 17.2 Two-Worker LoRA Run

- [ ] Launch two provider workers in one room.
- [ ] Validate matching base model, tokenizer, precision, and adapter structure.
- [ ] Run independent local steps.
- [ ] Exchange adapter deltas or pseudo-gradients through Phase 16.
- [ ] Apply synchronized updates over multiple rounds.
- [ ] Save final adapter/checkpoint and both workers' metrics.

### 17.3 Compressed Updates

- [ ] Integrate DeMo or a documented equivalent.
- [ ] Support low-bit representation and configurable compression knobs.
- [ ] Add error feedback where required.
- [ ] Record uncompressed/compressed bytes and compression ratio.
- [ ] Validate decompression and update shape.
- [ ] Add a toy convergence test.

### 17.4 Communication Overlap and Metrics

- [ ] Overlap transfer with local compute where practical.
- [ ] Record blocked and overlapped communication time, useful compute time, ratio, bytes per step/round, sync frequency, GPU utilization, RTT, and bandwidth.
- [ ] Make blocking fallback explicit.

### 17.5 Baseline Comparison and Failure Handling

- [ ] Compare loss/quality, tokens/s, VRAM, bytes, and ratio against Phase 15 and a naive full-precision baseline.
- [ ] Record hardware, network, model, dataset, and exact settings.
- [ ] Abort both workers if one required worker fails.
- [ ] Propagate cancellation and timeout.
- [ ] Preserve the latest valid checkpoint.
- [ ] Release locks and clean up runtime resources.

### 17.6 Acceptance Criteria

- Two NAT-friendly providers complete a short LoRA fine-tune.
- Training uses binary compressed updates.
- Direct and relay paths both work.
- Bytes per round are below the documented naive baseline.
- Communication-to-compute ratio is measured.
- Quality remains within an agreed tolerance of Phase 15.

---

## Phase 18: Elastic DiLoCo Training and Topology-Aware GPU Islands

**Goal:** Add infrequent WAN synchronization, overlap, straggler tolerance, elastic join/leave, checkpoint recovery, topology-aware grouping, multi-GPU reservations, and FSDP/TP inside high-bandwidth islands.

This phase absorbs the old Phase 15 scheduler and reservation work.

### 18.1 Distributed Training Job

- [ ] Add a first-class training-job spec with model, dataset, runtime, nodes, GPUs/node, total GPUs, minimum VRAM/GPU, precision, LoRA/QLoRA settings, DiLoCo `H`, minimum `k`, sync deadline, checkpoint interval, max runtime, resume policy, and runtime requirements.

### 18.2 Readiness and Placement Planner

- [ ] Filter by health, GPU count, per-GPU VRAM, runtime compatibility, reliability, path class, RTT, and bandwidth.
- [ ] Prefer same-host and LAN islands.
- [ ] Avoid WAN FSDP/TP.
- [ ] Generate candidate groups and return `capable`, `marginal`, or `insufficient` with warnings and actionable reasons.
- [ ] Store the selected plan and clearly label estimates.

### 18.3 Atomic Multi-GPU Reservations

- [ ] Reserve all required GPUs atomically.
- [ ] Roll back every reservation on partial failure.
- [ ] Add TTL, ownership, idempotent release, stale cleanup, and audit events.
- [ ] Prevent one task from releasing another task's reservation.

### 18.4 Topology-Aware Islands

- [ ] Define island membership.
- [ ] Group same-host and supported LAN-class providers.
- [ ] Use Phase 14 capability/path data.
- [ ] Record interconnect class, runtime compatibility, aggregate capacity, and grouping explanation.
- [ ] Keep WAN peers outside FSDP/TP islands.

### 18.5 Island-Local Memory Pooling

- [ ] Add FSDP2 inside compatible islands.
- [ ] Add TP only where interconnect supports it.
- [ ] Support one multi-GPU machine first, then controlled LAN islands.
- [ ] Record rank/process-group config and peak VRAM/GPU.
- [ ] Demonstrate a model that OOMs on one GPU but runs in an island.

### 18.6 DiLoCo and Elasticity

- [ ] Implement local inner optimization and configurable outer interval `H`.
- [ ] Implement outer optimizer.
- [ ] Add eager or streaming overlap.
- [ ] Reuse Phase 17 compression.
- [ ] Record outer-round bytes and communication ratio.
- [ ] Add late-join checkpoint bootstrap, graceful leave, failure detection, min-k sync, late-update policy, and rejoin.
- [ ] Add chaos test that kills one worker.

### 18.7 Distributed Launcher

- [ ] Create training groups, attach placement plans, assign worker/island IDs and ranks, generate short-lived credentials, enforce readiness/startup deadlines, prevent duplicate starts, propagate cancellation, and release reservations after terminal state.

### 18.8 Acceptance Criteria

- Scheduler explains feasibility.
- GPUs are reserved atomically.
- Same-host/LAN islands are preferred for FSDP/TP.
- WAN links use compressed outer synchronization.
- Configurable `H` and min-k sync are demonstrated.
- Worker drop/rejoin works from checkpoint.
- A model that OOMs on one GPU runs on a supported island.

---

## Phase 19: Overlay Networking, Recovery, Mixed Hardware, and Production Pilot

**Goal:** Add hard-NAT overlay networking, durable checkpoint recovery, integrity checks, neutral update formats, optional mixed-hardware support, dashboards, soak tests, and a reproducible production pilot.

### 19.1 Overlay Networking

- [ ] Define overlay interface: `connect`, `send`, `receive`, `close`, and `path_type`.
- [ ] Implement iroh or equivalent direct-to-relay QUIC path.
- [ ] Add `transport_mode=overlay`.
- [ ] Prefer direct and fall back to relay.
- [ ] Keep coordinator binary relay as fallback.
- [ ] Preserve WireGuard and dial-out coexistence.
- [ ] Record direct/relay success, relay bytes, and NAT-join results.
- [ ] Add migration guidance without forcing migration.

### 19.2 Durable Checkpoint and Recovery

- [ ] Store model/adapter, optimizer, outer-optimizer, round, membership, config, compression settings, and artifact references.
- [ ] Restore after coordinator or provider restart.
- [ ] Bootstrap late joiners.
- [ ] Verify compatibility and reject partial/corrupt checkpoints.
- [ ] Document retention and backup.

### 19.3 Neutral Update Format and Integrity

- [ ] Define framework-neutral outer-update schema using safetensors, NumPy, or equivalent.
- [ ] Include model revision, parameter names/shapes, dtype, quantization, round, worker identity, and checksum.
- [ ] Add room-scoped signature or MAC.
- [ ] Reject tampered and replayed updates.
- [ ] Keep the format extensible for MLX.

### 19.4 Optional Mixed Hardware

- [ ] Add experimental Apple/MLX worker path.
- [ ] Keep NVIDIA/PyTorch primary.
- [ ] Produce the same neutral update format.
- [ ] Document homogeneous quantization restrictions.
- [ ] Add simulated mixed-worker test and a real Mac+NVIDIA experiment when hardware is available.

### 19.5 Observability and Dashboard

- [ ] Add coordinator, provider, worker, queue, GPU, WAN-byte, direct/relay, sync-round, checkpoint, failure, and rejoin metrics.
- [ ] Add structured logs and trace IDs.
- [ ] Add Grafana dashboards and alerts where available.
- [ ] Add historical run comparison.
- [ ] Build a training-run dashboard showing job, placement, islands, workers/ranks, provider health, GPU usage, loss, throughput, synchronization, communication ratio, path, checkpoints, logs, first failure, cleanup, and exported reports.

### 19.6 Soak, Failure, and Recovery Tests

- [ ] Run multi-hour soak test.
- [ ] Restart coordinator, Redis according to persistence policy, and one provider.
- [ ] Drop/restore network connectivity.
- [ ] Force relay fallback.
- [ ] Corrupt a transfer and checkpoint.
- [ ] Revoke a provider mid-run.
- [ ] Confirm deterministic recovery or terminal outcomes.
- [ ] Confirm no leaked reservations, containers, or relay blobs.

### 19.7 Production Pilot

- [ ] Add a reproducible pilot runbook.
- [ ] Define supported hardware/runtime matrix, deployment, network assumptions, model/dataset, runtime, checkpoint policy, and limitations.
- [ ] Run one controlled multi-provider pilot.
- [ ] Record hardware, network, metrics, failures, and outcome.
- [ ] Publish architecture diagram, troubleshooting guide, release checklist, no-GPU CI path, and optional GPU integration workflow.

### 19.8 Acceptance Criteria

- Hard-NAT providers exchange training data through direct or relay overlay.
- Existing WireGuard and dial-out rooms remain supported.
- A run resumes from a durable checkpoint after a documented failure.
- Tampered updates are rejected.
- Dashboard explains workers, islands, GPU use, communication, checkpoints, and failure.
- Soak tests leave no leaked reservations or workloads.
- Team can reproduce a documented production pilot.
- Performance claims are backed by measured hardware and network data.

---

# End-to-End Success Criteria

## Provider and Room Flow

- Host creates a room.
- Provider joins through one outbound-only command.
- Provider receives a persistent room-scoped identity.
- Revoked or cross-room credentials are rejected.
- Provider reports hardware, runtime, health, and path information.
- WireGuard, dial-out, and overlay modes coexist.

## Control-Plane Reliability

- Assignments support WSS notification and HTTPS fallback.
- Claims and lifecycle transitions are idempotent where practical.
- Leases expire predictably.
- Provider restart recovery is deterministic.
- Logs, results, callbacks, and WebSocket updates are preserved.
- Every terminal path releases GPU capacity.

## Training Progression

- Phase 15 proves one-GPU LoRA/QLoRA and baseline metrics.
- Phase 16 proves persistent workers and binary direct/relay exchange.
- Phase 17 proves two-node compressed WAN LoRA.
- Phase 18 proves elastic DiLoCo-style synchronization and island-local FSDP/TP.
- Phase 19 proves hard-NAT overlay, recovery, integrity, observability, and a production pilot.

## Realism

- Per-GPU VRAM is distinguished from aggregate room VRAM.
- FSDP/TP is restricted to high-bandwidth islands.
- WAN synchronization is compressed and infrequent.
- Unsupported strategies are rejected.
- Performance claims include hardware class and network conditions.
- Literature utilization is treated as aspirational, not guaranteed.

---

# Recommended Execution Order

```text
Phase 10  Complete baseline
Phase 11  Complete coordinator packaging
Phase 12  Secure NAT-friendly provider join
Phase 13  Reliable dial-out assignment lifecycle
Phase 14  Transport compatibility + capability/path visibility
Phase 15  Single-GPU LoRA/QLoRA baseline
Phase 16  Persistent workers + binary channel
Phase 17  Two-node compressed WAN LoRA
Phase 18  Elastic DiLoCo + topology-aware islands
Phase 19  Overlay + recovery + mixed hardware + production pilot
```

Recommended parallelization after Phase 11:

- Track A: Phases 12–14.
- Track B: Phases 15–16.
- Integrate both tracks before Phase 17.
- Complete Phase 17 before Phase 18.
- Complete Phase 18 before the Phase 19 pilot.

---

# Deferred Research and Expansion

These are not required for Phase 10–19 completion unless explicitly promoted:

- SparseLoCo, CocktailSGD, and alternative error-feedback compressors.
- Heterogeneous LoRA ranks and bandwidth-aware participation.
- Async local-SGD variants and non-IID drift mitigation.
- Content-addressed model/dataset distribution.
- DiLoCoX, pipeline parallelism, broader tensor parallelism, and ZeRO-style island sharding.
- Stronger verification, reputation systems, and ledger attestations.
- OpenAI-compatible inference gateway, model registry, usage accounting, cloud bursting, and multi-region coordinator HA.

