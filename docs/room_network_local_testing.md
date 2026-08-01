# Room Network Local Testing

This is the Phase 10 repeatable gate for the existing room-network path. It runs one
coordinator and simulates a second user joining as a GPU provider. No local GPU is required.

## Prerequisites

- Docker Desktop or Docker Engine with Compose v2
- Python 3.11 and the Poetry environment (`poetry install`)
- Ports 8000, 5432, and 6379 available for the development stack

## Start the coordinator

From the repository root:

```powershell
docker compose -f docker/docker-compose.yml up -d --build zepgpu zepgpu-db redis
docker compose -f docker/docker-compose.yml ps
```

Wait until `zepgpu` is healthy. Confirm the API directly:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

## Run the complete simulation gate

```powershell
poetry run python scripts/verify_room_network_local_simulation.py
```

Every run creates uniquely named users and a room, so it is safe to repeat. The gate verifies:

1. coordinator health;
2. owner and provider registration/login;
3. room creation with `transport_mode` (default `dialout`) and invite with join one-liner;
4. provider invite join and **room-scoped provider token** issuance;
5. provider-token heartbeat with capabilities/path, node listing, and GPU pool summary;
6. room-aware no-op assignment through node-task polling;
7. idempotent claim/lease (accept alias), start/complete retries;
8. host revoke stops subsequent heartbeats;
9. task polling and remote result visibility; and
10. continued `/api/v1/vpn/*` visibility for the room.

Phases 12–14 full matrix (cross-room denial, WireGuard coexistence, reconcile):

```powershell
poetry run python scripts/verify_phases_12_14_local.py
```

Production NAT dial-out (second machine / network path): see [deploy/dialout_nat_smoke.md](deploy/dialout_nat_smoke.md).

Use a different coordinator with:

```powershell
poetry run python scripts/verify_room_network_local_simulation.py --base-url http://localhost:9000
```

## Run one persistent simulated provider

The all-in-one gate is preferred for verification. For manual UI testing, first run the gate or
create a provider through the room invite flow. The provider's `GET /api/v1/rooms/{room_id}/config`
response contains its `peer_id` and node-agent `auth_token`.

```powershell
poetry run python -m deepiri_zepgpu.node_agent.agent `
  --api-base-url http://127.0.0.1:8000 `
  --room-id <room-id> `
  --peer-id <peer-id> `
  --auth-token <node-auth-token> `
  --simulate `
  --enable-task-worker
```

Prefer the Phase 12 CLI when testing dial-out identity persistence:

```powershell
poetry run zepgpu-node join --invite <code> --coordinator http://127.0.0.1:8000 `
  --username <provider> --password <password> --node-name local-box
poetry run zepgpu-node serve --simulate --enable-task-worker
```

The agent sends heartbeats and polls assigned no-op work until stopped with Ctrl+C. Human JWTs
authorize join and host APIs; the room-scoped provider token authorizes heartbeat and node-task
lifecycle APIs. Do not interchange them.

## Updates

The gate uses authenticated polling (`GET /api/v1/tasks/{task_id}`), which is the stable fallback.
The UI can also subscribe to `ws://127.0.0.1:8000/api/v1/ws/rooms?token=<jwt>`. Public deployments
must use `wss://` when the page is served over HTTPS.

## Common failures

| Symptom | Check |
| --- | --- |
| Health endpoint is unreachable | `docker compose ... ps` and `docker compose ... logs zepgpu` |
| Health says Redis is unhealthy | Redis container health and `REDIS_URL` |
| Registration returns an existing-user error | Use the gate, which generates unique users |
| No GPU is available | Provider heartbeat is online, contains `gpu_status`, and has not gone stale |
| Pending poll returns 401 | Use the peer `auth_token` from room config, not the user JWT |
| Heartbeat returns 403 | The JWT must belong to the user that owns that peer |
| Cross-room target is denied | Peer and GPU IDs must belong to the task's `room_id` |
| Task remains assigned | Run the provider with `--enable-task-worker` or run the complete gate |
| WebSocket fails in a browser | Verify token, CORS origin, proxy Upgrade headers, and WSS under HTTPS |

## Simulation and real-provider boundary

Ready for real providers: room membership/access checks, invites, peer credentials, heartbeats,
GPU inventory, room scheduling, node-task polling/lifecycle, result metadata, polling/WebSocket room
events, stale-peer AWOL state, and VPN-route compatibility.

Simulation-only: generated GPU metrics and `NodeTaskRunner.run_noop`. Arbitrary remote user code,
artifact transfer, process isolation, GPU execution, and production WireGuard relay provisioning are
not validated by this gate. A dial-out provider needs only HTTPS/WSS egress. WireGuard mode additionally
needs the coordinator relay's UDP 51820 reachable; it does not imply opening a provider inbound port.

## Stop the stack

```powershell
docker compose -f docker/docker-compose.yml down
```

Add `-v` only when intentionally deleting local Postgres and Redis data.
