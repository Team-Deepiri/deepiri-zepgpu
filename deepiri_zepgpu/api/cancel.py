"""Task cancellation API."""

from __future__ import annotations

from typing import Optional

from deepiri_zepgpu.core.task import Task
from deepiri_zepgpu.core.scheduler import TaskScheduler


class TaskCancellation:
    """Handle task cancellation requests."""

    def __init__(self, scheduler: TaskScheduler):
        self._scheduler = scheduler

    def cancel(self, task_id: str) -> bool:
        """Cancel a single task."""
        return self._scheduler.cancel_task(task_id)

    def cancel_many(self, task_ids: list[str]) -> dict[str, bool]:
        """Cancel multiple tasks."""
        return {task_id: self.cancel(task_id) for task_id in task_ids}

    def cancel_user_tasks(
        self,
        user_id: str,
        status: Optional[str] = None,
    ) -> list[str]:
        """Cancel all tasks for a user."""
        from deepiri_zepgpu.core.task import TaskStatus

        tasks = self._scheduler.list_tasks(user_id=user_id)
        if status:
            target_status = TaskStatus(status)
            tasks = [t for t in tasks if t.status == target_status]

        cancelled = []
        for task in tasks:
            if task.status in {TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.SCHEDULED}:
                if self.cancel(task.task_id):
                    cancelled.append(task.task_id)

        return cancelled

    def cancel_by_tag(self, tag: str) -> list[str]:
        """Cancel all tasks with a specific tag."""
        tasks = self._scheduler.list_tasks()
        tasks = [t for t in tasks if tag in t.tags]

        cancelled = []
        for task in tasks:
            if self.cancel(task.task_id):
                cancelled.append(task.task_id)

        return cancelled

    def get_cancel_status(self, task_id: str) -> Optional[str]:
        """Get the status of a cancellation request."""
        task = self._scheduler.get_task(task_id)
        if not task:
            return None
        if task.status == TaskStatus.CANCELLED:
            return "cancelled"
        elif task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            return "not_applicable"
        else:
            return "pending"
