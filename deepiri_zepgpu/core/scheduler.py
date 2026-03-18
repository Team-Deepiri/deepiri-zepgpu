"""Task scheduling with priority queues and resource allocation."""

from __future__ import annotations

import asyncio
import heapq
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from deepiri_zepgpu.core.task import Task, TaskPriority, TaskResources, TaskStatus
from deepiri_zepgpu.core.gpu_manager import GPUManager, GPUDevice


class SchedulingPolicy(Enum):
    """Task scheduling policies."""
    FIFO = "fifo"
    PRIORITY = "priority"
    FAIR_SHARE = "fair_share"
    DEADLINE = "deadline"
    ML_PREDICTED = "ml_predicted"


@dataclass
class QueueStats:
    """Statistics for task queues."""
    total_tasks: int = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    average_wait_time: float = 0.0
    average_execution_time: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass(order=True)
class PriorityTaskItem:
    """Priority queue item with ordering."""
    priority: int
    created_at: float
    task_id: str = field(compare=False)
    task: Task = field(compare=False)


class TaskScheduler:
    """Schedules and manages GPU task execution."""

    def __init__(
        self,
        gpu_manager: GPUManager,
        policy: SchedulingPolicy = SchedulingPolicy.PRIORITY,
        max_concurrent_tasks: int = 10,
        enable_preemption: bool = False,
    ):
        self._gpu_manager = gpu_manager
        self._policy = policy
        self._max_concurrent_tasks = max_concurrent_tasks
        self._enable_preemption = enable_preemption

        self._pending_queue: list[PriorityTaskItem] = []
        self._running_tasks: dict[str, Task] = {}
        self._completed_tasks: dict[str, Task] = {}
        self._failed_tasks: dict[str, Task] = {}

        self._task_callbacks: dict[str, Callable[[Task], None]] = {}
        self._user_quotas: dict[str, dict[str, int]] = defaultdict(
            lambda: {"max_tasks": 100, "max_gpu_hours": 24}
        )
        self._user_usage: dict[str, dict[str, float]] = defaultdict(
            lambda: {"tasks_submitted": 0, "gpu_seconds": 0.0}
        )

        self._lock = threading.RLock()
        self._scheduler_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._stats = QueueStats()

    async def start(self) -> None:
        """Start the scheduler."""
        await self._gpu_manager.initialize()
        self._scheduler_task = asyncio.create_task(self._schedule_loop())

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._stop_event.set()
        if self._scheduler_task:
            await self._scheduler_task
        await self._gpu_manager.stop_monitoring()
        self._gpu_manager.shutdown()

    async def submit_task(self, task: Task) -> str:
        """Submit a new task to the queue."""
        with self._lock:
            if not self._check_user_quota(task.user_id):
                raise RuntimeError(f"User {task.user_id} has exceeded quota")

            task.status = TaskStatus.QUEUED
            task_id = task.task_id

            priority_value = (
                (6 - task.priority.value) * 1_000_000_000 +
                task.created_at.timestamp()
            )
            heapq.heappush(
                self._pending_queue,
                PriorityTaskItem(
                    priority=priority_value,
                    created_at=task.created_at.timestamp(),
                    task_id=task_id,
                    task=task,
                )
            )

            self._stats.pending_tasks += 1
            self._stats.total_tasks += 1
            self._user_usage[task.user_id or "default"]["tasks_submitted"] += 1

        return task_id

    def _check_user_quota(self, user_id: Optional[str]) -> bool:
        """Check if user is within their quota."""
        uid = user_id or "default"
        usage = self._user_usage[uid]
        quota = self._user_quotas[uid]
        return (
            usage["tasks_submitted"] < quota["max_tasks"] and
            usage["gpu_seconds"] < quota["max_gpu_hours"] * 3600
        )

    def set_user_quota(
        self,
        user_id: str,
        max_tasks: int,
        max_gpu_hours: float,
    ) -> None:
        """Set quota for a user."""
        self._user_quotas[user_id] = {
            "max_tasks": max_tasks,
            "max_gpu_hours": max_gpu_hours,
        }

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or running task."""
        with self._lock:
            for i, item in enumerate(self._pending_queue):
                if item.task_id == task_id:
                    task = item.task
                    del self._pending_queue[i]
                    heapq.heapify(self._pending_queue)
                    task.status = TaskStatus.CANCELLED
                    self._failed_tasks[task_id] = task
                    self._stats.pending_tasks -= 1
                    self._stats.failed_tasks += 1
                    self._notify_callback(task)
                    return True

            if task_id in self._running_tasks:
                task = self._running_tasks[task_id]
                task.status = TaskStatus.CANCELLED
                self._release_gpu_for_task(task)
                self._notify_callback(task)
                return True

        return False

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        with self._lock:
            for item in self._pending_queue:
                if item.task_id == task_id:
                    return item.task
            return (
                self._running_tasks.get(task_id) or
                self._completed_tasks.get(task_id) or
                self._failed_tasks.get(task_id)
            )

    def list_tasks(
        self,
        user_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
    ) -> list[Task]:
        """List tasks with optional filtering."""
        with self._lock:
            all_tasks: list[Task] = []
            for item in self._pending_queue:
                all_tasks.append(item.task)
            all_tasks.extend(self._running_tasks.values())
            all_tasks.extend(self._completed_tasks.values())
            all_tasks.extend(self._failed_tasks.values())

            if user_id:
                all_tasks = [t for t in all_tasks if t.user_id == user_id]
            if status:
                all_tasks = [t for t in all_tasks if t.status == status]

            return sorted(all_tasks, key=lambda t: t.created_at, reverse=True)

    def register_callback(
        self,
        task_id: str,
        callback: Callable[[Task], None],
    ) -> None:
        """Register callback for task completion."""
        self._task_callbacks[task_id] = callback

    async def _schedule_loop(self) -> None:
        """Main scheduling loop."""
        await self._gpu_manager.start_monitoring()

        while not self._stop_event.is_set():
            try:
                await self._schedule_pending_tasks()
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Scheduler error: {e}")

    async def _schedule_pending_tasks(self) -> None:
        """Schedule pending tasks to available GPUs."""
        with self._lock:
            available_slots = self._max_concurrent_tasks - len(self._running_tasks)

            if available_slots <= 0:
                return

            for _ in range(min(available_slots, len(self._pending_queue))):
                if not self._pending_queue:
                    break

                item = heapq.heappop(self._pending_queue)
                task = item.task

                device = self._gpu_manager.get_available_device(
                    required_memory_mb=task.resources.gpu_memory_mb,
                    gpu_type=task.resources.gpu_type,
                )

                if device is None and task.resources.allow_fallback_cpu:
                    device = self._gpu_manager.get_available_device(
                        required_memory_mb=0,
                        gpu_type="cpu",
                    )

                if device:
                    task.status = TaskStatus.SCHEDULED
                    task.gpu_device_id = device.device_id
                    self._gpu_manager.allocate_device(device.device_id, task.task_id)
                    self._running_tasks[task.task_id] = task
                    self._stats.pending_tasks -= 1
                    self._stats.running_tasks += 1
                else:
                    heapq.heappush(self._pending_queue, item)
                    break

    def mark_task_running(self, task_id: str) -> None:
        """Mark task as actually running."""
        with self._lock:
            task = self._running_tasks.get(task_id)
            if task:
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.utcnow()

    def mark_task_completed(
        self,
        task_id: str,
        result: Any = None,
    ) -> None:
        """Mark task as completed."""
        with self._lock:
            task = self._running_tasks.pop(task_id, None)
            if task:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.utcnow()
                task.result = result
                self._completed_tasks[task_id] = task
                self._stats.running_tasks -= 1
                self._stats.completed_tasks += 1
                self._release_gpu_for_task(task)
                self._update_stats(task)
                self._notify_callback(task)

    def mark_task_failed(
        self,
        task_id: str,
        error: str,
        traceback: Optional[str] = None,
    ) -> None:
        """Mark task as failed."""
        with self._lock:
            task = self._running_tasks.pop(task_id, None)
            if task:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                task.error = error
                task.traceback = traceback
                self._failed_tasks[task_id] = task
                self._stats.running_tasks -= 1
                self._stats.failed_tasks += 1
                self._release_gpu_for_task(task)
                self._update_stats(task)
                self._notify_callback(task)

    def _release_gpu_for_task(self, task: Task) -> None:
        """Release GPU resources allocated to task."""
        if task.gpu_device_id is not None:
            self._gpu_manager.release_device(task.gpu_device_id)
            task.gpu_device_id = None

    def _update_stats(self, task: Task) -> None:
        """Update queue statistics."""
        if task.started_at and task.completed_at:
            exec_time = (task.completed_at - task.started_at).total_seconds()
            total_completed = self._stats.completed_tasks
            self._stats.average_execution_time = (
                (self._stats.average_execution_time * (total_completed - 1) + exec_time) /
                total_completed if total_completed > 0 else exec_time
            )

            wait_time = (task.started_at - task.created_at).total_seconds()
            total_finished = self._stats.completed_tasks + self._stats.failed_tasks
            self._stats.average_wait_time = (
                (self._stats.average_wait_time * (total_finished - 1) + wait_time) /
                total_finished if total_finished > 0 else wait_time
            )

        self._stats.last_updated = datetime.utcnow()

    def _notify_callback(self, task: Task) -> None:
        """Notify registered callback for task."""
        callback = self._task_callbacks.pop(task.task_id, None)
        if callback:
            try:
                callback(task)
            except Exception as e:
                print(f"Callback error for task {task.task_id}: {e}")

    def get_stats(self) -> QueueStats:
        """Get queue statistics."""
        return self._stats

    def get_queue_length(self) -> int:
        """Get number of pending tasks."""
        with self._lock:
            return len(self._pending_queue)
