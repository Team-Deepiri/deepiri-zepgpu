"""Unit tests for Phase 19 training Prometheus helpers."""

from __future__ import annotations

import pytest

from deepiri_zepgpu.training import prom_metrics as pm


@pytest.mark.unit
def test_prom_metric_recorders_do_not_raise() -> None:
    pm.record_sync_round(room_id="r1", path_type="direct", result="ok", nbytes=128)
    pm.record_sync_round(room_id="r1", path_type="relay", result="ok", nbytes=64)
    pm.record_checkpoint(room_id="r1", operation="save", result="ok")
    pm.record_checkpoint(room_id="r1", operation="load", result="corrupt")
    pm.record_training_failure(room_id="r1", cause="worker_crash")
    pm.record_rejoin(room_id="r1", result="ok")
    pm.set_active_runs(state="running", count=2)
