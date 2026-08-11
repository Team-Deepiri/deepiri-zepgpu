# Phase 17: Two-Node WAN LoRA with Compressed Updates

Phase 17 builds on the Phase 15 single-GPU harness and Phase 16 binary channel to run
two-worker LoRA fine-tuning with switchable compressed updates, direct-or-relay transfer,
overlap metrics, and a Docker training runtime **library**.

## What is supported today

| Path | Status |
|---|---|
| In-process two-worker LoRA (`direct_backend=memory`, `runtime.mode=process`) | **Supported** — `run_two_worker_training` |
| Compressors `zep` / `demo` / `none` | **Supported** |
| Eager overlap (prefetch during transfer) + blocked/overlapped metrics | **Supported** (unit-tested with `DelayedDirectChannel`) |
| Relay **upload + download** via transfer-id bus | **Supported** in sync (in-memory + HTTP client) |
| HTTP coordinator relay end-to-end (Phase 16/17 integration) | **Supported** — `test_phase17_http_relay_sync_orchestrator_roundtrip` |
| LAN loopback sync (`LanPairDirectChannel`) | **Supported** in tests; inject channel into runner |
| Runtime fail-closed allowlist / mount jail / process timeout | **Supported** (unit-tested) |
| True two-OS-process LoRA workers vs live coordinator | **Supported** — `scripts/run_two_process_wan_lora.py` |
| Supervised Docker workers (`zepgpu-training:local`) vs live coordinator | **Supported** — `scripts/run_docker_wan_lora.py` |

## Library present, not fully runner-integrated

| Path | Status |
|---|---|
| `LanDirectChannel` | Library + unit HMAC test; **not** selected by in-process runner |
| `PcclDirectChannel` | Adapter only; fails closed without a real sender |
| In-process `run_two_worker_training` + `runtime.mode=docker` | Rejected unless a channel is injected; use the Docker e2e script instead |

## Locked quality policy

- Always **record** Phase 17 vs Phase 15 (+ naive full-precision byte baseline).
- Compare compressed **bytes per round** to naive bytes per round (not totals vs per-round).
- Hard-fail only on catastrophic failure: non-completion, non-finite loss, toy compressor
  non-convergence, trust/privileged violations, or legacy pickle-router imports.
- Do **not** fail CI solely because loss is X% worse than Phase 15.

## Compressors

Config path: `distributed.compression.backend`

| Backend | Codec ID | Notes |
|---|---|---|
| `zep` | `zep-v1` | **ZepCompressor** — native DCT + top-k + error feedback + low-bit |
| `demo` | `demo-v1` | Adapted from [bloc97/DeMo](https://github.com/bloc97/DeMo) DCT/top-k path (vendored under `training/compression/vendor/demo/`) |
| `none` | `none` | Full-precision packing for naive byte baselines |

```console
poetry run zepgpu-train examples/training/tiny_wan_lora.json --wan --smoke --compressor zep
poetry run zepgpu-train examples/training/tiny_wan_lora.json --wan --smoke --compressor demo \
  --compare-phase15 docs/baselines/phase15_tiny_lora_rtx4050.json
```

## Direct backends

`distributed.direct_backend`:

| Value | Role |
|---|---|
| `memory` | In-process direct channel (**supported** by local runner) |
| `lan` | Authenticated TCP LAN/same-host channel — library only until multi-process wiring |
| `pccl` | Optional PCCL sender — fail closed unless a sender is injected |

`TransferManager` prefers direct and falls back to coordinator relay on
`DirectUnavailable` / `TimeoutError`. After relay upload, peers **download** via
`HttpRelayChannel.download` / `InMemoryRelayChannel.download` using a transfer-id bus.

## Overlap

- `overlap_mode=blocking`: all sync wait counted as blocked.
- `overlap_mode=eager`: run independent local work (batch prefetch) concurrent with transfer;
  `overlapped_sync_seconds = min(overlap_work, sync_wall)`; remainder is blocked.
- Pipelined next-round training on stale weights is **Phase 18**, not Phase 17.
- Wall-clock `step_seconds` includes blocked sync for fair Phase 15/17 compare.

## Docker training runtime

- Spec: `deepiri_zepgpu.training.workload.TrainingWorkloadSpec`
- Trust allowlist: [`docker/training-images.allowlist`](../docker/training-images.allowlist)
- CPU e2e image: [`docker/Dockerfile.training.cpu`](../docker/Dockerfile.training.cpu) tagged `zepgpu-training:local`
- CUDA image: [`docker/Dockerfile.training`](../docker/Dockerfile.training)
- Privileged containers are rejected
- Process mode is what the local in-process runner uses (`distributed.runtime.mode=process`)

```console
docker build -f docker/Dockerfile.training.cpu -t zepgpu-training:local .
poetry run python scripts/run_docker_wan_lora.py --base-url http://127.0.0.1:8000
```

Containers run as the host `uid:gid` (`docker --user`) with owner-only mount permissions (`0700`/`0600`). Do not world-chmod bind mounts.

## Two-OS-process workers (live coordinator)

```console
poetry run python scripts/run_two_process_wan_lora.py --base-url http://127.0.0.1:8000
```

Workers authenticate, emit `ready`, wait for `running`, then train with HTTP relay sync using
deterministic transfer IDs so peers can download without an in-memory bus.

Pass `--transport-mode dialout|wireguard|overlay`. Production workers launched by
`zepgpu-node` receive a **run-scoped** `data_plane_secret` (shared HMAC for all workers
on the run — not per-worker `run.cred`), plus `transport_mode`, `vpn_ip` (WG), and
`overlay_backend=iroh` (overlay). Peers publish `{host,port,kind}` over the training
worker API so discovery does not need a shared filesystem.

WireGuard LoRA uses LanDirect to the peer `vpn_ip` inside the UDP tunnel.
Overlay LoRA uses iroh/quic UDP; `--force-relay` still completes over HTTP.

## Metrics (schema v2)

Fields include `blocked_sync_seconds`, `overlapped_sync_seconds`, uncompressed/compressed
bytes, compression ratio, path type, RTT/bandwidth when measured, compressor/direct backends.
`communication_compute_ratio` uses **blocked** sync time only.
`direct_backend` in metrics reflects the backend that actually ran.

## Local verify

```console
poetry run python scripts/verify_phase_17_local.py
poetry run python scripts/verify_phase_17_local.py --run-training --compressor zep
```

## Manual WAN gate (Layer E)

Two NAT-friendly dial-out providers against a deployed coordinator remain a manual gate for
true cross-network WAN. Same-host two-process and Docker e2e scripts cover the coordinator
relay train loop locally.

## Baselines

| File | Purpose |
|---|---|
| [`docs/baselines/phase15_tiny_lora_rtx4050.json`](baselines/phase15_tiny_lora_rtx4050.json) | Single-node comparison target |
| [`docs/baselines/phase17_naive_fp_bytes.json`](baselines/phase17_naive_fp_bytes.json) | Documented naive full-precision bytes fixture |
| [`docs/baselines/phase17_wan_smoke_zep.json`](baselines/phase17_wan_smoke_zep.json) | Recorded WAN smoke metadata (`zep`); expand with metrics when hardware available |
