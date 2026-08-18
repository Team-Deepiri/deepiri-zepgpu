# Phase 19 Production Pilot Runbook

## Goal

Reproduce a controlled multi-provider training pilot with measured hardware/network
evidence: overlay (or dial-out relay) data path, durable checkpoint recovery, and
dashboard visibility.

## Supported matrix (MVP)

| Item | Supported |
|---|---|
| Transport | `dialout` (always), `wireguard` (UDP hub + LanDirect over vpn_ip), `overlay` (iroh/quic UDP + HTTP relay) |
| GPUs | NVIDIA CUDA consumer GPUs (primary); MLX experimental via neutral update format |
| Coordinator | Compose stack from `docs/deploy/cloud_coordinator.md` |
| Training | Phase 17 WAN LoRA and/or Phase 18 DiLoCo smoke configs |

## Preflight

1. Coordinator healthy: `GET /api/v1/health` and `GET /metrics`.
2. Create room (`overlay` preferred for hard-NAT byte path pilot).
3. Two providers join with `zepgpu-node join` and `serve`.
4. Confirm heartbeats and path metrics.
5. Optional: Grafana dashboard `ZepGPU Phase 19 Training / Overlay`.

## Pilot steps

```bash
# Local gates (no GPU)
poetry run python scripts/verify_phase19_local.py --skip-coordinator
poetry run python scripts/verify_phase19_recovery.py
poetry run python scripts/verify_phase19_soak_smoke.py --seconds 10
poetry run python scripts/verify_phase19_chaos.py --seconds 10
poetry run python scripts/verify_phase18_wireguard_local.py --skip-coordinator
poetry run python scripts/smoke_wireguard_linux_direct.py --force-mock

# Multi-hour soak (manual)
poetry run python scripts/verify_phase19_chaos.py --seconds 7200 \
  --artifact artifacts/phase19_pilot/chaos_soak.json

# Against live coordinator
poetry run python scripts/verify_phase19_local.py --base-url https://YOUR_COORDINATOR
poetry run python scripts/collect_phase19_live_artifacts.py --base-url https://YOUR_COORDINATOR
poetry run python scripts/verify_phase19_chaos.py --seconds 30 --base-url https://YOUR_COORDINATOR
poetry run python scripts/fill_phase19_pilot_pack.py --base-url https://YOUR_COORDINATOR
```

Same-host two-process training soak (when multi-machine unavailable):

```bash
for mode in dialout wireguard overlay; do
  poetry run python scripts/run_two_process_wan_lora.py \
    --base-url http://127.0.0.1:8000 \
    --transport-mode "$mode" \
    --output-dir "/tmp/zepgpu-pilot-$mode"
done
poetry run python scripts/smoke_wireguard_hub.py --base-url http://127.0.0.1:8000
poetry run python scripts/smoke_wireguard_linux_direct.py --force-mock
# Linux runner with CAP_NET_ADMIN:
# poetry run python scripts/smoke_wireguard_linux_direct.py --require-real-wg
```

Coordinator restart / round-boundary resume: durable checkpoints use
`write_checkpoint_integrity` / `load_verified_checkpoint` (`deepiri_zepgpu/training/recovery.py`).
After restart, workers bootstrap from the last verified outer-round checkpoint.

MLX remains experimental/simulated; NVIDIA CUDA is the primary GPU path.

1. Create training run for the room (Phase 17 two-worker or Phase 18 job).
2. Open UI `/training-runs/<run_id>` dashboard.
3. Confirm workers, outer rounds, placement/islands (Phase 18), first failure empty on success.
4. Induce one documented failure (kill one worker or revoke), confirm deterministic terminal or resume.
5. Corrupt a checkpoint copy offline; confirm `load_verified_checkpoint` rejects it.
6. Record hardware, RTT/bandwidth, bytes/round, path_type, outcome in an artifact JSON.

## Artifact checklist

- [ ] Coordinator URL / commit SHA
- [ ] Room id + transport_mode
- [ ] Provider hostnames / GPU models / driver / CUDA
- [ ] Network notes (NAT type, direct vs relay)
- [ ] Metrics export or Grafana screenshots
- [ ] Dashboard export JSON from `/api/v1/training-runs/{id}/dashboard`
- [ ] Failure/recovery notes
- [ ] Final adapter/checkpoint refs

## Limitations

- Overlay production dial is HMAC UDP (`iroh`/`quic`); `tcp`/`memory` are CI helpers only. WireGuard rooms stay on UDP and do not use overlay TCP.
- Recorded three-mode pack: run the commands below for `dialout`, `wireguard`, and `overlay`, then store artifacts under `artifacts/phase19_pilot/<mode>/`.
- WAN memory pooling remains topology-aware (islands on fast links; compressed outer sync on WAN).
- Full multi-hour soak is manual (`--seconds 7200`); CI runs short soak-smoke.
