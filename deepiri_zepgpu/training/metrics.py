"""Training performance metric aggregation and reporting."""

from __future__ import annotations

import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def communication_to_compute_ratio(sync_seconds: float, compute_seconds: float) -> float:
    if sync_seconds < 0 or compute_seconds < 0:
        raise ValueError("timings cannot be negative")
    return sync_seconds / compute_seconds if compute_seconds else 0.0


class StepMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = Field(ge=1)
    tokens: int = Field(ge=0)
    samples: int = Field(ge=0)
    step_seconds: float = Field(ge=0)
    compute_seconds: float = Field(ge=0)
    sync_seconds: float = Field(default=0, ge=0)
    bytes_sent: int = Field(default=0, ge=0)
    bytes_received: int = Field(default=0, ge=0)
    loss: float | None = None
    gpu_utilization_percent: float | None = Field(default=None, ge=0, le=100)


class TrainingMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_id: str
    started_at: datetime
    completed_at: datetime
    model: str
    dataset: str
    adapter_mode: str
    precision: str
    batch_size: int
    sequence_length: int
    gradient_accumulation_steps: int
    software_versions: dict[str, str] = Field(default_factory=dict)
    hardware: dict[str, Any] = Field(default_factory=dict)
    steps: list[StepMetric]
    peak_allocated_vram_bytes: int = Field(default=0, ge=0)
    peak_reserved_vram_bytes: int = Field(default=0, ge=0)
    artifact_ref: str | None = None
    total_tokens: int = 0
    total_samples: int = 0
    total_step_seconds: float = 0
    useful_compute_seconds: float = 0
    sync_seconds: float = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    tokens_per_second: float = 0
    samples_per_second: float = 0
    communication_compute_ratio: float = 0
    mean_gpu_utilization_percent: float | None = None

    @model_validator(mode="after")
    def derive_aggregate_metrics(self) -> TrainingMetrics:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        if any(step.compute_seconds > step.step_seconds for step in self.steps):
            raise ValueError("useful compute time cannot exceed step time")
        self.total_tokens = sum(step.tokens for step in self.steps)
        self.total_samples = sum(step.samples for step in self.steps)
        self.total_step_seconds = sum(step.step_seconds for step in self.steps)
        self.useful_compute_seconds = sum(step.compute_seconds for step in self.steps)
        self.sync_seconds = sum(step.sync_seconds for step in self.steps)
        self.bytes_sent = sum(step.bytes_sent for step in self.steps)
        self.bytes_received = sum(step.bytes_received for step in self.steps)
        self.tokens_per_second = (
            self.total_tokens / self.total_step_seconds if self.total_step_seconds else 0.0
        )
        self.samples_per_second = (
            self.total_samples / self.total_step_seconds if self.total_step_seconds else 0.0
        )
        self.communication_compute_ratio = communication_to_compute_ratio(
            self.sync_seconds, self.useful_compute_seconds
        )
        values = [
            step.gpu_utilization_percent
            for step in self.steps
            if step.gpu_utilization_percent is not None
        ]
        self.mean_gpu_utilization_percent = sum(values) / len(values) if values else None
        return self

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    def summary(self) -> str:
        gpu = (
            f"{self.mean_gpu_utilization_percent:.1f}%"
            if self.mean_gpu_utilization_percent is not None
            else "unavailable"
        )
        return "\n".join(
            [
                f"Run: {self.run_id} ({self.adapter_mode}, {self.precision})",
                f"Throughput: {self.tokens_per_second:.2f} tokens/s, {self.samples_per_second:.2f} samples/s",
                f"Time: {self.total_step_seconds:.3f}s step, {self.useful_compute_seconds:.3f}s compute, {self.sync_seconds:.3f}s sync",
                f"Communication: {self.bytes_sent} B sent, {self.bytes_received} B received, ratio {self.communication_compute_ratio:.6f}",
                f"VRAM peak: {self.peak_allocated_vram_bytes} B allocated, {self.peak_reserved_vram_bytes} B reserved",
                f"Mean GPU utilization: {gpu}",
                f"Artifact: {self.artifact_ref or 'none'}",
            ]
        )


def runtime_versions(packages: dict[str, Any]) -> dict[str, str]:
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for name, module in packages.items():
        versions[name] = str(getattr(module, "__version__", "unknown"))
    return versions


def new_metrics(**kwargs: Any) -> TrainingMetrics:
    now = datetime.now(UTC)
    return TrainingMetrics(started_at=now, completed_at=now, **kwargs)


def load_metrics(path: Path) -> TrainingMetrics:
    return TrainingMetrics.model_validate(json.loads(path.read_text(encoding="utf-8")))
