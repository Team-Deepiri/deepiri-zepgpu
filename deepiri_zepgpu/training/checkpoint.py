"""Checkpoint metadata independent from optional ML libraries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
