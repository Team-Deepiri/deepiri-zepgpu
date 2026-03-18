# Architecture

## System Overview

DeepIRI ZepGPU implements a serverless GPU computing paradigm, allowing users to submit compute tasks that are dynamically scheduled, isolated, and executed on shared GPU resources.

## Component Architecture

### 1. API Layer

The API layer provides user-facing interfaces for task submission and management:

- **TaskSubmitter**: Main interface for submitting GPU tasks
- **TaskQuery**: Query task status and results
- **TaskCancellation**: Cancel pending/running tasks
- **PipelineBuilder**: Compose multi-stage pipelines

### 2. Core Engine

The core engine handles scheduling, execution, and GPU management:

- **TaskScheduler**: Priority-based task queue management
- **TaskExecutor**: Execute tasks with container isolation
- **GPUManager**: Abstract GPU allocation and monitoring
- **PipelineManager**: Coordinate multi-stage task pipelines

### 3. GPU Abstraction Layer

Provides virtualized GPU interface:

- Device discovery and enumeration
- Memory allocation and tracking
- Utilization monitoring
- Multi-GPU support (NVIDIA CUDA, AMD ROCm)
- Hardware metric collection (temperature, power, utilization)

### 4. Resource Layer

Manages preloaded resources:

- **ModelCache**: LRU cache for ML models
- **KernelCache**: Precompiled CUDA/CuPy kernels
- **DatasetCache**: Shared dataset storage

### 5. Monitoring Layer

Provides observability:

- **MetricsCollector**: System and GPU metrics
- **StructuredLogger**: JSON structured logging
- **MonitoringDashboard**: WebSocket real-time dashboard
- **AlertManager**: Task failure and SLA breach alerts

### 6. Security Layer

Ensures multi-tenant safety:

- **ContainerSandbox**: Docker container isolation
- **UserManager**: User authentication and roles
- **AccessControl**: Resource quota enforcement

---

## Data Flow

```
User Request
     │
     ▼
┌─────────────┐
│   API      │
│   Gateway  │
└─────────────┘
     │
     ▼
┌─────────────┐
│  Validation │
│  & Auth    │
└─────────────┘
     │
     ▼
┌─────────────┐
│  Scheduler  │◄──── Queue (Redis)
│  (Priority)  │
└─────────────┘
     │
     ▼
┌─────────────┐
│   GPU       │◄──── GPU Manager
│  Allocation │
└─────────────┘
     │
     ▼
┌─────────────┐
│  Executor   │◄──── Container Sandbox
│  (Docker)   │
└─────────────┘
     │
     ▼
┌─────────────┐
│   Result    │
│   Storage   │
└─────────────┘
```

---

## Scheduling Policies

### Priority Scheduling
Tasks are ordered by priority (CRITICAL > URGENT > HIGH > NORMAL > LOW), with creation time as tiebreaker.

### Fair Share
Each user gets equal GPU time allocation within the configured period.

### Deadline-Aware
Tasks with strict deadlines are prioritized over best-effort tasks.

---

## Resource Management

### GPU Memory
- Requested memory per task
- Memory tracking during execution
- Automatic cleanup on completion/timeout

### CPU Resources
- Configurable CPU core allocation
- CPU fallback when GPU unavailable

### Container Limits
- Memory limits (--memory)
- CPU limits (--cpus)
- GPU device access (--gpus)

---

## Monitoring & Telemetry

### Metrics Collected
- GPU utilization (%)
- GPU memory usage (MB)
- Task queue length
- Task execution time
- Task success/failure rate
- Temperature & power draw

### Alert Conditions
- Task timeout
- GPU over-temperature (>85°C)
- GPU memory exhaustion
- Queue backlog (>100 tasks)

---

## Security Model

### Isolation
Each task runs in an isolated Docker container:
- Network disabled by default
- Read-only root filesystem
- Restricted syscall set (seccomp)
- Memory and CPU limits enforced

### Authentication
- JWT tokens for API access
- Role-based access control (Admin, Researcher, User, Guest)
- Per-user resource quotas

### Resource Quotas
- Max tasks per period
- Max GPU hours per period
- Max concurrent tasks
- Max GPU memory per task

---

## Failure Handling

### Task Failures
- Automatic retry with exponential backoff
- Dead letter queue for failed tasks
- Detailed error reporting with tracebacks

### GPU Failures
- GPU health monitoring
- Automatic failover to healthy GPU
- Graceful degradation to CPU

### System Failures
- Checkpointing for long-running tasks
- Persistent queue (Redis)
- Database for task metadata (PostgreSQL)

---

## Scalability

### Horizontal Scaling
- Multiple scheduler instances
- Redis for distributed queue
- PostgreSQL for metadata

### Vertical Scaling
- Multiple GPUs per node
- GPU memory overcommit
- Dynamic GPU allocation

### Cross-Cloud
- Cloud-agnostic design
- S3-compatible object storage
- Kubernetes for orchestration
