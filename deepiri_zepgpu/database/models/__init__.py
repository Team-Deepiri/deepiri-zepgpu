"""Database models initialization."""

from deepiri_zepgpu.database.models.base import Base
from deepiri_zepgpu.database.models.user import User
from deepiri_zepgpu.database.models.task import Task
from deepiri_zepgpu.database.models.pipeline import Pipeline
from deepiri_zepgpu.database.models.gpu_device import GPUDevice, GPUState, GPUType
from deepiri_zepgpu.database.models.audit_log import AuditLog
from deepiri_zepgpu.database.models.user_quota import UserQuota
from deepiri_zepgpu.database.models.scheduled_task import ScheduledTask, ScheduleStatus, ScheduleType
from deepiri_zepgpu.database.models.scheduled_task_run import ScheduledTaskRun, ScheduleRunStatus
from deepiri_zepgpu.database.models.gang_scheduling import GangTask, GangStatus, PreemptionRecord, FairShareBucket
from deepiri_zepgpu.database.models.namespace import (
    Namespace,
    NamespaceStatus,
    NamespaceMember,
    TeamRole,
    Team,
    TeamMember,
    NamespaceQuota,
    NamespaceUsage,
)

__all__ = [
    "Base",
    "User",
    "Task",
    "Pipeline",
    "GPUDevice",
    "GPUState",
    "GPUType",
    "AuditLog",
    "UserQuota",
    "ScheduledTask",
    "ScheduledTaskRun",
    "ScheduleStatus",
    "ScheduleType",
    "ScheduleRunStatus",
    "GangTask",
    "GangStatus",
    "PreemptionRecord",
    "FairShareBucket",
    "Namespace",
    "NamespaceStatus",
    "NamespaceMember",
    "TeamRole",
    "Team",
    "TeamMember",
    "NamespaceQuota",
    "NamespaceUsage",
]
