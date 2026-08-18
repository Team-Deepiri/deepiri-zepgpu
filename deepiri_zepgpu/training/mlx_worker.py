"""Experimental Apple/MLX worker path producing NeutralOuterUpdate (Phase 19.4).

NVIDIA/PyTorch remains primary. This module never imports ``mlx`` at module load;
when MLX is unavailable it still builds neutral updates from plain NumPy-like
bytes so CI can exercise the mixed-hardware schema path.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from deepiri_zepgpu.training.integrity import (
    NeutralOuterUpdate,
    payload_digest,
    sign_update,
)


class MlxUnavailableError(RuntimeError):
    """Raised when a real MLX runtime is required but not installed."""


def mlx_available() -> bool:
    try:
        importlib.import_module("mlx.core")
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class MlxAdapterExport:
    """In-memory adapter tensors exported toward the neutral outer format."""

    model_revision: str
    parameter_names: list[str]
    shapes: list[list[int]]
    dtype: str
    quantization: str
    payload: bytes


def export_simulated_mlx_adapter(
    *,
    model_revision: str = "mlx-sim-v1",
    rank: int = 4,
    hidden: int = 8,
) -> MlxAdapterExport:
    """Build a deterministic fake MLX adapter payload (no MLX install required)."""
    # Pack little-endian float32 zeros as a stand-in for adapter weights.
    numel = rank * hidden * 2
    payload = b"\x00\x00\x00\x00" * numel
    return MlxAdapterExport(
        model_revision=model_revision,
        parameter_names=["lora_A", "lora_B"],
        shapes=[[rank, hidden], [hidden, rank]],
        dtype="f32",
        quantization="none",
        payload=payload,
    )


def export_real_mlx_adapter(*, model_revision: str, tensors: dict[str, Any]) -> MlxAdapterExport:
    """Export real MLX arrays to bytes. Requires ``mlx`` installed."""
    if not mlx_available():
        raise MlxUnavailableError("mlx is not installed")
    mx = importlib.import_module("mlx.core")
    import numpy as np

    names: list[str] = []
    shapes: list[list[int]] = []
    chunks: list[bytes] = []
    for name, value in sorted(tensors.items()):
        array = np.asarray(mx.array(value), dtype=np.float32)
        names.append(name)
        shapes.append(list(array.shape))
        chunks.append(array.tobytes(order="C"))
    if not names:
        raise ValueError("tensors cannot be empty")
    return MlxAdapterExport(
        model_revision=model_revision,
        parameter_names=names,
        shapes=shapes,
        dtype="f32",
        quantization="none",
        payload=b"".join(chunks),
    )


def build_neutral_update_from_mlx(
    export: MlxAdapterExport,
    *,
    room_id: str,
    run_id: str,
    worker_id: str,
    round_number: int,
    room_mac_key: str,
) -> tuple[NeutralOuterUpdate, str, bytes]:
    """Return (update, mac_hex, payload) ready for accept_outer_update."""
    update = NeutralOuterUpdate(
        model_revision=export.model_revision,
        parameter_names=list(export.parameter_names),
        shapes=[list(shape) for shape in export.shapes],
        dtype=export.dtype,
        quantization=export.quantization,
        round=round_number,
        worker_id=worker_id,
        run_id=run_id,
        room_id=room_id,
        payload_sha256=payload_digest(export.payload),
    )
    mac = sign_update(update, room_mac_key=room_mac_key)
    return update, mac, export.payload


HOMOGENEOUS_QUANTIZATION_NOTE = (
    "Mixed NVIDIA/MLX rooms must use the same quantization label on outer updates "
    "(default: none). Heterogeneous quantization is rejected at accept_outer_update "
    "validation by requiring matching NeutralOuterUpdate.quantization across workers."
)
