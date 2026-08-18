"""Phase 19.4 MLX / mixed-hardware path tests."""

from __future__ import annotations

import pytest

from deepiri_zepgpu.training.integrity import ReplayGuard, accept_outer_update
from deepiri_zepgpu.training.mlx_worker import (
    HOMOGENEOUS_QUANTIZATION_NOTE,
    build_neutral_update_from_mlx,
    export_simulated_mlx_adapter,
    mlx_available,
)


@pytest.mark.unit
def test_simulated_mlx_produces_acceptable_neutral_update() -> None:
    export = export_simulated_mlx_adapter(rank=2, hidden=4)
    update, mac, payload = build_neutral_update_from_mlx(
        export,
        room_id="room",
        run_id="run",
        worker_id="mlx-w0",
        round_number=1,
        room_mac_key="secret",
    )
    assert update.quantization == "none"
    assert len(update.parameter_names) == 2
    accept_outer_update(
        update, payload, room_mac_key="secret", mac_hex=mac, replay_guard=ReplayGuard()
    )
    assert "quantization" in HOMOGENEOUS_QUANTIZATION_NOTE.lower()


@pytest.mark.unit
def test_mlx_available_is_boolean() -> None:
    assert isinstance(mlx_available(), bool)
