# NAT / path troubleshooting (Phase 14)

Dial-out providers talk to the coordinator over outbound HTTPS (and optionally WSS). They do **not** need inbound UDP 51820. WireGuard rooms still use the classic VPN path and may require UDP reachability to the relay.

## Quick checks

1. **Room transport mode** — `GET /api/v1/rooms/{id}` includes `transport_mode`, `requires_wireguard_udp`, and `transport_experimental`.
2. **Provider heartbeat** — agent `serve` should show accepted heartbeats; node API includes `health_state`, `health_reason`, `capabilities`, and `path`.
3. **Path / RTT** — `path.path_type` (`direct` / `relay` / `unknown`), `path.path_class` (`same_host` / `lan` / `wan` / `relay`), `coordinator_rtt_ms`, and `measurement_kind` (`measured` vs `estimated`).
4. **Prometheus** — scrape `/metrics` for:
   - `zepgpu_provider_coordinator_rtt_seconds`
   - `zepgpu_provider_path_info`
   - `zepgpu_provider_health_state`
   - `zepgpu_provider_heartbeats_total`

## Common failures

| Symptom | Likely cause | What to try |
|---|---|---|
| Heartbeat 401/403 | Expired/rotated/revoked provider token, or wrong room | Re-run `zepgpu-node join`; confirm host has not revoked the provider |
| Heartbeat never arrives | Outbound HTTPS blocked, wrong coordinator URL, TLS interception | From provider: `curl -I https://<coordinator>/health`; confirm agent.json URL |
| `health_state=stale` | Missed heartbeats beyond timeout | Check agent process; lower network loss; confirm interval vs `VPN_HEARTBEAT_TIMEOUT_SECONDS` |
| `health_state=incompatible` | Agent version below coordinator minimum | Upgrade agent; or clear `VPN_MIN_COMPATIBLE_AGENT_VERSION` |
| `health_state=claim_timeout` | Assignment claimed/started too late | Inspect Phase 13 lease/timeout settings; check provider load |
| High RTT / `path_class=wan` | Expected on consumer internet | Prefer dial-out; do not assume LAN-class FSDP across WAN |
| WireGuard config useless on dial-out room | Room is `transport_mode=dialout` | Use join/serve only; no inbound UDP needed |
| Legacy pickle execute fails on dial-out | Pickle TaskRouter is WireGuard-only | Use node-task dial-out assignment; training must not import `vpn.task_router` |

## Coexistence

A coordinator can host WireGuard rooms and dial-out rooms at the same time. Existing networks default to `wireguard` after migration; new cloud rooms default to `dialout` (`VPN__DEFAULT_TRANSPORT_MODE`). Soft agent-version gate: `VPN__MIN_COMPATIBLE_AGENT_VERSION`.

Overlay mode is a first-class room transport (iroh/QUIC UDP dial with HTTP relay fallback). TCP overlay is a CI/LAN helper only.
