# Transport modes (Phase 14)

Rooms persist `transport_mode` on the underlying VPN network:

| Mode | Provider networking | Notes |
|---|---|---|
| `wireguard` | Classic WireGuard; may need UDP 51820 to relay | Default for existing rows after migration |
| `dialout` | Outbound HTTPS/WSS to coordinator only | Default for new cloud rooms (`VPN__DEFAULT_TRANSPORT_MODE`) |
| `overlay` | Experimental | Accepted but marked experimental until Phase 19 |

API/UI expose `transport_mode`, `requires_wireguard_udp`, and `transport_experimental` on room create/list/detail.

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
