# Phase 19 Overlay Networking

Overlay rooms (`transport_mode=overlay`) use a **direct-first** peer data path with
coordinator binary relay as fallback. Control plane remains HTTPS/WSS dial-out style
(invite, provider token, heartbeat, claim).

This mode is **not** WireGuard. WireGuard rooms stay on **UDP** (see
[transport modes](transport_modes.md) and [WG hub smoke](deploy/wireguard_hub_smoke.md)).
Overlay backends must stay pluggable so a TCP helper does not lock out UDP/QUIC.

## Backends

| Backend | Role |
|---|---|
| `memory` | In-process direct path for CI / same-process tests |
| `tcp` | **Helper** — authenticated length-prefixed TCP (HMAC) for LAN/CI when native overlay dial is unavailable |
| `iroh` / `quic` | **Production overlay dial** — HMAC-authenticated UDP (`UdpOverlayTransport`). Native `iroh` Python still lacks a stable send API; the wired path is first-party QUIC/UDP that satisfies `OverlayTransport`. |

Factory: `deepiri_zepgpu.vpn.overlay.build_overlay_transport`.

Training integration:

- Overlay rooms: `process_worker` wraps the selected overlay backend in
  `OverlayDirectAdapter` (`deepiri_zepgpu.training.channel_select`).
- WireGuard rooms: **do not** use overlay TCP. They select `LanDirectChannel`
  bound on `vpn_ip` so training rides the WG UDP tunnel.
- Dial-out: relay-first.

## iroh status

The public `iroh` Python package still has no stable connect/send API.
`iroh_dial_wired()` is **True** because overlay rooms dial via HMAC UDP
(`IrohOverlayTransport` wraps `UdpOverlayTransport`). `tcp`/`memory` remain
explicit CI helpers — overlay rooms must not default to TCP.

## Metrics

- `zepgpu_overlay_joins_total{result,backend}`
- `zepgpu_overlay_path_total{path_type,backend}`
- `zepgpu_overlay_bytes_total{path_type,backend}`
- `zepgpu_overlay_relay_bytes_total{backend}`

## Coexistence

WireGuard (UDP 51820) and dial-out rooms remain supported on the same coordinator.
Overlay does not require UDP 51820 and does not replace it.

## Migration

Existing dial-out rooms do not need to migrate. Create a new room with
`transport_mode=overlay` for hard-NAT peer-byte experiments, or `wireguard`
when a UDP hub is available.
