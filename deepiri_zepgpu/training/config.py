"""Versioned, secret-safe configuration for local adapter training."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdapterMode(str, Enum):
    LORA = "lora"
    QLORA = "qlora"


class Precision(str, Enum):
    BF16 = "bf16"
    FP16 = "fp16"
    FP32 = "fp32"


class DatasetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="zepgpu-inline-v1", min_length=1, max_length=255)
    texts: list[str] | None = None

    @model_validator(mode="after")
    def validate_texts(self) -> DatasetConfig:
        if self.texts is not None:
            if not self.texts:
                raise ValueError("dataset texts cannot be empty")
            if any(not text.strip() for text in self.texts):
                raise ValueError("dataset texts cannot contain blank samples")
        return self


class LoraConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(default=8, ge=1, le=256)
    alpha: int = Field(default=16, ge=1)
    dropout: float = Field(default=0.05, ge=0, lt=1)
    target_modules: list[str] | None = None
    # Required True for GPT-2 / Conv1D targets; leave False for standard Linear modules.
    fan_in_fan_out: bool = False


class TrainingRunConfig(BaseModel):
    """Stable serialized contract for a local training run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_name: str = Field(default="local-baseline", min_length=1, max_length=128)
    model_name: str = Field(
        default="hf-internal-testing/tiny-random-gpt2", min_length=1, max_length=1024
    )
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    adapter_mode: AdapterMode = AdapterMode.LORA
    precision: Precision = Precision.FP16
    load_in_4bit: bool = False
    device: str = Field(default="cuda:0", pattern=r"^(?:cpu|cuda:[0-9]+)$")
    sequence_length: int = Field(default=128, ge=8, le=32768)
    batch_size: int = Field(default=1, ge=1)
    gradient_accumulation_steps: int = Field(default=4, ge=1)
    learning_rate: float = Field(default=2e-4, gt=0)
    max_steps: int = Field(default=20, ge=1)
    checkpoint_every_steps: int = Field(default=10, ge=1)
    startup_timeout_seconds: int = Field(default=300, ge=10, le=86400)
    gradient_checkpointing: bool = True
    seed: int = Field(default=42, ge=0)
    output_dir: Path = Path("artifacts/training/local-baseline")
    resume_from: Path | None = None
    smoke_run: bool = False
    lora: LoraConfig = Field(default_factory=LoraConfig)

    @model_validator(mode="after")
    def validate_quantization(self) -> TrainingRunConfig:
        if self.adapter_mode == AdapterMode.QLORA and not self.load_in_4bit:
            self.load_in_4bit = True
        if self.load_in_4bit and self.adapter_mode != AdapterMode.QLORA:
            raise ValueError("4-bit base loading requires adapter_mode='qlora'")
        if self.smoke_run:
            self.max_steps = min(self.max_steps, 2)
            self.checkpoint_every_steps = min(self.checkpoint_every_steps, self.max_steps)
            self.sequence_length = min(self.sequence_length, 64)
            # Default smoke model is GPT-2-style Conv1D; peft warns unless this is True.
            if "gpt2" in self.model_name.lower():
                self.lora.fan_in_fan_out = True
        return self

    @classmethod
    def from_json_file(cls, path: Path) -> TrainingRunConfig:
        return cls.model_validate_json(path.read_text(encoding="utf-8-sig"))

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = filter_secrets(self.model_dump(mode="json"))
        path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")


_SECRET_PARTS = ("secret", "token", "password", "private_key", "credential", "api_key")


def filter_secrets(value: Any) -> Any:
    """Recursively redact credential-like keys before persistence or logging."""
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(part in str(key).lower() for part in _SECRET_PARTS)
                else filter_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [filter_secrets(item) for item in value]
    return value
