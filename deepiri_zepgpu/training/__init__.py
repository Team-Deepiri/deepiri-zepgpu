"""Training harness and distributed training data-plane primitives.

This package intentionally does not import the legacy task router or optional ML
libraries at module import time.

Training workloads must never import or invoke the legacy pickle TaskRouter
(`deepiri_zepgpu.vpn.task_router`). Use dial-out node-task assignment and the
binary data plane instead.
"""

from __future__ import annotations

from deepiri_zepgpu.training.config import TrainingRunConfig
from deepiri_zepgpu.training.metrics import TrainingMetrics

__all__ = ["TrainingMetrics", "TrainingRunConfig"]


def _probe_legacy_router_guard() -> None:
    """Test helper: calling this from the training package must raise."""

    from deepiri_zepgpu.vpn.legacy_router_guard import assert_not_called_from_training

    assert_not_called_from_training()
