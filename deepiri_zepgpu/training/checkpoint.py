"""Checkpoint metadata independent from optional ML libraries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from deepiri_zepgpu.training.config import filter_secrets


class CheckpointMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    run_id: str
    step: int = Field(ge=0)
    created_at: datetime
    adapter_ref: str
    optimizer_ref: str | None = None
    config: dict[str, object]

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "checkpoint.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, directory: Path) -> CheckpointMetadata:
        return cls.model_validate_json((directory / "checkpoint.json").read_text(encoding="utf-8"))


def make_checkpoint_metadata(
    *, run_id: str, step: int, directory: Path, config: dict[str, object]
) -> CheckpointMetadata:
    return CheckpointMetadata(
        run_id=run_id,
        step=step,
        created_at=datetime.now(UTC),
        adapter_ref=str(directory / "adapter"),
        optimizer_ref=str(directory / "optimizer.pt"),
        config=filter_secrets(config),
    )


class Phase18CheckpointMetadata(CheckpointMetadata):
    """Worker-bootstrap state layered onto the existing checkpoint contract."""

    schema_version: int = 2
    outer_round: int = Field(ge=0)
    model_state: dict[str, dict[str, Any]] = Field(default_factory=dict)
    local_optimizer_refs: dict[str, str] = Field(default_factory=dict)
    outer_optimizer_state: dict[str, Any] = Field(default_factory=dict)
    active_membership: list[str] = Field(default_factory=list)
    compression_config: dict[str, Any] = Field(default_factory=dict)
    placement: dict[str, Any] = Field(default_factory=dict)
    island_ids: list[str] = Field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)


def make_phase18_checkpoint_metadata(
    *,
    run_id: str,
    step: int,
    outer_round: int,
    directory: Path,
    config: dict[str, object],
    model_state: dict[str, dict[str, Any]],
    outer_optimizer_state: dict[str, Any],
    active_membership: list[str],
    compression_config: dict[str, Any],
    placement: dict[str, Any],
    island_ids: list[str],
    artifact_refs: list[dict[str, Any]] | None = None,
    local_optimizer_refs: dict[str, str] | None = None,
) -> Phase18CheckpointMetadata:
    return Phase18CheckpointMetadata(
        run_id=run_id,
        step=step,
        outer_round=outer_round,
        created_at=datetime.now(UTC),
        adapter_ref=str(directory / "adapter"),
        optimizer_ref=str(directory / "optimizer.pt"),
        config=filter_secrets(config),
        model_state=model_state,
        local_optimizer_refs=local_optimizer_refs or {},
        outer_optimizer_state=outer_optimizer_state,
        active_membership=sorted(active_membership),
        compression_config=filter_secrets(compression_config),
        placement=filter_secrets(placement),
        island_ids=sorted(island_ids),
        artifact_refs=artifact_refs or [],
    )
