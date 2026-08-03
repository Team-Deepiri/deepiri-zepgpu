# Deployment & Troubleshooting Guide

Common startup and runtime issues for the local ZepGPU stack and how to diagnose them.
This guide targets the Docker Compose stack defined in `docker/docker-compose.yml`.

## Contents

- [Quick health checks](#quick-health-checks)
- [Docker & Compose](#docker--compose)
- [PostgreSQL](#postgresql)
- [Redis](#redis)
- [Celery workers](#celery-workers)
- [MinIO / S3 result storage](#minio--s3-result-storage)
- [GPU / NVIDIA runtime](#gpu--nvidia-runtime)
- [Known issues](#known-issues)

---

## Quick health checks

Run these first to localize a problem.

```bash
# Container status (all should be "Up"; zepgpu should become healthy)
docker compose -f docker/docker-compose.yml ps

# API health — reports database and redis connectivity
curl -s http://localhost:8000/api/v1/health
# {"status":"healthy","timestamp":"...","version":"0.1.0","database":"healthy","redis":"healthy"}

# Tail logs for a service
docker compose -f docker/docker-compose.yml logs -f zepgpu
docker compose -f docker/docker-compose.yml logs --tail=50 celery-worker-schedules
```

The stack exposes:

| Service | URL / port |
|---------|------------|
| API + Swagger | `http://localhost:8000` (`/docs`) |
| Web UI | `http://localhost:3000` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:3001` |

---

## Docker & Compose

### `docker` not found in WSL

```
The command 'docker' could not be found in this WSL 2 distro.
```

Enable **WSL integration** for your distro in Docker Desktop → Settings → Resources → WSL
Integration, then restart the shell.

### Build error: `image "docker.io/library/zepgpu:latest": already exists`

Several services (the API, Celery beat, and the three Celery workers) share the same image
tag `zepgpu:latest`. With BuildKit/bake, building them in parallel can race on export and
fail with `image ... already exists`.

Workaround — build the shared image once, then start without rebuilding:

```bash
# Build the backend image a single time
docker build -t zepgpu:latest -f docker/Dockerfile .

# Start the stack using the prebuilt image
docker compose -f docker/docker-compose.yml up -d
```

Alternatively, disable parallel bake for the build:

```bash
COMPOSE_BAKE=false docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
```

### Ports already in use

If `8000`, `3000`, `5432`, `6379`, `9090`, or `3001` are taken, stop the conflicting
process or remap the host port in `docker/docker-compose.yml`.

### Rebuild after code changes

```bash
docker build -t zepgpu:latest -f docker/Dockerfile .
docker compose -f docker/docker-compose.yml up -d
```

Because the backend, beat, and workers all use `zepgpu:latest`, rebuilding that one image
updates all of them on the next `up`.

---

## PostgreSQL

- Connection (inside the Compose network): `postgresql://zepgpu:zepgpu@zepgpu-db:5432/zepgpu`
- The API runs `init_db()` on startup, which creates tables via SQLAlchemy
  `Base.metadata.create_all`. **No separate migration step is required** for the default
  local stack.

### API can't reach the database

```bash
docker compose -f docker/docker-compose.yml ps zepgpu-db
docker compose -f docker/docker-compose.yml logs zepgpu-db
```

If the API started before the database was ready, restart it:

```bash
docker compose -f docker/docker-compose.yml restart zepgpu
```

### Reset all data

```bash
docker compose -f docker/docker-compose.yml down -v   # removes postgres + redis volumes
docker compose -f docker/docker-compose.yml up -d
```

---

## Redis

Redis backs both the application cache/result store and the Celery broker/result backend:

| Purpose | URL |
|---------|-----|
| App cache / result store | `redis://redis:6379/0` |
| Celery broker | `redis://redis:6379/1` |
| Celery result backend | `redis://redis:6379/2` |
| Celery beat schedule | `redis://redis:6379/3` |

If `GET /api/v1/health` reports `"redis":"unhealthy"`:

```bash
docker compose -f docker/docker-compose.yml ps redis
docker compose -f docker/docker-compose.yml exec redis redis-cli ping   # expect: PONG
```

The application's Redis client retries on startup (5 attempts with a delay) to tolerate
Redis coming up slightly after the API.

---

## Celery workers

Compose starts one beat scheduler and three workers, each listening on specific queues:

| Container | Queues |
|-----------|--------|
| `celery-beat` | (scheduler only) |
| `celery-worker-schedules` | `schedules`, `celery` |
| `celery-worker-gang` | `gang` |
| `celery-worker-preemption` | `preemption` |

### Tasks stay `pending` forever

Newly created tasks are enqueued onto the default **`celery`** queue, which is served by
`celery-worker-schedules`. If that worker is down or not listening on `celery`, tasks never
start.

```bash
# Is the worker up?
docker compose -f docker/docker-compose.yml ps celery-worker-schedules

# Does it list the celery + schedules queues on boot?
docker compose -f docker/docker-compose.yml logs celery-worker-schedules | grep -i queues

# Restart it
docker compose -f docker/docker-compose.yml restart celery-worker-schedules
```

### Inspect a failed task

A task's `error` field surfaces the worker exception:

```bash
curl -s http://localhost:8000/api/v1/tasks/$TASK_ID \
  -H "Authorization: Bearer $TOKEN"
```

For the full traceback, read the worker logs:

```bash
docker compose -f docker/docker-compose.yml logs --tail=80 celery-worker-schedules
```

### asyncpg / event-loop errors in workers

Celery tasks run async database work via `asyncio.run(...)` inside the worker. If you see
event-loop or `asyncpg` errors after editing task code, restart the workers so they reload:

```bash
docker compose -f docker/docker-compose.yml restart \
  celery-worker-schedules celery-worker-gang celery-worker-preemption
```

---

## MinIO / S3 result storage

Object storage is **optional** and is not part of the default Compose stack. Large task
results are uploaded to S3/MinIO when it is configured and reachable; otherwise the result
store degrades:

- Small results are cached in Redis.
- Large results fall back to inline encoding when no S3 backend is available.

Default S3 settings (used only if you run MinIO/S3 yourself):

```
endpoint_url = http://localhost:9000
access_key   = minioadmin
secret_key   = minioadmin
bucket_name  = deepiri-results
```

If you point the stack at a MinIO instance and uploads fail, verify the endpoint, the
credentials, and that the bucket exists (the client attempts to create it on first use).

---

## GPU / NVIDIA runtime

The backend image is built on `nvidia/cuda`. GPU execution inside the Celery workers
requires the **NVIDIA Container Toolkit** on the host and device passthrough configured for
the worker containers.

### Run without a GPU

For local development without NVIDIA drivers, submit tasks with `gpu_memory_mb: 0`. This
skips GPU allocation and runs the task on CPU:

```bash
curl -s -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"cpu task","func_name":"math.sqrt","args":[0],"gpu_memory_mb":0}'
```

### Task fails with "No GPU available"

If a task requests `gpu_memory_mb > 0` with `allow_fallback_cpu: false` and no GPU is
available/registered, it is marked failed with `No GPU available`. Either:

- set `gpu_memory_mb: 0`, or
- set `allow_fallback_cpu: true` (the default), or
- ensure GPUs are registered and the NVIDIA runtime is available to the workers.

### Verify NVIDIA runtime on the host

```bash
nvidia-smi                              # host driver present
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

---

## Known issues

These are confirmed server-side behaviors in the current codebase (not configuration
problems on your machine). They are documented here so they can be recognized quickly.

### Tasks fail with `'NoneType' object has no attribute 'set_task_result'`

A task whose function **returns a value** can fail with:

```
'NoneType' object has no attribute 'set_task_result'
```

This happens in the worker when the result store is used before its Redis client is
initialized. Operations that return a value (including `math.sqrt`) require the result
store to be available.

Workarounds today:

- Use no-op/`None`-returning functions for smoke tests and demos.
- Treat value-returning tasks as dependent on a properly initialized, Redis-backed result
  store in the worker process.

### Unauthenticated requests fail closed

Protected REST routes reject missing, malformed, invalid, or expired bearer tokens with
HTTP `401`. PyJWT failures are handled through `jwt.PyJWTError`; they do not fall through
to an internal server error.

### Pipeline stages defined only with `func_name` are skipped

The pipeline executor dispatches a stage only when it carries a pre-created task reference
(`task_id`). Stages defined solely with a `func_name` are marked skipped, so a pipeline can
report `completed` with `0` executed stages. See
[docs/api_reference.md](api_reference.md#pipelines) for current pipeline behavior.
