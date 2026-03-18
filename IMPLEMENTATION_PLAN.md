# ZepGPU - Implementation Plan

## Overview

**Status: Production Ready - MVP Complete**  
**Last Updated: 2026-03-18**

---

## Project Vision

A production-grade serverless GPU framework enabling kernel-as-a-service computing. Users submit GPU compute tasks to a shared pool, with the system handling scheduling, isolation, execution, and result delivery.

**Repository:** `zepgpu` (formerly deepiri-zepgpu)

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Runtime** | Python 3.11+ | Primary language |
| **GPU** | CUDA 12+, PyTorch, JAX, CuPy | GPU compute |
| **API Server** | FastAPI + Uvicorn | REST API + WebSockets |
| **Frontend** | React + TypeScript + Vite | Web UI |
| **Task Queue** | Redis + Celery | Distributed task queue |
| **Database** | PostgreSQL 15 | Task metadata, users, audit logs |
| **Object Storage** | S3/MinIO | Large results, model artifacts |
| **Metrics** | Prometheus + Grafana | Monitoring & alerting |
| **Containers** | Docker + NVIDIA Docker | Task isolation |
| **Orchestration** | Kubernetes | Production deployment |

---

## Implementation Phases

### Phase 1: Core Framework ✅ COMPLETED
**Goal:** Basic Python API for task submission and GPU management

- [x] Task definition and status tracking
- [x] GPU manager with NVML integration
- [x] Basic scheduler with priority queue
- [x] Task executor with container support
- [x] Pipeline manager for multi-stage tasks
- [x] API layer (submit, query, cancel, pipelines)
- [x] Security layer (sandbox, user management, access control)
- [x] Monitoring layer (metrics, logging, alerts, dashboard)
- [x] Resources layer (model cache, kernel cache)
- [x] Utility functions
- [x] Example scripts
- [x] Docker configuration
- [x] Basic documentation
- [x] Unit tests

---

### Phase 2: Database & Persistence ✅ COMPLETED
**Goal:** Persistent storage for tasks, users, and results

#### 2.1 Database Models
- [x] Task model (metadata, status, resources, GPU allocation)
- [x] Pipeline model
- [x] User model
- [x] Audit log model
- [x] GPU device model
- [x] Quota model

#### 2.2 Database Migrations
- [x] Alembic configuration
- [x] Initial migration with all tables
- [x] Migration scripts

#### 2.3 Repository Layer
- [x] TaskRepository (CRUD, status updates, filtering)
- [x] UserRepository (auth, quota management)
- [x] PipelineRepository (multi-stage pipelines)
- [x] AuditLogRepository (audit trail)
- [x] GPUDeviceRepository (device tracking)

#### 2.4 Object Storage
- [x] S3/MinIO client
- [x] Large result handling
- [x] Presigned URLs
- [x] Result expiration

---

### Phase 3: API Server ✅ COMPLETED
**Goal:** Production-ready FastAPI server

#### 3.1 REST API Endpoints
- [x] POST /api/v1/tasks - Submit task
- [x] GET /api/v1/tasks/{id} - Get task
- [x] GET /api/v1/tasks - List tasks
- [x] DELETE /api/v1/tasks/{id} - Cancel task
- [x] GET /api/v1/tasks/{id}/result - Get result
- [x] POST /api/v1/pipelines - Create pipeline
- [x] GET /api/v1/pipelines/{id} - Get pipeline
- [x] POST /api/v1/auth/register - Register user
- [x] POST /api/v1/auth/login - Login user
- [x] GET /api/v1/users/me - Get current user
- [x] GET /api/v1/gpu/devices - List GPUs
- [x] GET /api/v1/metrics - Prometheus metrics
- [x] GET /api/v1/stats - System statistics
- [x] GET /api/v1/health - Health checks

#### 3.2 WebSocket Support
- [x] Task status updates (/api/v1/ws/tasks)
- [x] Real-time GPU metrics (/api/v1/ws/gpus)
- [x] System metrics stream (/api/v1/ws/metrics)

#### 3.3 Authentication
- [x] JWT token authentication
- [x] Role-based access control (admin, researcher, user, guest)
- [x] Password hashing with PBKDF2
- [x] User quota enforcement

---

### Phase 4: Task Queue ✅ COMPLETED
**Goal:** Distributed task execution with Redis/Celery

#### 4.1 Redis Integration
- [x] Redis connection pool
- [x] Task queue operations (enqueue/dequeue)
- [x] Pub/sub for status updates
- [x] Result caching

#### 4.2 Celery Workers
- [x] Worker configuration
- [x] Task routing
- [x] Priority handling
- [x] Retry policies
- [x] GPU task execution with cloudpickle serialization

#### 4.3 Job Scheduling
- [x] Pipeline execution tasks
- [x] GPU device synchronization
- [x] System health checks
- [x] Periodic cleanup tasks

---

### Phase 5: Monitoring & Observability ✅ COMPLETED
**Goal:** Production monitoring stack

#### 5.1 Prometheus Metrics
- [x] Task metrics (submitted, running, completed, failed)
- [x] GPU metrics (utilization, memory, temperature)
- [x] Queue metrics (length, wait time)
- [x] System metrics (CPU, memory, disk)
- [x] HTTP request metrics

#### 5.2 Grafana Dashboards
- [x] Task overview dashboard
- [x] GPU utilization dashboard
- [x] System health dashboard
- [x] Alert rules

#### 5.3 Logging
- [x] Structured JSON logging
- [x] Log aggregation
- [x] Log levels by component

---

### Phase 6: Production Deployment ✅ COMPLETED
**Goal:** Kubernetes-ready production deployment

#### 6.1 Kubernetes Manifests
- [x] Deployment for API server (zepgpu-api)
- [x] Deployment for UI server (zepgpu-ui)
- [x] Deployment for Celery workers (zepgpu-worker)
- [x] Deployment for Redis
- [x] Deployment for PostgreSQL (zepgpu-db)
- [x] Service definitions
- [x] ConfigMaps and Secrets
- [x] HPA (Horizontal Pod Autoscaler)

#### 6.2 Docker Compose
- [x] zepgpu (backend API)
- [x] zepgpu-ui (React frontend)
- [x] zepgpu-db (PostgreSQL)
- [x] redis (Task queue)
- [x] prometheus (Metrics)
- [x] grafana (Dashboards)

#### 6.3 CI/CD
- [x] GitHub Actions workflow
- [x] Docker image build
- [x] Test automation
- [x] Deployment pipeline

---

### Phase 7: Web UI (zepgpu-ui) ✅ COMPLETED
**Goal:** Full-featured React web interface

#### 7.1 Core Pages
- [x] Dashboard (stats, GPU status, recent tasks)
- [x] Tasks (list, filter, search, cancel)
- [x] Task Detail (view, monitor progress)
- [x] New Task (create task form)
- [x] Pipelines (list, create pipelines)
- [x] GPUs (monitor all GPU devices)
- [x] Login / Register

#### 7.2 UI Features
- [x] JWT authentication with token storage
- [x] React Query for data fetching
- [x] Zustand for state management
- [x] Tailwind CSS styling
- [x] Responsive design
- [x] Real-time WebSocket integration
- [x] Toast notifications
- [x] Dark theme

---

## Database Schema

### Tables

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT true,
    is_verified BOOLEAN DEFAULT false,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tasks table
CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',
    priority INTEGER DEFAULT 2,
    func_name VARCHAR(255),
    serialized_func BYTEA,
    args BYTEA,
    kwargs BYTEA,
    gpu_memory_mb INTEGER DEFAULT 1024,
    cpu_cores INTEGER DEFAULT 1,
    timeout_seconds INTEGER DEFAULT 3600,
    gpu_type VARCHAR(50),
    allow_fallback_cpu BOOLEAN DEFAULT true,
    gpu_device_id INTEGER,
    container_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error TEXT,
    traceback TEXT,
    result_ref VARCHAR(500),
    result_size_bytes BIGINT,
    execution_time_ms BIGINT,
    metadata_json JSONB DEFAULT '{}',
    tags JSONB,
    callback_url VARCHAR(500)
);

-- Pipelines table
CREATE TABLE pipelines (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    stages JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error TEXT
);

-- GPU devices table
CREATE TABLE gpu_devices (
    id SERIAL PRIMARY KEY,
    device_index INTEGER UNIQUE NOT NULL,
    uuid VARCHAR(255) UNIQUE,
    name VARCHAR(255),
    gpu_type VARCHAR(50) DEFAULT 'nvidia',
    vendor VARCHAR(100),
    driver_version VARCHAR(50),
    cuda_version VARCHAR(20),
    total_memory_mb BIGINT,
    available_memory_mb BIGINT,
    compute_capability_major INTEGER,
    compute_capability_minor INTEGER,
    max_cuda_cores INTEGER,
    num_multiprocessors INTEGER,
    state VARCHAR(50) DEFAULT 'idle',
    current_task_id VARCHAR(255),
    utilization_percent FLOAT,
    memory_utilization_percent FLOAT,
    temperature_celsius INTEGER,
    power_draw_watts FLOAT,
    power_limit_watts FLOAT,
    fan_speed_percent INTEGER,
    clock_speed_mhz INTEGER,
    memory_clock_mhz INTEGER,
    pci_bus_id VARCHAR(50),
    pci_device_id INTEGER,
    is_available BOOLEAN DEFAULT true,
    is_monitored BOOLEAN DEFAULT true,
    last_seen TIMESTAMP DEFAULT NOW()
);

-- Audit logs table
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(255),
    details JSONB,
    ip_address INET,
    user_agent VARCHAR(500),
    status_code INTEGER,
    error_message VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW()
);

-- User quotas table
CREATE TABLE user_quotas (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    max_tasks INTEGER DEFAULT 100,
    max_gpu_hours DECIMAL(10,2) DEFAULT 24,
    max_concurrent_tasks INTEGER DEFAULT 4,
    max_gpu_memory_mb INTEGER DEFAULT 16384,
    period_hours INTEGER DEFAULT 24,
    tasks_submitted INTEGER DEFAULT 0,
    gpu_seconds_used DECIMAL(15,2) DEFAULT 0,
    concurrent_tasks INTEGER DEFAULT 0,
    period_start TIMESTAMP DEFAULT NOW()
);
```

---

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login and get JWT token |

### Users
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/users/me` | Get current user |
| PUT | `/api/v1/users/me` | Update user profile |
| GET | `/api/v1/users/me/quota` | Get quota usage |

### Tasks
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/tasks` | Submit a new task |
| GET | `/api/v1/tasks` | List tasks (with filters) |
| GET | `/api/v1/tasks/{id}` | Get task details |
| DELETE | `/api/v1/tasks/{id}` | Cancel a task |
| GET | `/api/v1/tasks/{id}/result` | Get task result |
| POST | `/api/v1/tasks/{id}/retry` | Retry failed task |

### Pipelines
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/pipelines` | Create a pipeline |
| GET | `/api/v1/pipelines` | List pipelines |
| GET | `/api/v1/pipelines/{id}` | Get pipeline details |
| POST | `/api/v1/pipelines/{id}/run` | Execute pipeline |
| DELETE | `/api/v1/pipelines/{id}` | Delete pipeline |

### GPU
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/gpu/devices` | List GPU devices |
| GET | `/api/v1/gpu/devices/{id}` | Get device details |
| GET | `/api/v1/gpu/metrics` | Get GPU metrics |

### WebSocket
| Endpoint | Description |
|----------|-------------|
| `/api/v1/ws/tasks` | Real-time task updates |
| `/api/v1/ws/gpus` | Real-time GPU metrics |
| `/api/v1/ws/metrics` | System metrics stream |

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/stats` | System statistics |
| GET | `/api/v1/metrics` | Prometheus metrics |

---

## File Structure

```
zepgpu/
├── deepiri_zepgpu/                 # Python backend package
│   ├── __init__.py
│   ├── cli.py                     # CLI entry point
│   ├── config.py                  # Pydantic settings
│   ├── api/
│   │   ├── submit.py
│   │   ├── query.py
│   │   ├── cancel.py
│   │   ├── pipelines.py
│   │   └── server/                # FastAPI server
│   │       ├── main.py
│   │       ├── dependencies.py
│   │       ├── websocket_manager.py
│   │       └── routes/
│   │           ├── tasks.py
│   │           ├── users.py
│   │           ├── pipelines.py
│   │           ├── gpu.py
│   │           ├── health.py
│   │           └── websocket.py
│   ├── core/                      # Core engine
│   │   ├── task.py
│   │   ├── scheduler.py
│   │   ├── executor.py
│   │   ├── gpu_manager.py
│   │   └── pipeline_manager.py
│   ├── database/                  # Database layer
│   │   ├── session.py
│   │   ├── models/
│   │   └── repositories/
│   ├── queue/                    # Task queue
│   │   ├── redis_queue.py
│   │   ├── celery_app.py
│   │   └── tasks.py
│   ├── storage/                  # Storage layer
│   │   ├── s3_client.py
│   │   └── result_store.py
│   ├── resources/                 # Caching
│   ├── monitoring/               # Observability
│   ├── security/                 # Auth & sandboxing
│   └── utils/                    # Utilities
├── zepgpu-ui/                    # React frontend
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── api/
│   │   ├── stores/
│   │   └── types/
│   └── Dockerfile
├── docker/                       # Docker configs
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── prometheus.yml
├── k8s/                          # Kubernetes manifests
│   └── deployment.yaml
├── alembic/                      # Database migrations
│   └── versions/
├── examples/                      # Example scripts
├── tests/                        # Unit tests
├── docs/                         # Documentation
├── pyproject.toml
├── alembic.ini
└── README.md
```

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://zepgpu:zepgpu@zepgpu-db:5432/zepgpu
DATABASE_POOL_SIZE=10

# Redis
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# S3/MinIO
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET_NAME=zepgpu-results

# API Server
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4

# Authentication
JWT_SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=1440

# GPU Settings
CUDA_VISIBLE_DEVICES=0,1
GPU_MEMORY_RESERVE_MB=1024
```

---

## What's Next - Next Phases

### Recent Bug Fixes ✅
- [x] Fixed `pipelines.py` `/run` endpoint to actually execute pipeline via `execute_pipeline.delay()`
- [x] Added callback execution in Celery tasks via `GPUTask.on_success()` and `on_failure()` hooks
- [x] Added `_execute_callback()` function to trigger webhook notifications on task completion

---

## Phase 8: Integration Testing & End-to-End Validation 🔄 IN PROGRESS

**Goal:** Verify the entire system works end-to-end

#### 8.1 End-to-End Testing
- [ ] Run docker-compose and verify task submission flow
- [ ] Test pipeline creation and execution
- [ ] Verify callback webhooks fire correctly
- [ ] Test WebSocket real-time updates
- [ ] Validate JWT authentication flow

#### 8.2 Fix Integration Issues
- [ ] Fix async/await issues in ResultStore
- [ ] Handle S3/MinIO connection errors gracefully
- [ ] Add retry logic for Redis connections
- [ ] Fix potential race conditions in GPU allocation

#### 8.3 Documentation
- [ ] Update README with quick start guide
- [ ] Add API documentation with examples
- [ ] Create deployment troubleshooting guide

---

## Phase 9: Cron-Like Task Scheduling

**Goal:** Add periodic/scheduled task execution

#### 9.1 Scheduled Tasks
- [ ] Add Celery Beat for periodic task scheduling
- [ ] Create `/api/v1/schedules` endpoints
- [ ] Support cron expressions for pipeline scheduling
- [ ] Add schedule management UI in frontend

#### 9.2 Delayed Tasks
- [ ] Support delayed task execution
- [ ] Add `execute_at` parameter to task creation
- [ ] Implement task queue with ETA

---

## Phase 10: Advanced Scheduling

**Goal:** Production-grade scheduling algorithms

#### 10.1 Gang Scheduling
- [ ] Support multi-GPU distributed ML training tasks
- [ ] Allocate multiple GPUs atomically
- [ ] Handle partial allocation failures

#### 10.2 Preemption
- [ ] Add preemption support for high-priority tasks
- [ ] Implement graceful task migration
- [ ] Add checkpoint/resume capability

#### 10.3 Fair Share
- [ ] Implement fair share scheduling per user
- [ ] Add weighted priority queues
- [ ] Track GPU time per user/namespace

---

## Phase 11: Multi-Tenant Support

**Goal:** Support multiple organizations/teams

#### 11.1 Namespace Isolation
- [ ] Add namespace model and endpoints
- [ ] Isolate resources per namespace
- [ ] Add namespace-scoped GPU allocation

#### 11.2 Team Management
- [ ] Add team/user role mapping
- [ ] Implement team quotas
- [ ] Add team-level billing tracking

---

## Phase 12: Hybrid Cloud (Future)

**Goal:** Support cloud GPU providers

#### 12.1 Cloud Integration
- [ ] Abstract GPU provider interface
- [ ] Implement RunPod API integration
- [ ] Support AWS EC2 GPU instances
- [ ] Add spot instance management

#### 12.2 Cost Optimization
- [ ] Compare on-prem vs cloud costs
- [ ] Auto-scale based on queue depth
- [ ] Implement cloud burst on demand

---

## Immediate Next Steps

1. **Run integration tests** - Start docker-compose, submit a test task, verify execution
2. **Fix async issues** - Ensure ResultStore handles async properly throughout
3. **Test callbacks** - Set up a test webhook endpoint and verify callbacks fire
4. **Add example scripts** - Create example Python scripts demonstrating task submission
5. **Update README** - Add quick start guide with docker-compose

---

## Priority Queue

| Priority | Task | Phase | Status |
|----------|------|-------|--------|
| P0 | Integration testing | Phase 8 | 🔄 Now |
| P1 | Cron/Beat scheduling | Phase 9 | 📋 Next |
| P2 | Gang scheduling | Phase 10 | 📋 Planned |
| P3 | Multi-tenant | Phase 11 | 📋 Future |
| P4 | Cloud integration | Phase 12 | 📋 Future |

---

## Milestones

| Milestone | Target | Status |
|-----------|--------|--------|
| M1: Basic API & Core | Week 1-2 | ✅ Complete |
| M2: Database Integration | Week 2-3 | ✅ Complete |
| M3: Full API Server + Auth | Week 3-4 | ✅ Complete |
| M4: Web UI | Week 4-5 | ✅ Complete |
| M5: Monitoring Stack | Week 5-6 | ✅ Complete |
| M6: Kubernetes Deployment | Week 6-7 | ✅ Complete |
| M7: Bug Fixes | Week 7-8 | ✅ Complete |
| M8: Integration Testing | Week 8-9 | 🔄 In Progress |
| M9: Cron Scheduling | Week 9-10 | 📋 Planned |
| M10: Advanced Scheduling | Week 10-12 | 📋 Planned |
| M11: Multi-Tenant | Week 12-14 | 📋 Planned |
| M12: Hybrid Cloud | Week 14-18 | 📋 Future |

---

## Success Criteria

1. **Functional**: All core APIs work correctly
2. **Reliable**: 99.9% uptime for API server
3. **Performant**: Sub-100ms API response times
4. **Secure**: No security vulnerabilities
5. **Observable**: Full metrics and logging coverage
6. **Documented**: Complete API docs and tutorials
7. **Testable**: >80% test coverage

---

## Contributing

Contributions are welcome! Please see `CONTRIBUTING.md` for guidelines.

## License

MIT License - see LICENSE file for details.
