# Phase 18 elastic training

Phase 18 extends the existing versioned training contract with `schema_version=3` and a
`phase18` job section. Schema v2 remains the exactly-two-worker Phase 17 WAN runner.

The readiness planner consumes the existing room-scoped `Peer.capabilities_json`, path
observability, and `GpuShare` rows. It never infers missing P2P, NVLink, FSDP2, TP, CUDA,
PyTorch, or NCCL support. Same-host islands rank first. Multi-provider LAN islands require
fresh, measured provider-to-provider RTT and bandwidth samples in both directions for every
pair; provider-to-coordinator LAN classifications are not evidence of a LAN collective.
Compatible LAN islands rank second, and WAN providers remain independent DiLoCo workers.
FSDP2 and tensor parallel execution never form a WAN process group.

GPU reservations are stored in `training_gpu_reservations`. The service locks all selected
`gpu_shares` rows in deterministic order, validates the complete set, and changes both the
share ownership and reservation rows in one savepoint/transaction. A partial failure rolls
back every new claim. A PostgreSQL partial unique index permits only one active reservation
per share. Terminal run transitions and the background TTL sweep release only matching
training ownership claims. Ready/heartbeat/progress events renew only the reporting worker's
owned, active reservations to `now + reservation_ttl_seconds` (bounded to 30 seconds through
24 hours). The cleanup sweep locks in the same run→reservation→GPU order and skips a run
being renewed, so active heartbeats and expiry cannot race into an unsafe release.

The elastic coordinator performs `diloco_h` local steps before a compressed outer update.
It reuses the Phase 17 compressor and binary envelope, orders accepted updates by worker ID,
and applies a checkpointed outer SGD or Adam optimizer. Before the deadline all expected
active workers are preferred; at/after the deadline the round may finalize at `min_k`.
Finalized-round updates and duplicate worker updates are rejected. A failed/rejoining worker
must bootstrap the latest finalized checkpoint before submitting to a newer round.

`Phase18CoordinatorRuntime` is the sole schema-v3 outer-round authority. Worker lifecycle
events cannot create, accept, or finalize outer rounds. The API accepts versioned binary
initial state and outer updates, mirrors the coordinator's exact accepted/rejected set,
deadline, optimizer state, metric, and checkpoint into PostgreSQL, and returns a lossless
binary global state. The explicit policy is “all currently active workers or deadline”: a
round finalizes before its deadline only when all currently active members have contributed;
a declared failure reduces that active set. At the deadline it finalizes with at least
`min_k`, otherwise it pauses.

The launcher sends each persisted rank/device plan over the authenticated provider WSS.
The node agent starts `process_worker`; schema v2 stays on the Phase 17 two-peer path, while
schema v3 selects the DiLoCo coordinator path or constructs `IslandRuntime` for FSDP2/TP.

## Automated validation

```powershell
docker compose -f docker/docker-compose.test.yml up -d
poetry run alembic upgrade head
poetry run pytest tests/training -q --basetemp artifacts/pytest-phase18
poetry run black --check deepiri_zepgpu tests
poetry run ruff check deepiri_zepgpu tests
poetry run mypy deepiri_zepgpu
```

## Hardware-gated acceptance

These commands are not part of CPU CI. They must be run on a host with at least two
compatible CUDA GPUs and the optional training dependency group installed.

```powershell
$env:ZEPGPU_PHASE18_GPU_TEST='1'
poetry run pytest tests/training/test_phase18_gpu.py -q
poetry run python scripts/verify_phase18_fsdp2.py --mode single --hidden-size 4096 --layers 4
```

The gated pytest creates the Phase 18 config and placement, atomically reserves the two
local GPUs, invokes the launcher to create the rank manifest, runs the manifest through
`IslandRuntime` and FSDP2 for a training step, and verifies terminal reservation cleanup.
Raw FSDP2 mode intentionally refuses to run without that launcher-produced manifest.

For the OOM acceptance gate, increase `--hidden-size` and/or `--layers` until the documented
single-GPU command fails with CUDA OOM, then run exactly the same model dimensions under the
two-GPU FSDP2 command. Record both command outputs and each rank's
`peak_allocated_vram_bytes`. Do not treat a smaller toy smoke run as proof of this gate.

Controlled multi-host LAN tests require measured LAN paths plus explicit collective, P2P,
runtime-version, and strategy capability reports on every provider. Ordinary WAN links are
not eligible.
