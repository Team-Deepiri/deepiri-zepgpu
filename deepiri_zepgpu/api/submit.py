"""Task submission API."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

from deepiri_zepgpu.core.task import Task, TaskResources, TaskPriority, TaskStatus
from deepiri_zepgpu.core.scheduler import TaskScheduler
from deepiri_zepgpu.core.gpu_manager import GPUManager
from deepiri_zepgpu.core.executor import TaskExecutor


class TaskSubmitter:
    """Main interface for submitting GPU tasks."""

    def __init__(
        self,
        scheduler: Optional[TaskScheduler] = None,
        gpu_manager: Optional[GPUManager] = None,
        executor: Optional[TaskExecutor] = None,
        auto_start: bool = True,
    ):
        self._gpu_manager = gpu_manager or GPUManager()
        self._executor = executor or TaskExecutor(self._gpu_manager)
        self._scheduler = scheduler or TaskScheduler(self._gpu_manager)
        self._auto_start = auto_start
        self._started = False

    async def start(self) -> None:
        """Start the task submitter."""
        if self._started:
            return
        await self._scheduler.start()
        self._started = True

    async def stop(self) -> None:
        """Stop the task submitter."""
        if not self._started:
            return
        await self._scheduler.stop()
        self._started = False

    async def submit(
        self,
        func: Callable[..., Any],
        *args: Any,
        user_id: Optional[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        gpu_memory_mb: int = 1024,
        timeout_seconds: int = 3600,
        gpu_type: Optional[str] = None,
        allow_fallback_cpu: bool = True,
        **kwargs: Any,
    ) -> str:
        """Submit a GPU task for execution."""
        if not self._started:
            await self.start()

        resources = TaskResources(
            gpu_memory_mb=gpu_memory_mb,
            timeout_seconds=timeout_seconds,
            gpu_type=gpu_type,
            allow_fallback_cpu=allow_fallback_cpu,
        )

        task = Task(
            func=func,
            args=args,
            kwargs=kwargs,
            resources=resources,
            priority=priority,
            user_id=user_id,
        )

        task_id = await self._scheduler.submit_task(task)

        asyncio.create_task(self._execute_task_async(task))

        return task_id

    async def _execute_task_async(self, task: Task) -> None:
        """Execute a task asynchronously."""
        while task.status == TaskStatus.QUEUED:
            await asyncio.sleep(0.1)

        if task.status != TaskStatus.SCHEDULED:
            return

        self._scheduler.mark_task_running(task.task_id)

        try:
            result = await self._executor.execute_task(task)
            if result.success:
                self._scheduler.mark_task_completed(task.task_id, result.result)
            else:
                self._scheduler.mark_task_failed(
                    task.task_id,
                    result.error or "Unknown error",
                    result.traceback,
                )
        except Exception as e:
            self._scheduler.mark_task_failed(task.task_id, str(e))

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        return self._scheduler.get_task(task_id)

    def get_task_status(self, task_id: str) -> Optional[str]:
        """Get task status as string."""
        task = self.get_task(task_id)
        return task.status.value if task else None

    def get_task_result(self, task_id: str) -> Any:
        """Get task result."""
        task = self.get_task(task_id)
        return task.result if task else None

    def list_tasks(
        self,
        user_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
    ) -> list[Task]:
        """List tasks."""
        return self._scheduler.list_tasks(user_id, status)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        return self._scheduler.cancel_task(task_id)


async def submit_task(
    func: Callable[..., Any],
    *args: Any,
    user_id: Optional[str] = None,
    priority: TaskPriority = TaskPriority.NORMAL,
    gpu_memory_mb: int = 1024,
    timeout_seconds: int = 3600,
    gpu_type: Optional[str] = None,
    allow_fallback_cpu: bool = True,
    wait: bool = False,
    **kwargs: Any,
) -> str | Any:
    """Convenience function to submit a GPU task.

    Args:
        func: The function to execute on GPU
        *args: Positional arguments for the function
        user_id: Optional user identifier
        priority: Task priority (default: NORMAL)
        gpu_memory_mb: Required GPU memory in MB (default: 1024)
        timeout_seconds: Task timeout in seconds (default: 3600)
        gpu_type: Required GPU type (e.g., "A100", "V100")
        allow_fallback_cpu: Allow CPU fallback if GPU unavailable
        wait: If True, wait for completion and return result
        **kwargs: Keyword arguments for the function

    Returns:
        Task ID if wait=False, otherwise the task result

    Example:
        >>> from deepiri_zepgpu import submit_task
        >>> import torch
        >>> def matrix_mult(a, b):
        ...     return torch.matmul(a, b)
        >>> task_id = submit_task(matrix_mult, A, B, gpu_memory_mb=2048)
        >>> result = submit_task(matrix_mult, A, B, wait=True)
    """
    submitter = TaskSubmitter()
    await submitter.start()

    task_id = await submitter.submit(
        func=func,
        *args,
        user_id=user_id,
        priority=priority,
        gpu_memory_mb=gpu_memory_mb,
        timeout_seconds=timeout_seconds,
        gpu_type=gpu_type,
        allow_fallback_cpu=allow_fallback_cpu,
        **kwargs,
    )

    if wait:
        while True:
            task = submitter.get_task(task_id)
            if task and task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                await submitter.stop()
                if task.status == TaskStatus.COMPLETED:
                    return task.result
                else:
                    raise RuntimeError(f"Task failed: {task.error}")
            await asyncio.sleep(0.5)

    await submitter.stop()
    return task_id


class AsyncTaskSubmitter:
    """Async context manager for task submission."""

    def __init__(self):
        self._submitter = TaskSubmitter()

    async def __aenter__(self) -> TaskSubmitter:
        await self._submitter.start()
        return self._submitter

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self._submitter.stop()
