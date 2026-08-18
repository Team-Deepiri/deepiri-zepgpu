# Provider join quick start (Phase 12)

Providers join GPU rooms with outbound HTTPS only. No inbound ports are required for dial-out rooms.

## One-line join

Hosts create an invite in the room UI. The invite copy includes a one-liner:

```bash
zepgpu-node join --invite <CODE> --coordinator https://gpu.example.com
```

Authenticate with `--username` / `--password` or `--token <human-jwt>`. Optional: `--node-name`, `--provider-mode dialout|wireguard|overlay` (must match the room).

## Transport-specific join

| Mode | After join |
|---|---|
| `dialout` | Outbound HTTPS/WSS only. No tunnel. `zepgpu-node serve` immediately. |
| `wireguard` | Linux/macOS: agent applies `wg-quick` when tools and `/dev/net/tun` exist. Windows: agent **exports** `~/.zepgpu/wg0.conf` and prints numbered import steps (WireGuard app → Add Tunnel → import file → activate → `zepgpu-node serve`). It does not silent-mock. Logout runs `wg-quick down` on Linux/macOS; deactivate the Windows app tunnel manually. |
| `overlay` | Agent publishes overlay node/ticket hints. Data plane is iroh/QUIC UDP with HTTP relay fallback. Logout closes overlay state with identity. |

`zepgpu-node status --probe` reports `tunnel_state` (`dialout` / `up` / `mock` / `exported_conf` / `overlay`) and `vpn_ip` when assigned.

## Persist identity

Successful join writes `~/.zepgpu/agent.json` (coordinator URL, room ID, peer ID, node name, provider token, expiry, heartbeat interval, agent version). The CLI does not print the provider token in normal output.

```bash
zepgpu-node status          # redacted local state
zepgpu-node status --probe  # optional coordinator probe with provider token
zepgpu-node serve --simulate --enable-task-worker
zepgpu-node logout          # clear local credentials
```

Non-HTTPS coordinator URLs are rejected except localhost/dev.

## Auth model

| Action | Credential |
|---|---|
| Redeem invite / join | Human JWT (login) |
| Heartbeat, poll, claim, logs, complete, fail, reconcile | Room-scoped **provider token** |
| Host revoke provider | Human JWT (room host/admin) |

Revoked, expired, rotated, or cross-room tokens are rejected. Hosts revoke providers from the room nodes panel (`POST /api/v1/rooms/{id}/nodes/{peer_id}/revoke`); active assignments are failed and GPU locks released.

## Related

- [Assignment leases and reconcile](assignment_leases.md)
- [Transport modes](transport_modes.md)
- [NAT dial-out smoke](deploy/dialout_nat_smoke.md)
- [NAT / path troubleshooting](nat_path_troubleshooting.md)
