# Transport modes (Phase 14 / 19)

Rooms persist `transport_mode` on the underlying VPN network. The three modes
are **independent** — overlay TCP is not a substitute for WireGuard UDP, and
must not constrain the WG data plane.

| Mode | Provider networking | Notes |
|---|---|---|
| `wireguard` | **UDP** WireGuard (typically UDP 51820 to the hub) | L3 tunnel; training prefers `LanDirect` to peer `vpn_ip` (app bytes inside the WG UDP tunnel) + HTTP relay fallback |
| `dialout` | Outbound HTTPS/WSS to coordinator only | Default for new cloud rooms (`VPN__DEFAULT_TRANSPORT_MODE`); no inbound UDP |
| `overlay` | Direct-first peer path with coordinator relay fallback | Phase 19 hard-NAT experiments; backends are pluggable (`memory` / `tcp` / `iroh`). **Not** the WireGuard transport. |

API/UI expose `transport_mode`, `requires_wireguard_udp`, and `transport_experimental` on room create/list/detail.

## Production parity matrix

| Gate | dialout | wireguard | overlay |
|---|---|---|---|
| Room create + join + heartbeat + claim/revoke | `scripts/verify_phases_12_14_local.py --transport-mode …` | same | same |
| Invite negatives + training relay | `scripts/verify_phases_10_16_local.py --transport-mode …` | same | same |
| Two-worker compressed LoRA | `scripts/run_two_process_wan_lora.py --transport-mode dialout` | `--transport-mode wireguard` | `--transport-mode overlay` (iroh/quic UDP; `--force-relay` still completes) |
| Room_auto noop e2e | `E2E_ROOMS_BACKEND=1` parametrized in `tests/e2e/test_room_task_dispatch.py` | same | same |
| Direct path smoke | NAT dial-out smoke (relay is the path) | `scripts/smoke_wireguard_hub.py` (two providers) + `scripts/smoke_wireguard_linux_direct.py` (`path_type=direct`, `--force-relay`, `--require-real-wg`) | Overlay UDP roundtrip unit + two-process LoRA without forcing TCP |
| Config API | Coordinator URL + token; **no** WG `.conf` | Peer `.conf` + hub regen `GET /rooms/{id}/hub-config` | Overlay hints; **no** WG `.conf` |

TCP overlay (`overlay_backend=tcp`) and in-memory overlay are **CI/LAN helpers only**. Production overlay rooms use `iroh`/`quic` (HMAC UDP dial). WireGuard is never funneled through overlay TCP.

## UDP vs TCP (do not lock the stack)

- **WireGuard is UDP.** Hub reachability, keepalive, and NAT traversal for WG
  rooms are UDP. `requires_wireguard_udp=true` for this mode. Do not treat
  overlay TCP as the WG path.
- **Training on WG rooms** uses `LanDirectChannel` to `vpn_ip` when the tunnel
  is up. Those sockets are ordinary TCP *inside* the WG tunnel; the wire
  packets remain WG UDP. Relay is HTTP to the coordinator when direct fails.
- **Overlay mode** is a separate room type. `tcp` is a **CI/LAN helper** so
  tests can exercise direct→metrics without native bindings. Production overlay
  dial is **iroh/quic HMAC UDP**. Overlay TCP is not a product lock-in and does
  not apply to WG rooms.

## Routing rules

- Dial-out rooms do **not** require provider inbound ports or UDP 51820.
- WireGuard config generation remains available for WireGuard rooms.
- Legacy pickle `vpn.task_router.TaskRouter` is quarantined to **WireGuard-only** generic tasks.
- Training code must not import or call the legacy router (`deepiri_zepgpu/vpn/legacy_router_guard.py`).

## Observability

Provider heartbeats report capability inventory, structured `health_state` / `health_reason`, and path type/class with coordinator RTT. Prometheus metrics: `zepgpu_provider_*` on `/metrics`. See [NAT / path troubleshooting](nat_path_troubleshooting.md).

## Related

- [Provider join](provider_join.md)
- [NAT dial-out smoke](deploy/dialout_nat_smoke.md)
- Related: [Overlay networking](overlay_networking.md), [Phase 19 pilot](deploy/phase19_pilot.md), [WireGuard hub smoke](deploy/wireguard_hub_smoke.md)
