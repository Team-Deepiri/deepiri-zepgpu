"""Task definitions and status tracking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
import cloudpickle


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority(Enum):
    """Task priority levels."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4
    CRITICAL = 5


@dataclass
class TaskResources:
    """GPU/CPU resource requirements for a task."""
    gpu_memory_mb: int = 1024
    cpu_cores: int = 1
    timeout_seconds: int = 3600
    gpu_type: Optional[str] = None
    allow_fallback_cpu: bool = True


@dataclass
class Task:
    """Represents a GPU compute task."""
    func: Callable[..., Any]
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    resources: TaskResources = field(default_factory=TaskResources)
    priority: TaskPriority = TaskPriority.NORMAL
    user_id: Optional[str] = None
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    gpu_device_id: Optional[int] = None
    container_id: Optional[str] = None
    callback_url: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.name is None:
            self.name = f"task_{self.task_id[:8]}"

    def serialize_func(self) -> bytes:
        """Serialize the task function using cloudpickle."""
        return cloudpickle.dumps(self.func)

    @classmethod
    def deserialize_func(cls, serialized: bytes) -> Callable[..., Any]:
        """Deserialize a task function."""
        return cloudpickle.loads(serialized)

    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary representation."""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "user_id": self.user_id,
            "status": self.status.value,
            "priority": self.priority.name,
            "resources": {
                "gpu_memory_mb": self.resources.gpu_memory_mb,
                "cpu_cores": self.resources.cpu_cores,
                "timeout_seconds": self.resources.timeout_seconds,
                "gpu_type": self.resources.gpu_type,
                "allow_fallback_cpu": self.resources.allow_fallback_cpu,
            },
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "gpu_device_id": self.gpu_device_id,
            "error": self.error,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        """Create task from dictionary representation."""
        resources = TaskResources(**data.get("resources", {}))
        return cls(
            func=lambda: None,
            task_id=data.get("task_id", str(uuid.uuid4())),
            name=data.get("name"),
            user_id=data.get("user_id"),
            status=TaskStatus(data.get("status", "pending")),
            priority=TaskPriority[data.get("priority", "NORMAL")],
            resources=resources,
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            gpu_device_id=data.get("gpu_device_id"),
            tags=data.get("tags", []),
        )


@dataclass
class TaskResult:
    """Result from a completed task."""
    task_id: str
    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_seconds: float = 0.0
    gpu_memory_used_mb: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "execution_time_seconds": self.execution_time_seconds,
            "gpu_memory_used_mb": self.gpu_memory_used_mb,
            "metadata": self.metadata,
        }
