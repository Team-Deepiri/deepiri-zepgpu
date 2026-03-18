# Basic Task Submission

## Overview

This tutorial covers the basics of submitting GPU tasks using the DeepIRI ZepGPU framework.

## Prerequisites

```bash
pip install deepiri-zepgpu[gpu,ml]
```

## Simple Example

```python
import numpy as np
from deepiri_zepgpu import submit_task

def matrix_multiply(A, B):
    return np.matmul(A, B)

A = np.random.randn(1000, 1000).astype(np.float32)
B = np.random.randn(1000, 1000).astype(np.float32)

# Submit task (non-blocking)
task_id = submit_task(
    matrix_multiply,
    A, B,
    gpu_memory_mb=2048,
)

print(f"Task submitted: {task_id}")
```

## Wait for Result

```python
# Submit and wait for result
result = submit_task(
    matrix_multiply,
    A, B,
    wait=True,
    timeout_seconds=300,
)

print(f"Result shape: {result.shape}")
```

## Using TaskSubmitter

```python
import asyncio
from deepiri_zepgpu.api import TaskSubmitter

async def main():
    submitter = TaskSubmitter()
    await submitter.start()
    
    task_id = await submitter.submit(
        matrix_multiply,
        A, B,
        priority=TaskPriority.HIGH,
    )
    
    # Poll for completion
    while True:
        task = submitter.get_task(task_id)
        print(f"Status: {task.status}")
        if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            break
        await asyncio.sleep(1)
    
    await submitter.stop()

asyncio.run(main())
```

## Key Concepts

### GPU Memory
Specify required GPU memory in MB:

```python
submit_task(func, A, B, gpu_memory_mb=4096)
```

### Timeout
Set task timeout:

```python
submit_task(func, A, B, timeout_seconds=7200)
```

### Priority
Set task priority:

```python
from deepiri_zepgpu.core.task import TaskPriority

submit_task(func, A, B, priority=TaskPriority.HIGH)
```

### User ID
Track tasks by user:

```python
submit_task(func, A, B, user_id="researcher-001")
```
