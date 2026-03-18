"""Task query and status monitoring API."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from deepiri_zepgpu.core.task import Task, TaskStatus
from deepiri_zepgpu.core.scheduler import TaskScheduler


class TaskQuery:
    """Query interface for task status and results."""

    def __init__(self, scheduler: TaskScheduler):
        self._scheduler = scheduler

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        return self._scheduler.get_task(task_id)

    def get_status(self, task_id: str) -> Optional[str]:
        """Get task status as string."""
        task = self.get_task(task_id)
        return task.status.value if task else None

    def is_complete(self, task_id: str) -> bool:
        """Check if task is complete (success or failure)."""
        task = self.get_task(task_id)
        return task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}

    def is_success(self, task_id: str) -> bool:
        """Check if task completed successfully."""
        task = self.get_task(task_id)
        return task.status == TaskStatus.COMPLETED if task else False

    def get_result(self, task_id: str) -> Any:
        """Get task result if available."""
        task = self.get_task(task_id)
        if not task:
            return None
        if task.status != TaskStatus.COMPLETED:
            raise RuntimeError(f"Task {task_id} not completed: {task.status.value}")
        return task.result

    def get_error(self, task_id: str) -> Optional[str]:
        """Get task error message if failed."""
        task = self.get_task(task_id)
        return task.error if task else None

    def get_execution_time(self, task_id: str) -> Optional[float]:
        """Get task execution time in seconds."""
        task = self.get_task(task_id)
        if not task or not task.started_at or not task.completed_at:
            return None
        return (task.completed_at - task.started_at).total_seconds()

    def get_wait_time(self, task_id: str) -> Optional[float]:
        """Get time spent waiting in queue."""
        task = self.get_task(task_id)
        if not task or not task.created_at or not task.started_at:
            return None
        return (task.started_at - task.created_at).total_seconds()

    def list_tasks(
        self,
        user_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> list[Task]:
        """List tasks with filtering."""
        tasks = self._scheduler.list_tasks(user_id, status)
        return tasks[:limit]

    def list_running_tasks(self, user_id: Optional[str] = None) -> list[Task]:
        """List currently running tasks."""
        return self.list_tasks(user_id=user_id, status=TaskStatus.RUNNING)

    def list_pending_tasks(self, user_id: Optional[str] = None) -> list[Task]:
        """List pending tasks."""
        return self.list_tasks(user_id=user_id, status=TaskStatus.QUEUED)

    def list_user_tasks(
        self,
        user_id: str,
        status: Optional[TaskStatus] = None,
    ) -> list[Task]:
        """List all tasks for a specific user."""
        return self.list_tasks(user_id=user_id, status=status)

    def get_task_history(
        self,
        user_id: Optional[str] = None,
        hours: int = 24,
    ) -> list[Task]:
        """Get task history for the specified time period."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        tasks = self.list_tasks(user_id=user_id)
        return [t for t in tasks if t.created_at >= cutoff]

    def get_user_stats(self, user_id: str) -> dict[str, Any]:
        """Get statistics for a user."""
        tasks = self.list_user_tasks(user_id)

        completed = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        failed = [t for t in tasks if t.status == TaskStatus.FAILED]
        running = [t for t in tasks if t.status == TaskStatus.RUNNING]

        exec_times = [
            (t.completed_at - t.started_at).total_seconds()
            for t in completed
            if t.started_at and t.completed_at
        ]

        return {
            "user_id": user_id,
            "total_tasks": len(tasks),
            "completed": len(completed),
            "failed": len(failed),
            "running": len(running),
            "pending": len(tasks) - len(completed) - len(failed) - len(running),
            "average_execution_time": sum(exec_times) / len(exec_times) if exec_times else 0,
            "total_execution_time": sum(exec_times),
        }


class TaskWatcher:
    """Watch task status changes with callbacks."""

    def __init__(self, query: TaskQuery, poll_interval: float = 0.5):
        self._query = query
        self._poll_interval = poll_interval
        self._callbacks: dict[str, list[callable]] = {}

    def watch(
        self,
        task_id: str,
        on_complete: Optional[callable] = None,
        on_error: Optional[callable] = None,
        on_progress: Optional[callable] = None,
    ) -> None:
        """Register callbacks for task events."""
        if task_id not in self._callbacks:
            self._callbacks[task_id] = []
        if on_complete:
            self._callbacks[task_id].append(("complete", on_complete))
        if on_error:
            self._callbacks[task_id].append(("error", on_error))
        if on_progress:
            self._callbacks[task_id].append(("progress", on_progress))

    async def wait_for_completion(self, task_id: str) -> Task:
        """Wait for task to complete."""
        import asyncio
        while True:
            task = self._query.get_task(task_id)
            if not task:
                raise RuntimeError(f"Task {task_id} not found")
            if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                return task
            await asyncio.sleep(self._poll_interval)

    async def wait_for_result(self, task_id: str) -> Any:
        """Wait for task result."""
        task = await self.wait_for_completion(task_id)
        if task.status != TaskStatus.COMPLETED:
            raise RuntimeError(f"Task failed: {task.error}")
        return task.result
