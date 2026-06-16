# API Reference

ZepGPU exposes two interfaces:

- **[HTTP / REST API](#http--rest-api)** — for remote clients over HTTP/WebSocket. This is
  what the Docker Compose stack serves on `http://localhost:8000`.
- **[Python SDK](#python-sdk)** — the in-process library (`submit_task`, `TaskSubmitter`,
  etc.) for embedding ZepGPU directly in Python code.

---

# HTTP / REST API

Verified examples for the ZepGPU REST and WebSocket API as served by the default Docker
Compose stack. Every request/response in this section was exercised against a running local
stack (`docker compose -f docker/docker-compose.yml up -d`).

- Base URL: `http://localhost:8000`
- All REST routes are mounted under the `/api/v1` prefix.
- Interactive OpenAPI docs: `http://localhost:8000/docs`
- Authentication endpoints are available under **both** `/api/v1/auth/*` and
  `/api/v1/users/*` (they share the same router).

> Examples use `random.seed` as a harmless no-op function: it takes no required arguments
> and returns `None`. See [Task result behavior](#task-result-behavior) for why the example
> functions return `None`.

**Sections:** [Authentication](#authentication) ·
[Tasks](#tasks) ·
[Task result behavior](#task-result-behavior) ·
[Callbacks (webhooks)](#callbacks-webhooks) ·
[Pipelines](#pipelines) ·
[WebSockets](#websockets) ·
[Error responses](#error-responses)

## Authentication

### Register

`POST /api/v1/auth/register`

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","email":"demo@example.com","password":"password123"}'
```

Response `201 Created`:

```json
{
  "id": "39cb0e97-f742-408c-8267-62b150dcb85b",
  "username": "demo",
  "email": "demo@example.com",
  "role": "user",
  "first_name": null,
  "last_name": null,
  "is_active": true,
  "is_verified": false,
  "created_at": "2026-06-15T19:05:25.464216Z",
  "last_login_at": null
}
```

Constraints: `username` 3–50 chars, `password` at least 8 chars, `email` must be valid.
A duplicate username or email returns `400`.

### Login

`POST /api/v1/auth/login`

The body must be **JSON** (not form-encoded). A form-encoded body returns `422`.

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"password123"}'
```

Response `200 OK`:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

Save the token for subsequent calls:

```bash
export TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"password123"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
```

Invalid credentials return `401`.

### Current user

`GET /api/v1/users/me`

```bash
curl -s http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN"
```

Response `200 OK` returns the same user shape as registration, with `last_login_at` set.

## Tasks

### Create a task

`POST /api/v1/tasks`

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Optional display name |
| `func_name` | string | Dotted Python path, e.g. `package.module.function` |
| `serialized_func` | string | Alternative to `func_name` (cloudpickle payload) |
| `args` / `kwargs` | string | Optional serialized positional/keyword args |
| `priority` | int (1–5) | Default `2` |
| `gpu_memory_mb` | int ≥ 0 | `0` runs without GPU allocation |
| `timeout_seconds` | int ≥ 1 | Default `3600` |
| `gpu_type` | string | Optional required GPU type |
| `allow_fallback_cpu` | bool | Default `true` |
| `callback_url` | string | Optional webhook (see [Callbacks](#callbacks-webhooks)) |

Either `func_name` or `serialized_func` is required. A `func_name` that is not a valid
dotted path (e.g. `notdotted`) returns `400`.

```bash
curl -s -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Smoke test","func_name":"random.seed","gpu_memory_mb":0}'
```

Response `201 Created`:

```json
{
  "id": "66d3cf97-4329-45cc-8d9a-90ea60d57687",
  "name": "Smoke test",
  "status": "pending",
  "priority": 2,
  "gpu_memory_mb": 0,
  "timeout_seconds": 3600,
  "gpu_type": null,
  "gpu_device_id": null,
  "created_at": "2026-06-15T19:05:25.742186Z",
  "started_at": null,
  "completed_at": null,
  "error": null,
  "execution_time_ms": null,
  "user_id": "39cb0e97-f742-408c-8267-62b150dcb85b"
}
```

### Get a task

`GET /api/v1/tasks/{task_id}`

```bash
curl -s http://localhost:8000/api/v1/tasks/$TASK_ID \
  -H "Authorization: Bearer $TOKEN"
```

Within a few seconds, `status` transitions `pending` → `completed` for the no-op above.

### List tasks

`GET /api/v1/tasks`

Query parameters: `status` (filter), `limit` (1–1000, default 100), `offset` (default 0).

```bash
curl -s "http://localhost:8000/api/v1/tasks?limit=10" \
  -H "Authorization: Bearer $TOKEN"
```

Response `200 OK`:

```json
{
  "tasks": [ { "id": "...", "status": "completed", ... } ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

### Get a task result

`GET /api/v1/tasks/{task_id}/result`

```bash
curl -s http://localhost:8000/api/v1/tasks/$TASK_ID/result \
  -H "Authorization: Bearer $TOKEN"
```

Response `200 OK`:

```json
{
  "task_id": "66d3cf97-4329-45cc-8d9a-90ea60d57687",
  "status": "completed",
  "result": null,
  "presigned_url": null
}
```

### Cancel a task

`DELETE /api/v1/tasks/{task_id}`

Returns `204 No Content`. Only tasks that are still `pending`/`queued`/`running` can be
cancelled; cancelling an already-terminated task returns `400`.

```bash
curl -s -X DELETE http://localhost:8000/api/v1/tasks/$TASK_ID \
  -H "Authorization: Bearer $TOKEN"
```

### Retry a task

`POST /api/v1/tasks/{task_id}/retry`

Re-enqueues a `failed`, `cancelled`, or `timeout` task and returns the updated task.

## Task result behavior

The examples in this section use functions that return `None` (such as `random.seed`).
A task whose function returns `None` is recorded as `completed` with `result: null`.

In the default local stack, a task whose function **returns a value** requires the
Redis-backed result store to be reachable from the Celery worker. If it is not, the task
ends in `failed` with an error similar to:

```
'NoneType' object has no attribute 'set_task_result'
```

See the [deployment troubleshooting guide](deployment_troubleshooting.md#tasks-fail-with-nonetype-object-has-no-attribute-set_task_result)
for details and remediation.

## Callbacks (webhooks)

Provide a `callback_url` when creating a task. When the task finishes (success or failure),
the worker sends a `POST` to that URL with a JSON body.

```bash
curl -s -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"With callback","func_name":"random.seed","gpu_memory_mb":0,
       "callback_url":"http://host.docker.internal:9099/hook"}'
```

Webhook payload delivered to `callback_url`:

```json
{
  "task_id": "5787fa84-f8ca-422b-a97d-7f71ca12a08f",
  "status": "completed",
  "user_id": "f15ee280-dca5-440e-8da7-75805708fcbd"
}
```

Notes:

- `task_id` is the ZepGPU database task ID (the same `id` returned by task creation).
- `status` is `completed` or `failed`.
- The callback is best-effort: delivery failures are logged and do not affect task state.
- From inside the Docker network, use a host-reachable URL such as
  `http://host.docker.internal:<port>` to receive callbacks on your host machine.

## Pipelines

### Create a pipeline

`POST /api/v1/pipelines`

Each stage has a `name`, an optional `func_name`, optional `args`, and an optional
`depends_on` list referencing earlier stage names.

```bash
curl -s -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Demo Pipeline",
    "description": "two stage",
    "stages": [
      {"name": "preprocess", "func_name": "random.seed"},
      {"name": "train", "func_name": "random.seed", "depends_on": ["preprocess"]}
    ]
  }'
```

Response `201 Created`:

```json
{
  "id": "1a0715e0-c13c-4840-9b2f-b733cdd29c0c",
  "name": "Demo Pipeline",
  "description": "two stage",
  "status": "created",
  "stages": [ {"name": "preprocess", "func_name": "random.seed", ...} ],
  "stage_statuses": {"preprocess": "pending", "train": "pending"},
  "completed_stages": 0,
  "total_stages": 2,
  "progress_percent": 0.0,
  "created_at": "2026-06-15T19:20:34.325376Z",
  "started_at": null,
  "completed_at": null,
  "error": null,
  "user_id": "b8245a69-fea7-4f0c-b73f-1f3ff2394771"
}
```

### Run a pipeline

`POST /api/v1/pipelines/{pipeline_id}/run`

```bash
curl -s -X POST http://localhost:8000/api/v1/pipelines/$PIPELINE_ID/run \
  -H "Authorization: Bearer $TOKEN"
```

Response `200 OK`:

```json
{ "message": "Pipeline started", "pipeline_id": "1a0715e0-c13c-4840-9b2f-b733cdd29c0c" }
```

### Get / list / delete pipelines

- `GET /api/v1/pipelines/{pipeline_id}` — pipeline detail
- `GET /api/v1/pipelines` — list (supports `status`, `limit`, `offset`)
- `DELETE /api/v1/pipelines/{pipeline_id}` — returns `204`

> **Current behavior:** The pipeline executor dispatches a stage only when the stage carries
> a pre-created task reference (`task_id`). Stages defined solely with a `func_name` are
> marked as skipped, so a pipeline can report `completed` with `0` executed stages. Treat
> pipeline orchestration as create/run/track plumbing rather than per-stage function
> execution for now.

## WebSockets

Three authenticated streams are available. Pass the JWT as a `token` query parameter:

| Endpoint | Purpose |
|----------|---------|
| `ws://localhost:8000/api/v1/ws/tasks` | Task updates; supports `ping`, `subscribe_task`, `unsubscribe_task`, `get_status` |
| `ws://localhost:8000/api/v1/ws/gpus` | Periodic GPU metrics |
| `ws://localhost:8000/api/v1/ws/metrics` | Aggregated CPU / memory / queue / GPU metrics |

On connect, the server sends a `connected` message. A `ping` is answered with `pong`.

Browser example:

```javascript
const ws = new WebSocket('ws://localhost:8000/api/v1/ws/tasks?token=' + TOKEN);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data); // {"type":"connected",...} then {"type":"pong"}
};

ws.onopen = () => ws.send(JSON.stringify({ type: 'ping' }));
```

Verified message exchange:

```text
-> (connect)        <- {"type":"connected","user_id":"...","message":"Connected to task updates stream"}
-> {"type":"ping"}  <- {"type":"pong"}
```

**Authentication failures** are surfaced during the WebSocket handshake (not as a normal
close frame):

- A **missing or empty** `token` is rejected with **HTTP `403`** during the handshake.
- A **malformed/invalid** `token` currently returns **HTTP `500`** — the same `jwt.JWTError`
  defect described under [Error responses](#error-responses), since WebSocket auth shares
  the affected code path.

## Error responses

| Situation | Status |
|-----------|--------|
| Duplicate username/email on register | `400` |
| Invalid login credentials | `401` |
| Login with form-encoded body | `422` |
| Invalid `func_name` (not a dotted path) | `400` |
| Task/pipeline not found | `404` |
| Accessing another user's task/pipeline | `403` |
| Cancelling an already-terminated task | `400` |

> **Known issue:** Requests to protected REST routes with a **missing or invalid** bearer
> token currently return `500` (instead of `401`/`403`). This is a server-side defect, not a
> client/configuration problem — a valid token returns `200`. See the
> [troubleshooting guide](deployment_troubleshooting.md#unauthenticated-requests-return-500-instead-of-401).

---

# Python SDK

The in-process library for embedding ZepGPU directly in Python code.

## Task Submission API

### `submit_task()`

Submit a GPU task for execution.

```python
from deepiri_zepgpu import submit_task

task_id = submit_task(
    func,                    # Callable to execute
    *args,                   # Positional arguments
    user_id=None,            # Optional user identifier
    priority=NORMAL,         # Task priority
    gpu_memory_mb=1024,      # Required GPU memory
    timeout_seconds=3600,     # Task timeout
    gpu_type=None,           # Required GPU type (e.g., "A100")
    allow_fallback_cpu=True, # Allow CPU fallback
    wait=False,              # Wait for completion
    **kwargs                 # Keyword arguments
)
```

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| func | Callable | Required | Function to execute |
| *args | Any | () | Positional arguments for func |
| user_id | str | None | User identifier |
| priority | TaskPriority | NORMAL | Task priority level |
| gpu_memory_mb | int | 1024 | GPU memory in MB |
| timeout_seconds | int | 3600 | Timeout in seconds |
| gpu_type | str | None | Required GPU type |
| allow_fallback_cpu | bool | True | Allow CPU fallback |
| wait | bool | False | Wait for result |
| **kwargs | Any | {} | Keyword arguments |

**Returns:** `str` (task_id) or task result if `wait=True`

---

### `TaskSubmitter`

Main interface for task submission with lifecycle management.

```python
from deepiri_zepgpu.api import TaskSubmitter

submitter = TaskSubmitter()
await submitter.start()
```

#### Methods

##### `submit()`

Submit a task asynchronously.

```python
task_id = await submitter.submit(
    func=my_function,
    arg1, arg2,
    gpu_memory_mb=2048,
    priority=TaskPriority.HIGH,
)
```

##### `get_task()`

Get task by ID.

```python
task = submitter.get_task(task_id)
```

##### `cancel_task()`

Cancel a task.

```python
success = submitter.cancel_task(task_id)
```

##### `list_tasks()`

List tasks with filtering.

```python
tasks = submitter.list_tasks(
    user_id="user123",
    status=TaskStatus.RUNNING,
)
```

---

## Query API

### `TaskQuery`

Interface for querying task status and results.

```python
from deepiri_zepgpu.api import TaskQuery

query = TaskQuery(scheduler)
```

#### Methods

##### `get_status()`

Get task status as string.

```python
status = query.get_status(task_id)  # "running", "completed", etc.
```

##### `get_result()`

Get task result (raises if not completed).

```python
result = query.get_result(task_id)
```

##### `get_execution_time()`

Get execution time in seconds.

```python
exec_time = query.get_execution_time(task_id)
```

##### `get_user_stats()`

Get statistics for a user.

```python
stats = query.get_user_stats("user123")
# {"total_tasks": 42, "completed": 40, "failed": 2, ...}
```

---

## Pipeline API

### `PipelineBuilder`

Build multi-stage GPU compute pipelines.

```python
from deepiri_zepgpu.api.pipelines import PipelineBuilder

pipeline = (
    PipelineBuilder("my_pipeline")
    .preprocess(name="prep", func=preprocess_fn)
    .compute(name="model", func=model_fn, depends_on=["prep"], gpu_memory_mb=4096)
    .postprocess(name="post", func=postprocess_fn, depends_on=["model"])
    .build()
)
```

#### Methods

##### `add_stage()`

Add a generic pipeline stage.

```python
builder.add_stage(
    name="stage1",
    func=my_function,
    args={"data": "$previous_stage"},
    depends_on=["other_stage"],
    gpu_memory_mb=2048,
)
```

##### `preprocess()`, `compute()`, `postprocess()`

Convenience methods for common stage types.

---

## GPU Management API

### `GPUManager`

Abstract GPU allocation and monitoring.

```python
from deepiri_zepgpu.core.gpu_manager import GPUManager

gpu_manager = GPUManager()
await gpu_manager.initialize()
```

#### Methods

##### `get_available_device()`

Find an available GPU meeting requirements.

```python
device = gpu_manager.get_available_device(
    required_memory_mb=2048,
    gpu_type="A100",
)
```

##### `allocate_device()`

Allocate a specific GPU to a task.

```python
success = gpu_manager.allocate_device(device_id=0, task_id="task-123")
```

##### `list_devices()`

List all available GPUs.

```python
devices = gpu_manager.list_devices()
```

##### `start_monitoring()`

Start continuous GPU monitoring.

```python
await gpu_manager.start_monitoring(interval_seconds=5.0)
```

---

## Task Definition API

### `Task`

Represents a GPU compute task.

```python
from deepiri_zepgpu.core.task import Task, TaskResources, TaskPriority

task = Task(
    func=my_function,
    args=(arg1, arg2),
    kwargs={"key": "value"},
    resources=TaskResources(
        gpu_memory_mb=2048,
        timeout_seconds=3600,
    ),
    priority=TaskPriority.HIGH,
    user_id="user123",
)
```

### `TaskStatus`

Task status enum values:
- `PENDING` - Task created but not queued
- `QUEUED` - Task in queue
- `SCHEDULED` - Task assigned to GPU
- `RUNNING` - Task executing
- `COMPLETED` - Task finished successfully
- `FAILED` - Task failed
- `CANCELLED` - Task cancelled
- `TIMEOUT` - Task timed out

### `TaskPriority`

Priority levels:
- `LOW = 1`
- `NORMAL = 2`
- `HIGH = 3`
- `URGENT = 4`
- `CRITICAL = 5`

---

## Resource Caching API

### `ModelCache`

LRU cache for ML models.

```python
from deepiri_zepgpu.resources.models import ModelCache

cache = ModelCache(max_size_mb=10240)
cache.put("model_v1", model)
cached_model = cache.get("model_v1")
```

### `KernelCache`

Cache for compiled CUDA kernels.

```python
from deepiri_zepgpu.resources.kernel_cache import KernelCache

kernel_cache = KernelCache()
kernel = kernel_cache.compile_and_cache(
    name="my_kernel",
    source=cuda_source_code,
)
```

---

## Monitoring API

### `MetricsCollector`

Collect system and GPU metrics.

```python
from deepiri_zepgpu.monitoring import MetricsCollector

collector = MetricsCollector(collect_interval=5.0)
await collector.start()

# Get metrics
summary = collector.get_summary()
```

### `StructuredLogger`

JSON structured logging.

```python
from deepiri_zepgpu.monitoring import get_logger

logger = get_logger()
logger.info("Task completed", task_id="123", duration_ms=150)
```

### `AlertManager`

Manage alerts and notifications.

```python
from deepiri_zepgpu.monitoring import AlertManager, AlertType, AlertSeverity

alerts = AlertManager()
await alerts.alert_task_failed(task_id, error="Out of memory")
```

---

## Security API

### `UserManager`

User authentication and management.

```python
from deepiri_zepgpu.security import UserManager, UserRole

users = UserManager()
user = users.create_user(
    username="researcher1",
    email="researcher@example.com",
    role=UserRole.RESEARCHER,
)
token = users.create_token(user.user_id)
```

### `AccessControl`

Resource quota enforcement.

```python
from deepiri_zepgpu.security import AccessControl, Quota

access = AccessControl(default_quota=Quota(max_tasks=100, max_gpu_hours=24))
can_submit, reason = access.check_task_submission(user_id, task)
```
