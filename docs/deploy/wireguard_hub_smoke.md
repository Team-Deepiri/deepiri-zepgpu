# WireGuard Hub Smoke (Layer C equivalent for WG rooms)

## Goal

Prove a WireGuard hub room works with two providers: join, heartbeat, noop
node-task, and (when possible) training relay / direct-over-VPN. Hub must expose
UDP 51820 (or configured port). Providers typically dial out to the hub with
keepalive. Training on WG rooms uses `LanDirect` over `vpn_ip` **inside the
WireGuard UDP tunnel** — not overlay TCP.

## Prerequisites

- Coordinator reachable over HTTPS
- Host/VPS with WireGuard tools and UDP hub port forwarded/open
- Two provider machines (or one machine + mock tunnel for partial checks)

## Commands

```bash
# In-process / mock (no hub)
poetry run python scripts/verify_wireguard_room_local.py --skip-coordinator

# Against live coordinator (create/coexist + join/heartbeat/noop)
poetry run python scripts/smoke_wireguard_hub.py \
  --base-url https://gpu.example.com \
  --artifact-dir /tmp/zepgpu-wg-smoke

# Collect phase19 + WG live pack
poetry run python scripts/collect_phase19_live_artifacts.py \
  --base-url http://127.0.0.1:8000

# Linux direct-over-VPN LoRA (mock when CAP_NET_ADMIN missing)
poetry run python scripts/smoke_wireguard_linux_direct.py --force-mock \
  --artifact-dir /tmp/zepgpu-wg-linux
```

Provider join (WG room):

```bash
zepgpu-node join --invite <code> --coordinator https://gpu.example.com \
  --username <user> --password <pass> --provider-mode wireguard
zepgpu-node status --probe
zepgpu-node serve --simulate --enable-task-worker
```

If `wg` is not installed, Linux/macOS may use a **mock tunnel** (CI/dev) and
persist `vpn_ip` for control-plane testing. Windows always exports a `.conf`
instead of silent-mock. Real hub: `docker compose --profile wireguard up -d wireguard-hub`
(needs `/dev/net/tun`; on WSL enable the tun device). Hub config is regenerated
from live peers via `GET /api/v1/rooms/{id}/hub-config` after join/revoke.

## Artifact checklist

- [ ] Room id + `transport_mode=wireguard` + `requires_wireguard_udp=true`
- [ ] Two provider heartbeats (or one API-simulated provider for smoke)
- [ ] No-op node-task completion
- [ ] `AllowedIPs` uses room CIDR (not full-tunnel) unless explicitly configured
- [ ] Dial-out and overlay rooms still creatable on same coordinator
- [ ] Logout tears down WG or mock tunnel
- [ ] (hardware) `smoke_wireguard_linux_direct.py` artifact: direct bytes > 0, relay fallback, no leaked reservations

## CI note

Real `wg-quick` requires `CAP_NET_ADMIN`. Mark the Linux direct job
`optional` / `hardware` on runners without that capability; mock mode remains CI-green.
