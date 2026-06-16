# ZepGPU - Serverless GPU Framework

_Made by Deepiri_

<div align="center">

![ZepGPU](https://img.shields.io/badge/ZepGPU-v0.1.0-blue)
![Python](https://img.shields.io/badge/Python-3.11+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-orange)
![License](https://img.shields.io/badge/License-MIT-yellow)

**Serverless GPU framework for kernel-as-a-service computing**

[Features](#features) • [Quick Start](#quick-start) • [Documentation](#documentation) • [API Reference](#api-reference) • [Development](#development)

</div>

---

## Features

- **GPU Task Scheduling** - Submit Python functions for GPU execution with priority-based scheduling
- **Multi-Stage Pipelines** - Chain tasks with dependencies into executable workflows
- **Real-time Monitoring** - WebSocket streams for task status and GPU metrics
- **Container Isolation** - Docker-based task execution with resource limits
- **PostgreSQL Persistence** - Full task history, user management, and audit logging
- **Redis Queue** - Distributed task queue with Celery workers
- **S3/MinIO Storage** - Tiered result storage for large outputs
- **Web UI** - Modern dashboard for task management
- **Kubernetes Ready** - Production deployment manifests included

---

## Quick Start

The fastest way to run ZepGPU locally is Docker Compose. It starts the API, UI, PostgreSQL, Redis, Celery workers, and observability stack in one command.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2 (`docker compose`)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) (optional, only needed for GPU task execution on the host)

Poetry and a local Python install are only required if you want to run the backend outside Docker (see [Development](#development)).

### Start the stack

```bash
git clone https://github.com/Team-Deepiri/deepiri-zepgpu.git
cd deepiri-zepgpu

docker compose -f docker/docker-compose.yml up -d --build
```

First startup builds the backend and UI images and may take several minutes.

Check that services are running:

```bash
docker compose -f docker/docker-compose.yml ps
```

Wait until the `zepgpu` container reports healthy, then verify the API:

```bash
curl http://localhost:8000/api/v1/health
```

### Services and ports

| Service | Container | URL / port |
|---------|-----------|------------|
| API + Swagger | `zepgpu` | http://localhost:8000 — OpenAPI at `/docs` |
| Web UI | `zepgpu-ui` | http://localhost:3000 |
| PostgreSQL | `zepgpu-db` | `localhost:5432` |
| Redis | `redis` | `localhost:6379` |
| Prometheus | `prometheus` | http://localhost:9090 |
| Grafana | `grafana` | http://localhost:3001 (login `admin` / `admin`) |

Celery processes started by compose:

- `celery-beat` — scheduled jobs
- `celery-worker-schedules` — `schedules` and default `celery` task queue
- `celery-worker-gang` — gang scheduling queue
- `celery-worker-preemption` — preemption queue

The API container runs database initialization on startup (`init_db`). No separate migration step is required for the default local stack.

### Verify auth and task execution

Register a user, log in, and submit a lightweight no-op task. Setting `gpu_memory_mb: 0` skips GPU allocation, so this works on a machine without NVIDIA drivers.

```bash
# Register
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","email":"demo@example.com","password":"password123"}'

# Login (JSON body) and save the token
export TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"password123"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Create a no-op task. random.seed takes no required args and returns None,
# which the worker records as a completed task with no stored result.
curl -s -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Smoke test","func_name":"random.seed","gpu_memory_mb":0}'

# Poll task status (replace TASK_ID with the id from the create response)
curl -s http://localhost:8000/api/v1/tasks/TASK_ID \
  -H "Authorization: Bearer $TOKEN"
```

Within a few seconds the task status moves from `pending` to `completed`. The result
endpoint returns `null` for this no-op because the function returns no value:

```bash
curl -s http://localhost:8000/api/v1/tasks/TASK_ID/result \
  -H "Authorization: Bearer $TOKEN"
# {"task_id":"...","status":"completed","result":null,"presigned_url":null}
```

> **Note:** In the default local stack, tasks whose function returns a value require the
> result store (Redis-backed) to be reachable from the worker. See the
> [deployment troubleshooting guide](docs/deployment_troubleshooting.md) if a task ends
> in `failed` with a `set_task_result` error.

For the complete, verified HTTP API walkthrough (auth, tasks, pipelines, callbacks, and
WebSockets), see the **[API reference](docs/api_reference.md#http--rest-api)**.

### Web UI

Open http://localhost:3000 to create and manage tasks, view pipelines, and monitor GPU utilization.

### Stop the stack

```bash
docker compose -f docker/docker-compose.yml down
```

Add `-v` to remove named volumes (PostgreSQL and Redis data).

### Python API (optional)

If you run the backend with Poetry instead of Docker, install dependencies first (`poetry install`), ensure PostgreSQL and Redis are reachable, then start the server:

```bash
poetry run uvicorn deepiri_zepgpu.api.server.main:app --reload
```

```python
from deepiri_zepgpu.api.submit import submit_task

def matrix_multiply(a, b):
    import cupy as cp
    return cp.dot(a, b)

task_id = submit_task(
    func=matrix_multiply,
    args=([1, 2, 3], [4, 5, 6]),
    gpu_memory_mb=2048,
    priority=3,
)

print(f"Task submitted: {task_id}")
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (zepgpu-ui)                    │
│                   React + TypeScript + Vite                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API Server (zepgpu)                          │
│              FastAPI + Uvicorn + WebSockets                      │
├─────────────────────────────────────────────────────────────────┤
│  Routes: Tasks │ Pipelines │ Users │ GPU │ Auth │ Health       │
│  Middleware: CORS │ Metrics │ Auth │ WebSocket                 │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐
│   PostgreSQL    │  │    Redis     │  │   S3/MinIO       │
│   (zepgpu-db)   │  │  (Task Queue) │  │  (Result Store)   │
└─────────────────┘  └──────────────┘  └──────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Celery Workers                                │
│              GPU Task Execution                                  │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    GPU Devices                                   │
│                 NVIDIA CUDA + NVML                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Documentation

- **[API reference](docs/api_reference.md)** — the [HTTP/REST + WebSocket API](docs/api_reference.md#http--rest-api) (auth, tasks, pipelines, callbacks) and the [Python SDK](docs/api_reference.md#python-sdk).
- **[Deployment & troubleshooting guide](docs/deployment_troubleshooting.md)** — Docker, Postgres, Redis, Celery, MinIO/S3, and GPU/NVIDIA issues.

### Project Structure

```
deepiri-zepgpu/
├── deepiri_zepgpu/       # Python backend
│   ├── api/server/       # FastAPI routes
│   ├── core/             # Task scheduler, GPU manager
│   ├── database/         # SQLAlchemy models, repositories
│   ├── queue/            # Redis + Celery
│   └── storage/          # S3 client
├── zepgpu-ui/            # React frontend
├── docker/               # Docker configs
├── k8s/                  # Kubernetes manifests
└── examples/             # Usage examples
```

### Environment Variables

Docker Compose sets connection URLs for PostgreSQL, Redis, and Celery automatically. For local non-Docker development, configure at minimum:

```bash
DATABASE_URL=postgresql+asyncpg://zepgpu:zepgpu@localhost:5432/zepgpu
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

Optional S3/MinIO settings (`S3_*` / endpoint URL) enable large result storage; the stack runs without MinIO and degrades gracefully when object storage is unavailable.

Auth defaults to `changeme-in-production` for the JWT secret in local development — override via application settings before deploying publicly.

---

## API Reference

This section is a quick reference. For the full, verified walkthrough with request/response
examples, see the **[API reference](docs/api_reference.md#http--rest-api)**.

All routes are served under `/api/v1`. Authentication endpoints are mounted at both
`/api/v1/auth/*` and `/api/v1/users/*` (same router).

### Authentication

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"user","email":"user@example.com","password":"password123"}'

# Login — JSON body (NOT form-encoded). Returns an access_token.
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"user","password":"password123"}'
```

### Tasks

```bash
# Submit task. Provide a dotted func_name; gpu_memory_mb=0 runs without a GPU.
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"My Task","func_name":"random.seed","gpu_memory_mb":0}'

# List tasks
curl http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN"

# Get task status
curl http://localhost:8000/api/v1/tasks/{task_id} \
  -H "Authorization: Bearer $TOKEN"

# Get task result
curl http://localhost:8000/api/v1/tasks/{task_id}/result \
  -H "Authorization: Bearer $TOKEN"

# Cancel task (only while pending/queued/running)
curl -X DELETE http://localhost:8000/api/v1/tasks/{task_id} \
  -H "Authorization: Bearer $TOKEN"
```

### Callbacks

Include a `callback_url` when creating a task. On completion or failure, the worker POSTs a
JSON payload to that URL:

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"With callback","func_name":"random.seed","gpu_memory_mb":0,
       "callback_url":"https://example.com/hook"}'

# Webhook body delivered to callback_url:
# {"task_id":"<uuid>","status":"completed","user_id":"<uuid>"}
```

### Pipelines

```bash
# Create a pipeline with ordered stages
curl -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Demo Pipeline",
    "stages": [
      {"name": "preprocess", "func_name": "random.seed"},
      {"name": "train", "func_name": "random.seed", "depends_on": ["preprocess"]}
    ]
  }'

# Run pipeline
curl -X POST http://localhost:8000/api/v1/pipelines/{pipeline_id}/run \
  -H "Authorization: Bearer $TOKEN"
```

### WebSocket

Three authenticated streams are available; pass the JWT as a `token` query parameter:
`/api/v1/ws/tasks`, `/api/v1/ws/gpus`, `/api/v1/ws/metrics`.

```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/ws/tasks?token=JWT_TOKEN');

ws.onopen = () => ws.send(JSON.stringify({ type: 'ping' }));

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // { "type": "connected", ... } on connect, { "type": "pong" } in reply to ping
  console.log(data);
};

// Subscribe to a specific task's updates
ws.send(JSON.stringify({ type: 'subscribe_task', task_id: 'task-uuid' }));
```

---

## Development

### Setup

```bash
# Install dependencies
poetry install

# Run tests
poetry run pytest tests/ -v

# Run linters
poetry run ruff check deepiri_zepgpu
poetry run mypy deepiri_zepgpu

# Start development server
poetry run uvicorn deepiri_zepgpu.api.server.main:app --reload
```

### Database Migrations

```bash
# Create migration
poetry run alembic revision --autogenerate -m "Add new table"

# Apply migrations
poetry run alembic upgrade head

# Rollback
poetry run alembic downgrade -1
```

### Docker

```bash
# Build and run the full local stack (from repo root)
docker compose -f docker/docker-compose.yml up -d --build

# Rebuild a single service after code changes
docker compose -f docker/docker-compose.yml up -d --build zepgpu

# View logs
docker compose -f docker/docker-compose.yml logs -f zepgpu celery-worker-schedules

# Stop and remove containers
docker compose -f docker/docker-compose.yml down
```

The backend image is CUDA-based. GPU task execution inside workers requires the NVIDIA Container Toolkit on the host and appropriate device passthrough configuration.

---

## Examples

See `examples/` directory for:

- `pytorch_training.py` - PyTorch model training task
- `cupy_kernel.py` - CuPy GPU kernel execution
- `neural_ode.py` - Neural ODE simulation
- `monte_carlo.py` - Monte Carlo option pricing
- `multi_task_pipeline.py` - Complex pipeline example

---

## Monitoring

### Prometheus Metrics

Access at `http://localhost:8000/metrics`:

- `zepgpu_http_requests_total` - HTTP request count
- `zepgpu_http_request_duration_seconds` - Request latency
- `zepgpu_active_tasks` - Running task count
- `zepgpu_gpu_utilization` - GPU utilization by device
- `zepgpu_task_queue_length` - Pending tasks in queue

### Grafana Dashboards

Grafana runs at http://localhost:3001 when using Docker Compose (default login `admin` / `admin`). Dashboards are provisioned from `docker/grafana/provisioning/`:

- Task Overview
- GPU Utilization
- System Health
- Queue Statistics

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Support

- 📖 [Documentation](https://zepgpu.readthedocs.io)
- 💬 [Discord Community](https://discord.gg/zepgpu)
- 🐛 [Issue Tracker](https://github.com/deepiri/zepgpu/issues)
- 📧 [Email Support](mailto:support@deepiri.ai)
