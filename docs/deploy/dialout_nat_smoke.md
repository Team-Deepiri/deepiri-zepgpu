# Dial-Out NAT Smoke (Phases 12–14 Layer C)

This gate verifies **real outbound-only provider join** against a **deployed** coordinator.
It is required before treating Phases 12–14 as production-verified on a given environment.

Local single-machine control-plane coverage lives in:

- `scripts/verify_room_network_local_simulation.py` (Phase 10 + provider-token path)
- `scripts/verify_phases_12_14_local.py` (full 12–14 matrix on one host)

## Hardware / network assumptions

| Role | Requirements |
|---|---|
| Coordinator | Phase 11 Compose/Caddy (or equivalent) with public `https://` URL, Postgres, Redis, Celery |
| Provider machine | Second host **or** separate network path (different LAN/NAT, cellular tether, or cloud VM). Outbound TCP 443 only. **No inbound ports.** |
| GPU | Not required for this smoke (fake GPU payload). |
| WireGuard UDP 51820 | Not required for dial-out rooms. Still required only if you exercise WireGuard rooms against a relay that needs UDP. |

If you cannot use a second machine, document a NAT simulation (e.g. provider process on a cloud VM while the coordinator is on another VPC/region, or a laptop on guest Wi-Fi / phone hotspot). Same-host `127.0.0.1` is a **local dry run**, not a NAT proof.

## Prerequisites

1. Coordinator deployed per [cloud_coordinator.md](cloud_coordinator.md).
2. Migrations through `015_transport_mode_observability` applied.
3. `COORDINATOR_PUBLIC_URL` is the HTTPS URL providers will dial.
4. From the provider host: `curl -fsS https://<coordinator>/api/v1/health`.

## Run the smoke

From a checkout that can import `deepiri_zepgpu` (Poetry / `.venv`):

```bash
poetry run python scripts/smoke_dialout_nat.py \
  --base-url https://gpu.example.com \
  --artifact-dir /tmp/zepgpu-nat-smoke
```

Local HTTPS-simulation dry run (not a NAT proof):

```bash
poetry run python scripts/smoke_dialout_nat.py \
  --base-url http://127.0.0.1:8000 \
  --allow-http-localhost \
  --artifact-dir /tmp/zepgpu-nat-smoke-local
```

### Optional real CLI path (manual)

On the provider host, after the host creates a dial-out room and invite in the UI:

```bash
zepgpu-node join --invite <code> --coordinator https://gpu.example.com \
  --username <user> --password <pass> --node-name nat-box
zepgpu-node serve --simulate --enable-task-worker
zepgpu-node status --probe
```

Then dispatch a room no-op from the host UI/API and confirm claim/complete. Revoke the provider from the room nodes panel and confirm heartbeat stops.

## What the script asserts

1. Coordinator health over the public URL.
2. Register/login → create `transport_mode=dialout` room (`requires_wireguard_udp=false`).
3. Invite includes `join_command` one-liner; invalid invite rejected.
4. Provider joins with human JWT once; receives **room-scoped provider token** (never logged).
5. Heartbeat with provider token reports `health_state`, `capabilities`, and `path` (RTT class).
6. Best-effort Prometheus `/metrics` samples (`zepgpu_provider_*`).
7. Dispatch no-op → claim/lease → start → complete.
8. Host revoke → subsequent heartbeat fails.
9. WireGuard room can still be created on the same coordinator.

## Negative cases (covered or manual)

| Case | Covered by script? | Manual check |
|---|---|---|
| Invalid invite | Yes | — |
| Expired / exhausted / revoked invite | Partial | Create invite with `max_uses=1`, join twice; revoke invite then join |
| Revoked provider token | Yes | — |
| Cross-room claim | Use `verify_phases_12_14_local.py` | Attempt claim with another room's provider token |
| Lease expiry cleanup | Sweep unit tests | Lower lease TTL in a staging env and wait for beat sweep |

## Artifacts checklist

Capture and attach to the release/verification note:

- [ ] Script JSON artifact from `--artifact-dir` (redacted; no tokens)
- [ ] Coordinator logs covering join, heartbeat, claim, complete, revoke
- [ ] Provider `zepgpu-node status` output (tokens redacted)
- [ ] Prometheus scrape or screenshot showing `zepgpu_provider_coordinator_rtt_seconds` / health gauges
- [ ] UI: room transport mode dial-out; node health/path; revoke control
- [ ] Confirmation: provider host has **no** inbound firewall openings for this test

## Related docs

- [Provider join quick start](../provider_join.md)
- [Assignment leases and reconcile](../assignment_leases.md)
- [Transport modes](../transport_modes.md)
- [NAT / path troubleshooting](../nat_path_troubleshooting.md)
