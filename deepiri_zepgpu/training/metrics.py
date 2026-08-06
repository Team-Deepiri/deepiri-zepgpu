"""Training performance metric aggregation and reporting."""

from __future__ import annotations

import json
import math
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def communication_to_compute_ratio(sync_seconds: float, compute_seconds: float) -> float:
    if sync_seconds < 0 or compute_seconds < 0:
        raise ValueError("timings cannot be negative")
    return sync_seconds / compute_seconds if compute_seconds else 0.0


def is_finite_loss(loss: float | None) -> bool:
    return loss is None or (math.isfinite(loss))


class StepMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = Field(ge=1)
    tokens: int = Field(ge=0)
    samples: int = Field(ge=0)
    step_seconds: float = Field(ge=0)
    compute_seconds: float = Field(ge=0)
    sync_seconds: float = Field(default=0, ge=0)
    blocked_sync_seconds: float = Field(default=0, ge=0)
    overlapped_sync_seconds: float = Field(default=0, ge=0)
    bytes_sent: int = Field(default=0, ge=0)
    bytes_received: int = Field(default=0, ge=0)
    uncompressed_bytes: int = Field(default=0, ge=0)
    compressed_bytes: int = Field(default=0, ge=0)
    compression_ratio: float | None = Field(default=None, ge=0)
    path_type: Literal["direct", "relay", "none"] | None = None
    rtt_ms: float | None = Field(default=None, ge=0)
    bandwidth_bps: float | None = Field(default=None, ge=0)
    round: int | None = Field(default=None, ge=0)
    loss: float | None = None
    gpu_utilization_percent: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def align_sync_fields(self) -> StepMetric:
        if self.blocked_sync_seconds == 0 and self.sync_seconds > 0:
            self.blocked_sync_seconds = self.sync_seconds
        if self.sync_seconds == 0 and self.blocked_sync_seconds > 0:
            self.sync_seconds = self.blocked_sync_seconds
        if self.compression_ratio is None and self.uncompressed_bytes > 0:
            self.compression_ratio = self.compressed_bytes / self.uncompressed_bytes
        if self.loss is not None and not math.isfinite(self.loss):
            raise ValueError("loss must be finite")
        return self


class TrainingMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2] = 1
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
    blocked_sync_seconds: float = 0
    overlapped_sync_seconds: float = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    uncompressed_bytes: int = 0
    compressed_bytes: int = 0
    compression_ratio: float | None = None
    rounds: int = 0
    sync_frequency: float | None = None
    path_type: Literal["direct", "relay", "mixed", "none"] | None = None
    rtt_ms: float | None = None
    bandwidth_bps: float | None = None
    compressor_backend: str | None = None
    direct_backend: str | None = None
    tokens_per_second: float = 0
    samples_per_second: float = 0
    communication_compute_ratio: float = 0
    mean_gpu_utilization_percent: float | None = None
    final_loss: float | None = None
    mean_loss: float | None = None

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
        self.blocked_sync_seconds = sum(step.blocked_sync_seconds for step in self.steps)
        self.overlapped_sync_seconds = sum(step.overlapped_sync_seconds for step in self.steps)
        self.sync_seconds = sum(step.sync_seconds for step in self.steps)
        if self.blocked_sync_seconds == 0 and self.sync_seconds > 0:
            self.blocked_sync_seconds = self.sync_seconds
        self.bytes_sent = sum(step.bytes_sent for step in self.steps)
        self.bytes_received = sum(step.bytes_received for step in self.steps)
        self.uncompressed_bytes = sum(step.uncompressed_bytes for step in self.steps)
        self.compressed_bytes = sum(step.compressed_bytes for step in self.steps)
        if self.uncompressed_bytes > 0:
            self.compression_ratio = self.compressed_bytes / self.uncompressed_bytes
        round_ids = {step.round for step in self.steps if step.round is not None}
        self.rounds = len(round_ids)
        if self.useful_compute_seconds > 0 and self.rounds > 0:
            self.sync_frequency = self.rounds / self.useful_compute_seconds
        paths = {
            step.path_type for step in self.steps if step.path_type and step.path_type != "none"
        }
        if not paths:
            self.path_type = self.path_type or "none"
        elif len(paths) == 1:
            self.path_type = next(iter(paths))
        else:
            self.path_type = "mixed"
        rtts = [step.rtt_ms for step in self.steps if step.rtt_ms is not None]
        self.rtt_ms = sum(rtts) / len(rtts) if rtts else self.rtt_ms
        bandwidths = [step.bandwidth_bps for step in self.steps if step.bandwidth_bps is not None]
        self.bandwidth_bps = sum(bandwidths) / len(bandwidths) if bandwidths else self.bandwidth_bps
        self.tokens_per_second = (
            self.total_tokens / self.total_step_seconds if self.total_step_seconds else 0.0
        )
        self.samples_per_second = (
            self.total_samples / self.total_step_seconds if self.total_step_seconds else 0.0
        )
        # Ratio uses blocked communication only; overlapped time is excluded.
        self.communication_compute_ratio = communication_to_compute_ratio(
            self.blocked_sync_seconds, self.useful_compute_seconds
        )
        values = [
            step.gpu_utilization_percent
            for step in self.steps
            if step.gpu_utilization_percent is not None
        ]
        self.mean_gpu_utilization_percent = sum(values) / len(values) if values else None
        losses = [step.loss for step in self.steps if step.loss is not None]
        if losses:
            self.final_loss = losses[-1]
            self.mean_loss = sum(losses) / len(losses)
        if self.schema_version == 1 and (
            self.blocked_sync_seconds
            or self.overlapped_sync_seconds
            or self.uncompressed_bytes
            or self.compressor_backend
            or self.direct_backend
        ):
            self.schema_version = 2
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
        ratio = f"{self.compression_ratio:.4f}" if self.compression_ratio is not None else "n/a"
        return "\n".join(
            [
                f"Run: {self.run_id} ({self.adapter_mode}, {self.precision})",
                f"Throughput: {self.tokens_per_second:.2f} tokens/s, {self.samples_per_second:.2f} samples/s",
                (
                    f"Time: {self.total_step_seconds:.3f}s step, "
                    f"{self.useful_compute_seconds:.3f}s compute, "
                    f"{self.blocked_sync_seconds:.3f}s blocked sync, "
                    f"{self.overlapped_sync_seconds:.3f}s overlapped sync"
                ),
                (
                    f"Communication: {self.bytes_sent} B sent, {self.bytes_received} B received, "
                    f"ratio {self.communication_compute_ratio:.6f}, "
                    f"compressed {self.compressed_bytes}/{self.uncompressed_bytes} B ({ratio})"
                ),
                f"Path: {self.path_type or 'n/a'}, compressor={self.compressor_backend or 'n/a'}, "
                f"direct={self.direct_backend or 'n/a'}",
                f"Loss: final={self.final_loss}, mean={self.mean_loss}",
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
    """Load Phase 15 (v1) or Phase 17 (v2) metrics JSON."""
    return TrainingMetrics.model_validate(json.loads(path.read_text(encoding="utf-8")))


def assert_catastrophic_quality(metrics: TrainingMetrics) -> None:
    """Hard-fail only on non-finite loss; relative Phase 15 tolerance is not enforced."""
    for step in metrics.steps:
        if step.loss is not None and not math.isfinite(step.loss):
            raise ValueError(f"non-finite loss at step {step.step}: {step.loss}")
    if metrics.final_loss is not None and not math.isfinite(metrics.final_loss):
        raise ValueError(f"non-finite final_loss: {metrics.final_loss}")
