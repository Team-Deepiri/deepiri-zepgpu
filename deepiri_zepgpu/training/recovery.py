"""Phase 19 durable checkpoint recovery helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from deepiri_zepgpu.training.checkpoint import Phase18CheckpointMetadata


class CheckpointCorruptionError(ValueError):
    """Raised when a checkpoint is partial, truncated, or fails integrity checks."""


def checkpoint_sidecar_path(directory: Path) -> Path:
    return directory / "checkpoint.sha256"


def write_checkpoint_json_sidecar(directory: Path) -> Path | None:
    """Hash checkpoint.json for any schema (Phase 17 process worker included)."""
    path = directory / "checkpoint.json"
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = checkpoint_sidecar_path(directory)
    sidecar.write_text(digest + "\n", encoding="utf-8")
    return sidecar


def write_checkpoint_integrity(directory: Path, metadata: Phase18CheckpointMetadata) -> Path:
    """Write metadata + SHA-256 sidecar for durable recovery verification."""
    path = metadata.save(directory)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = checkpoint_sidecar_path(directory)
    sidecar.write_text(digest + "\n", encoding="utf-8")
    return path


def load_verified_checkpoint(directory: Path) -> Phase18CheckpointMetadata:
    """Load Phase 18+ checkpoint and reject missing/corrupt/partial files."""
    path = directory / "checkpoint.json"
    sidecar = checkpoint_sidecar_path(directory)
    if not path.exists():
        raise CheckpointCorruptionError("checkpoint.json missing")
    if not sidecar.exists():
        raise CheckpointCorruptionError("checkpoint integrity sidecar missing")
    raw = path.read_bytes()
    if not raw.strip():
        raise CheckpointCorruptionError("checkpoint.json is empty")
    expected = sidecar.read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(raw).hexdigest()
    if expected != actual:
        raise CheckpointCorruptionError("checkpoint.json checksum mismatch")
    try:
        meta = Phase18CheckpointMetadata.model_validate_json(raw.decode("utf-8"))
    except Exception as exc:
        raise CheckpointCorruptionError(f"checkpoint.json is not valid metadata: {exc}") from exc
    if meta.outer_round < 0:
        raise CheckpointCorruptionError("invalid outer_round")
    return meta


def bootstrap_late_joiner_state(
    metadata: Phase18CheckpointMetadata,
    *,
    worker_id: str,
) -> dict[str, Any]:
    """Return membership-aware bootstrap dict for a late-joining worker."""
    membership = list(metadata.active_membership)
    if worker_id not in membership:
        membership.append(worker_id)
    return {
        "run_id": metadata.run_id,
        "outer_round": metadata.outer_round,
        "step": metadata.step,
        "active_membership": membership,
        "compression_config": dict(metadata.compression_config),
        "placement": dict(metadata.placement),
        "island_ids": list(metadata.island_ids),
        "model_state": dict(metadata.model_state),
        "outer_optimizer_state": dict(metadata.outer_optimizer_state),
        "artifact_refs": list(metadata.artifact_refs),
    }


def retention_candidates(root: Path, *, keep_last: int) -> list[Path]:
    """List checkpoint directories under root older than the newest keep_last."""
    if keep_last < 1:
        raise ValueError("keep_last must be >= 1")
    if not root.exists():
        return []
    dirs = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return dirs[keep_last:]
