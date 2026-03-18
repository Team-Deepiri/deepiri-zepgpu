"""Resource quota and access control."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from deepiri_zepgpu.core.task import Task


class ResourceType(Enum):
    """Resource types for quota enforcement."""
    TASKS = "tasks"
    GPU_HOURS = "gpu_hours"
    GPU_MEMORY = "gpu_memory"
    CONCURRENT_TASKS = "concurrent_tasks"
    STORAGE_GB = "storage_gb"


@dataclass
class Quota:
    """Resource quota for a user or group."""
    max_tasks: int = 100
    max_gpu_hours: float = 24.0
    max_gpu_memory_mb: int = 16384
    max_concurrent_tasks: int = 4
    max_storage_gb: int = 100


@dataclass
class ResourceUsage:
    """Current resource usage."""
    tasks_submitted: int = 0
    gpu_seconds: float = 0.0
    peak_gpu_memory_mb: int = 0
    concurrent_tasks: int = 0
    storage_used_gb: float = 0.0
    period_start: datetime = field(default_factory=datetime.utcnow)

    def reset(self) -> None:
        """Reset usage counters."""
        self.tasks_submitted = 0
        self.gpu_seconds = 0.0
        self.concurrent_tasks = 0
        self.storage_used_gb = 0.0
        self.period_start = datetime.utcnow()


class AccessControl:
    """Access control and quota enforcement."""

    def __init__(
        self,
        default_quota: Optional[Quota] = None,
        period_hours: int = 24,
    ):
        self._default_quota = default_quota or Quota()
        self._period_hours = period_hours

        self._quotas: dict[str, Quota] = {}
        self._usage: dict[str, ResourceUsage] = {}
        self._lock = threading.RLock()

    def get_quota(self, user_id: str) -> Quota:
        """Get quota for user."""
        with self._lock:
            return self._quotas.get(user_id, self._default_quota)

    def set_quota(self, user_id: str, quota: Quota) -> None:
        """Set quota for user."""
        with self._lock:
            self._quotas[user_id] = quota

    def get_usage(self, user_id: str) -> ResourceUsage:
        """Get current usage for user."""
        with self._lock:
            usage = self._usage.get(user_id)
            if usage and self._is_period_expired(usage):
                usage.reset()
            return usage or ResourceUsage()

    def check_task_submission(self, user_id: str, task: Task) -> tuple[bool, str]:
        """Check if user can submit a task."""
        with self._lock:
            usage = self.get_usage(user_id)
            quota = self.get_quota(user_id)

            if usage.tasks_submitted >= quota.max_tasks:
                return False, f"Task limit reached: {quota.max_tasks} tasks per {self._period_hours}h"

            if usage.concurrent_tasks >= quota.max_concurrent_tasks:
                return False, f"Concurrent task limit reached: {quota.max_concurrent_tasks}"

            if task.resources.gpu_memory_mb > quota.max_gpu_memory_mb:
                return False, f"Memory request exceeds limit: {quota.max_gpu_memory_mb}MB"

            return True, "OK"

    def record_task_start(self, user_id: str, gpu_memory_mb: int) -> None:
        """Record task start for usage tracking."""
        with self._lock:
            if user_id not in self._usage:
                self._usage[user_id] = ResourceUsage()

            usage = self._usage[user_id]
            if self._is_period_expired(usage):
                usage.reset()

            usage.tasks_submitted += 1
            usage.concurrent_tasks += 1
            usage.peak_gpu_memory_mb = max(usage.peak_gpu_memory_mb, gpu_memory_mb)

    def record_task_end(
        self,
        user_id: str,
        execution_seconds: float,
    ) -> None:
        """Record task end for usage tracking."""
        with self._lock:
            if user_id in self._usage:
                usage = self._usage[user_id]
                usage.concurrent_tasks = max(0, usage.concurrent_tasks - 1)
                usage.gpu_seconds += execution_seconds

    def record_storage(self, user_id: str, size_gb: float) -> None:
        """Record storage usage."""
        with self._lock:
            if user_id not in self._usage:
                self._usage[user_id] = ResourceUsage()
            self._usage[user_id].storage_used_gb = size_gb

    def _is_period_expired(self, usage: ResourceUsage) -> bool:
        """Check if usage period has expired."""
        return datetime.utcnow() > usage.period_start + timedelta(hours=self._period_hours)

    def get_remaining_quota(self, user_id: str) -> dict[str, float]:
        """Get remaining quota for user."""
        with self._lock:
            usage = self.get_usage(user_id)
            quota = self.get_quota(user_id)

            period_elapsed = min(
                (datetime.utcnow() - usage.period_start).total_seconds() / 3600,
                self._period_hours
            )

            return {
                "tasks_remaining": max(0, quota.max_tasks - usage.tasks_submitted),
                "gpu_hours_remaining": max(0, quota.max_gpu_hours - (usage.gpu_seconds / 3600)),
                "concurrent_tasks_remaining": max(0, quota.max_concurrent_tasks - usage.concurrent_tasks),
                "gpu_memory_remaining_mb": max(0, quota.max_gpu_memory_mb - usage.peak_gpu_memory_mb),
                "storage_remaining_gb": max(0, quota.max_storage_gb - usage.storage_used_gb),
                "period_hours_remaining": max(0, self._period_hours - period_elapsed),
            }

    def check_access(
        self,
        user_id: str,
        resource: ResourceType,
        amount: float,
    ) -> tuple[bool, str]:
        """Check if user has access to a resource."""
        remaining = self.get_remaining_quota(user_id)

        resource_map = {
            ResourceType.TASKS: "tasks_remaining",
            ResourceType.GPU_HOURS: "gpu_hours_remaining",
            ResourceType.CONCURRENT_TASKS: "concurrent_tasks_remaining",
            ResourceType.GPU_MEMORY: "gpu_memory_remaining_mb",
            ResourceType.STORAGE_GB: "storage_remaining_gb",
        }

        key = resource_map.get(resource)
        if key:
            available = remaining.get(key, 0)
            if available >= amount:
                return True, "OK"
            return False, f"Insufficient {resource.value}: need {amount}, have {available}"

        return False, f"Unknown resource: {resource}"

    def reset_usage(self, user_id: str) -> None:
        """Reset usage for user (admin only)."""
        with self._lock:
            if user_id in self._usage:
                self._usage[user_id].reset()
