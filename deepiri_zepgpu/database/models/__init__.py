"""Database models initialization."""

from deepiri_zepgpu.database.models.audit_log import AuditLog
from deepiri_zepgpu.database.models.base import Base
from deepiri_zepgpu.database.models.gang_scheduling import (
    FairShareBucket,
    GangStatus,
    GangTask,
    PreemptionRecord,
)
from deepiri_zepgpu.database.models.gpu_device import GPUDevice, GPUState, GPUType
from deepiri_zepgpu.database.models.ledger import (
    LedgerBalance,
    LedgerBlock,
    LedgerBridgeReceipt,
    LedgerTransaction,
    LedgerTxType,
    LedgerValidator,
)
from deepiri_zepgpu.database.models.namespace import (
    Namespace,
    NamespaceMember,
    NamespaceQuota,
    NamespaceStatus,
    NamespaceUsage,
    Team,
    TeamMember,
    TeamRole,
)
from deepiri_zepgpu.database.models.node_task_assignment import (
    NodeAssignmentStatus,
    NodeTaskAssignment,
    NodeTaskEvent,
)
from deepiri_zepgpu.database.models.pipeline import Pipeline
from deepiri_zepgpu.database.models.scheduled_task import (
    ScheduledTask,
    ScheduleStatus,
    ScheduleType,
)
from deepiri_zepgpu.database.models.scheduled_task_run import ScheduledTaskRun, ScheduleRunStatus
from deepiri_zepgpu.database.models.task import Task, TaskStatus
from deepiri_zepgpu.database.models.user import User
from deepiri_zepgpu.database.models.user_quota import UserQuota
from deepiri_zepgpu.database.models.vpn_models import (
    Friendship,
    FriendshipStatus,
    GpuShare,
    GpuShareQuota,
    GpuShareState,
    Peer,
    PeerOnlineStatus,
    VpnInvite,
    VpnNetwork,
)

__all__ = [
    "Base",
    "User",
    "Task",
    "TaskStatus",
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
    "VpnNetwork",
    "Peer",
    "GpuShare",
    "Friendship",
    "FriendshipStatus",
    "VpnInvite",
    "GpuShareQuota",
    "PeerOnlineStatus",
    "GpuShareState",
    "LedgerValidator",
    "LedgerBlock",
    "LedgerTransaction",
    "LedgerBalance",
    "LedgerTxType",
    "LedgerBridgeReceipt",
    "NodeTaskAssignment",
    "NodeTaskEvent",
    "NodeAssignmentStatus",
]
