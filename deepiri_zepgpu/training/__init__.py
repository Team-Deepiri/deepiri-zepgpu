"""Training package placeholder (Phase 15+).

This package must never import or invoke the legacy pickle TaskRouter
(`deepiri_zepgpu.vpn.task_router`). Training workloads use dial-out
node-task assignment and a future binary data plane.
"""

from __future__ import annotations

__all__: list[str] = []


def _probe_legacy_router_guard() -> None:
    """Test helper: calling this from the training package must raise."""

    from deepiri_zepgpu.vpn.legacy_router_guard import assert_not_called_from_training

    assert_not_called_from_training()
