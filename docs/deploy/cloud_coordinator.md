# Cloud Coordinator Deployment

The coordinator is the always-on CPU control plane for API/UI access, rooms, invites, provider
identity, scheduling, task lifecycle, Postgres, Redis, Celery, WebSockets, and heartbeat expiry. It
does not need a GPU, CUDA runtime, or an NVIDIA container runtime.

## Capacity assumptions

For a small self-hosted installation (tens of users/providers), start with 2 vCPU, 4 GB RAM, 40 GB
SSD, and a daily database backup. Use 4 vCPU and 8 GB RAM when API, Postgres, Redis, worker, beat,
UI, and proxy share one VM. Storage growth is driven by task metadata, audit/event history, and
Postgres backups; remote result objects should live in object storage.

Production managed deployments should use highly available Postgres and Redis, at least two API
replicas behind a load balancer, independently scaled Celery workers, and one Celery beat instance.

## Self-hosted quick start

1. Point a DNS A/AAAA record such as `gpu.example.com` at the VM.
2. Allow TCP 80/443. Allow UDP 51820 only if this host is the WireGuard relay.
3. Copy and edit the production environment file.

```bash
cp docker/.env.prod.example docker/.env.prod
openssl rand -hex 32
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml up -d --build
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml ps
```

The default command starts the API, Postgres, Redis, Celery worker, and Celery beat. It binds the API
to loopback on port 8000. To add the optional UI and Caddy HTTPS reverse proxy:

```bash
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml --profile ui up -d --build
```

Caddy obtains and renews public certificates when `COORDINATOR_DOMAIN` resolves to the VM and ports
80/443 are reachable. For localhost it uses local TLS behavior. If another load balancer terminates
TLS, omit the `ui` profile and proxy to `127.0.0.1:8000` with WebSocket Upgrade support.

## Managed services

Set all database and Redis values in `docker/.env.prod` to the provider-issued URLs:

- `DATABASE_URL`: async SQLAlchemy URL using `postgresql+asyncpg://`
- `DATABASE_SYNC_URL`: synchronous `postgresql://` URL for migrations/workers
- `REDIS_URL`: application/cache database
- `CELERY_BROKER_URL`: Celery broker database
- `CELERY_RESULT_BACKEND`: Celery result database
- `CELERY_BEAT_SCHEDULE_DB`: beat/schedule database

Start only coordinator processes when Postgres and Redis are managed:

```bash
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml up -d --build --no-deps api celery-worker celery-beat
```

Use TLS-enabled `postgresql` and `rediss` endpoints according to the managed provider's certificate
requirements. Managed Redis must permit persistence/configuration needed by Celery and must not evict
broker keys under normal load.

## Public URL, TLS, WSS, and CORS

Set `COORDINATOR_PUBLIC_URL=https://gpu.example.com`. The browser UI origin must appear in the
comma-separated `CORS_ORIGINS`; do not use `*` with credentialed browser requests. HTTPS is required
for credentials on the public Internet. Browsers serving the UI over HTTPS must connect to room/task
WebSockets with `wss://`, never `ws://`.

The supplied Caddy example forwards `/api/*` (including WebSocket upgrades) to the API and all other
paths to the optional UI. Keep proxy read timeouts long enough for WebSocket connections.

Dial-out rooms require provider egress to coordinator TCP 443 and no provider inbound ports.
WireGuard rooms additionally require the selected relay endpoint to receive UDP 51820. Opening UDP
51820 on the coordinator is unnecessary when WireGuard rooms are disabled or relayed elsewhere.

## Secrets and rotation

Generate `ZEPGPU_SECRET_KEY` with `openssl rand -hex 32` or a cloud secret manager. Generate independent
strong Postgres, Redis, object-storage, and provider credentials. Never commit `docker/.env.prod`.

Rotating the JWT signing secret invalidates existing user sessions; deploy the new secret and require
users to log in again. Rotate database/Redis credentials by creating a new credential, updating all API,
worker, and beat instances together, verifying health, then revoking the old credential. Peer tokens are
encrypted at rest using application cryptographic settings; revoke/rejoin a peer if its token is exposed.

## Postgres backup and restore

For bundled Postgres, create a logical backup outside the container volume:

```bash
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml exec -T postgres \
  pg_dump -U zepgpu -Fc zepgpu > zepgpu-$(date +%F).dump
```

Test restores regularly. Stop API/worker/beat writers, create an empty database, then restore:

```bash
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml stop api celery-worker celery-beat
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml exec -T postgres \
  pg_restore -U zepgpu --clean --if-exists -d zepgpu < zepgpu-YYYY-MM-DD.dump
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml start api celery-worker celery-beat
```

Managed Postgres should use automated snapshots plus point-in-time recovery. Retain backups in another
failure domain and rehearse restore procedures before relying on them.

## Redis persistence

The bundled Redis uses AOF with `appendfsync everysec`. Redis is not the source of truth for rooms,
users, or task records; Postgres is. Redis does hold broker messages, result/cache data, distributed GPU
locks, and beat state, so data loss can cause delayed/duplicated work and requires reconciliation. Use
managed Redis persistence and no-eviction policies for production. Never treat Redis snapshots as a
replacement for Postgres backups.

## Verification

Run the public smoke test from outside the coordinator network:

```bash
poetry run python scripts/smoke_cloud_coordinator.py --base-url https://gpu.example.com
```

It checks health, registration/login, room creation, invite creation, and room listing. It creates a
unique smoke user each run. Then run the deeper provider simulation against the same URL if appropriate:

```bash
poetry run python scripts/verify_room_network_local_simulation.py --base-url https://gpu.example.com
poetry run python scripts/verify_phases_12_14_local.py --base-url https://gpu.example.com
```

For production NAT dial-out acceptance (second machine / network path), see
[dialout_nat_smoke.md](dialout_nat_smoke.md):

```bash
poetry run python scripts/smoke_dialout_nat.py --base-url https://gpu.example.com --artifact-dir /tmp/zepgpu-nat-smoke
```

## Troubleshooting

| Area | Symptoms and checks |
| --- | --- |
| DNS | Confirm public A/AAAA records resolve to the load balancer/VM from another network |
| TLS | Check Caddy logs, ports 80/443, certificate rate limits, system time, and domain ownership |
| WSS | Confirm the proxy preserves Upgrade/Connection headers and the UI uses `wss://` with a valid JWT |
| CORS | Add the exact UI scheme/host/port to `CORS_ORIGINS`; browser errors often hide a healthy API |
| Redis | Run `redis-cli ping`; verify all API/worker/beat URLs and TLS credentials use intended DB numbers |
| Postgres | Run `pg_isready`; verify async vs sync URL drivers, credentials, disk space, and migrations |
| Celery | Inspect worker/beat logs, `celery ... inspect ping`, queue names, broker connectivity, and clock skew |
| Providers | Check coordinator HTTPS egress, peer token, heartbeat timeout, room membership, and GPU payload |

Useful commands:

```bash
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml ps
docker compose --env-file docker/.env.prod -f docker/docker-compose.prod.yml logs -f api celery-worker celery-beat
curl -fsS https://gpu.example.com/api/v1/health
```

## Current limitations

The production artifact packages the control plane, but operators remain responsible for VM/load-balancer
hardening, external monitoring/alerting, backup retention, upgrades, high availability, abuse controls,
WireGuard relay setup, and object storage. The node-agent currently executes the safe no-op simulation;
general remote GPU workloads require the later execution/isolation phases.
