# API Reference

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
