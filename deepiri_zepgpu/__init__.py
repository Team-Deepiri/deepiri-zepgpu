"""DeepIRI ZepGPU - Serverless GPU Framework for Kernel-as-a-Service Computing.

A modular framework for submitting, scheduling, and executing GPU compute tasks
like serverless functions. Supports deep learning, scientific computation,
and simulation workloads.
"""

__version__ = "0.1.0"
__author__ = "DeepIRI Team"

from deepiri_zepgpu.core.task import Task, TaskStatus, TaskResult
from deepiri_zepgpu.core.gpu_manager import GPUManager, GPUDevice
from deepiri_zepgpu.api.submit import submit_task, TaskSubmitter

__all__ = [
    "Task",
    "TaskStatus",
    "TaskResult",
    "GPUManager",
    "GPUDevice",
    "submit_task",
    "TaskSubmitter",
]
