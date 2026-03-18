# ZepGPU - Serverless GPU Framework

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
- **React Web UI** - Modern dashboard for task management
- **Kubernetes Ready** - Production deployment manifests included

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- NVIDIA Docker (for GPU support)
- PostgreSQL 15
- Redis 7

### Installation

```bash
# Clone the repository
git clone https://github.com/deepiri/zepgpu.git
cd zepgpu

# Install dependencies
poetry install

# Start with Docker Compose
cd docker
docker-compose up -d

# Or run directly
poetry run uvicorn deepiri_zepgpu.api.server.main:app --reload
```

### Python API

```python
from deepiri_zepgpu.api.submit import submit_task
import cloudpickle

# Define your GPU function
def matrix_multiply(a, b):
    import cupy as cp
    return cp.dot(a, b)

# Submit for execution
task = submit_task(
    func=matrix_multiply,
    args=([1, 2, 3], [4, 5, 6]),
    gpu_memory_mb=2048,
    priority=3
)

print(f"Task submitted: {task.task_id}")
```

### Web UI

Access the dashboard at `http://localhost:3000`:

- Create and manage tasks
- Monitor GPU utilization
- View pipeline execution
- Track task history

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

### Project Structure

```
zepgpu/
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

```bash
# Required
DATABASE_URL=postgresql+asyncpg://zepgpu:zepgpu@localhost:5432/zepgpu
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=your-secret-key

# Optional
API_PORT=8000
GPU_MEMORY_RESERVE_MB=1024
```

---

## API Reference

### Authentication

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"user","email":"user@example.com","password":"password123"}'

# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -d "username=user&password=password123"
```

### Tasks

```bash
# Submit task
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"My GPU Task","func_name":"numpy.matmul","gpu_memory_mb":1024}'

# List tasks
curl http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN"

# Get task status
curl http://localhost:8000/api/v1/tasks/{task_id} \
  -H "Authorization: Bearer $TOKEN"

# Cancel task
curl -X DELETE http://localhost:8000/api/v1/tasks/{task_id} \
  -H "Authorization: Bearer $TOKEN"
```

### Pipelines

```bash
# Create pipeline
curl -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ML Training Pipeline",
    "stages": [
      {"name": "preprocess", "task_id": "uuid-1"},
      {"name": "train", "task_id": "uuid-2", "depends_on": ["preprocess"]}
    ]
  }'

# Run pipeline
curl -X POST http://localhost:8000/api/v1/pipelines/{pipeline_id}/run \
  -H "Authorization: Bearer $TOKEN"
```

### WebSocket

```javascript
// Connect to task updates
const ws = new WebSocket('ws://localhost:8000/api/v1/ws/tasks?token=JWT_TOKEN');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'task_update') {
    console.log(`Task ${data.task_id} status: ${data.status}`);
  }
};

// Subscribe to specific task
ws.send(JSON.stringify({
  type: 'subscribe_task',
  task_id: 'task-uuid'
}));
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
# Build images
docker build -t zepgpu:latest -f docker/Dockerfile .
docker build -t zepgpu-ui:latest -f zepgpu-ui/Dockerfile .

# Run stack
docker-compose -f docker/docker-compose.yml up -d

# Run with GPU support
docker-compose -f docker/docker-compose.yml up -d --profile gpu
```

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

Import dashboards from `docker/grafana/provisioning/`:

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
