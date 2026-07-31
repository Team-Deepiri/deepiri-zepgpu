"""Training harness and distributed training data-plane primitives.

This package intentionally does not import the legacy task router or optional ML
libraries at module import time.
"""

from deepiri_zepgpu.training.config import TrainingRunConfig
from deepiri_zepgpu.training.metrics import TrainingMetrics

__all__ = ["TrainingMetrics", "TrainingRunConfig"]
