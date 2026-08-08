"""Versioned, secret-safe configuration for local and WAN adapter training."""

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


class CompressorBackend(str, Enum):
    NONE = "none"
    ZEP = "zep"
    DEMO = "demo"


class DirectBackend(str, Enum):
    MEMORY = "memory"
    LAN = "lan"
    PCCL = "pccl"


class RuntimeMode(str, Enum):
    PROCESS = "process"
    DOCKER = "docker"


class OverlapMode(str, Enum):
    BLOCKING = "blocking"
    EAGER = "eager"


class DistributedStrategy(str, Enum):
    """Execution strategy for a schema-v3 training job."""

    SINGLE = "single"
    DILOCO = "diloco"
    FSDP2 = "fsdp2"
    TENSOR_PARALLEL = "tensor_parallel"


class NetworkScope(str, Enum):
    SAME_HOST = "same_host"
    LAN = "lan"
    WAN = "wan"


class ResumePolicy(str, Enum):
    NEVER = "never"
    LATEST = "latest"
    REQUIRED = "required"


class OuterOptimizerKind(str, Enum):
    SGD = "sgd"
    ADAM = "adam"


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


class CompressionConfig(BaseModel):
    """Switchable compressed-update backends for Phase 17 WAN sync."""

    model_config = ConfigDict(extra="forbid")

    backend: CompressorBackend = CompressorBackend.ZEP
    top_k: int = Field(default=32, ge=1, le=65536)
    chunk_size: int = Field(default=64, ge=8, le=4096)
    quant_bits: int = Field(default=4, ge=2, le=8)
    error_feedback: bool = True


class RuntimeConfig(BaseModel):
    """Training workload runtime: process for tests, docker for production."""

    model_config = ConfigDict(extra="forbid")

    mode: RuntimeMode = RuntimeMode.PROCESS
    image: str = Field(default="zepgpu-training:local", min_length=1, max_length=512)
    privileged: bool = False
    network_enabled: bool = True
    memory_limit_mb: int = Field(default=8192, ge=256, le=1_048_576)
    cpu_limit: float = Field(default=4.0, gt=0, le=256)
    timeout_seconds: int = Field(default=3600, ge=30, le=86400)
    gpu_devices: list[int] = Field(default_factory=lambda: [0])
    environment: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_security(self) -> RuntimeConfig:
        if self.privileged:
            raise ValueError("privileged containers are disabled by default and not allowed")
        return self


class RuntimeRequirements(BaseModel):
    """Reported provider capabilities required by a Phase 18 placement."""

    model_config = ConfigDict(extra="forbid")

    requires_cuda: bool = True
    cuda_version: str | None = Field(default=None, max_length=64)
    pytorch_version: str | None = Field(default=None, max_length=64)
    nccl_version: str | None = Field(default=None, max_length=64)
    compute_capability: str | None = Field(default=None, max_length=32)
    requires_p2p: bool = False
    requires_nvlink: bool = False
    requires_fsdp2: bool = False
    requires_tensor_parallel: bool = False
    minimum_bandwidth_mbps: float | None = Field(default=None, gt=0)
    maximum_rtt_ms: float | None = Field(default=None, gt=0)


class OuterOptimizerConfig(BaseModel):
    """Small, deterministic outer optimizer used by DiLoCo/local-SGD."""

    model_config = ConfigDict(extra="forbid")

    kind: OuterOptimizerKind = OuterOptimizerKind.SGD
    learning_rate: float = Field(default=1.0, gt=0)
    momentum: float = Field(default=0.0, ge=0, lt=1)
    beta1: float = Field(default=0.9, ge=0, lt=1)
    beta2: float = Field(default=0.999, ge=0, lt=1)
    epsilon: float = Field(default=1e-8, gt=0)


class Phase18TrainingConfig(BaseModel):
    """First-class elastic/topology-aware training job specification."""

    model_config = ConfigDict(extra="forbid")

    strategy: DistributedStrategy = DistributedStrategy.DILOCO
    requested_node_count: int = Field(default=2, ge=1, le=256)
    gpus_per_node: int = Field(default=1, ge=1, le=64)
    total_gpus: int = Field(default=2, ge=1, le=4096)
    minimum_vram_per_gpu_mb: int = Field(default=1024, ge=1)
    diloco_h: int = Field(default=1, ge=1, le=1_000_000)
    min_k: int = Field(default=2, ge=1, le=256)
    sync_deadline_seconds: float = Field(default=120.0, gt=0, le=86400)
    readiness_timeout_seconds: int = Field(default=300, ge=1, le=86400)
    startup_timeout_seconds: int = Field(default=300, ge=1, le=86400)
    checkpoint_interval_rounds: int = Field(default=1, ge=1, le=100_000)
    maximum_runtime_seconds: int = Field(default=3600, ge=30, le=604800)
    reservation_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    resume_policy: ResumePolicy = ResumePolicy.LATEST
    network_scope: NetworkScope | None = None
    runtime_requirements: RuntimeRequirements = Field(default_factory=RuntimeRequirements)
    outer_optimizer: OuterOptimizerConfig = Field(default_factory=OuterOptimizerConfig)

    @model_validator(mode="after")
    def validate_job(self) -> Phase18TrainingConfig:  # noqa: C901
        expected_total = self.requested_node_count * self.gpus_per_node
        if self.total_gpus != expected_total:
            raise ValueError(
                "total_gpus must equal requested_node_count * gpus_per_node " f"({expected_total})"
            )
        if self.min_k > self.requested_node_count:
            raise ValueError("min_k cannot exceed requested_node_count")
        if self.strategy == DistributedStrategy.SINGLE:
            if self.requested_node_count != 1 or self.total_gpus != 1:
                raise ValueError("strategy='single' requires exactly one node and one GPU")
            if self.min_k != 1:
                raise ValueError("strategy='single' requires min_k=1")
        if self.strategy in {
            DistributedStrategy.FSDP2,
            DistributedStrategy.TENSOR_PARALLEL,
        }:
            if self.network_scope == NetworkScope.WAN:
                raise ValueError(f"strategy='{self.strategy.value}' cannot span WAN links")
            if self.network_scope is None:
                self.network_scope = NetworkScope.SAME_HOST
            self.runtime_requirements.requires_cuda = True
            self.runtime_requirements.requires_p2p = True
            if self.strategy == DistributedStrategy.FSDP2:
                self.runtime_requirements.requires_fsdp2 = True
            else:
                self.runtime_requirements.requires_tensor_parallel = True
        elif self.network_scope is None:
            self.network_scope = NetworkScope.WAN
        return self


class DistributedTrainingConfig(BaseModel):
    """WAN synchronization settings (two workers in schema v2; elastic in v3)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    worker_count: int = Field(default=2, ge=1, le=256)
    local_steps_per_round: int = Field(default=1, ge=1, le=10_000)
    max_rounds: int = Field(default=2, ge=1, le=10_000)
    compression: CompressionConfig = Field(default_factory=CompressionConfig)
    direct_backend: DirectBackend = DirectBackend.MEMORY
    overlap_mode: OverlapMode = OverlapMode.BLOCKING
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    worker_seed_offset: int = Field(default=1, ge=0, le=1_000_000)


class TrainingRunConfig(BaseModel):
    """Stable serialized contract for a local or distributed training run."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2, 3] = 1
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
    distributed: DistributedTrainingConfig = Field(default_factory=DistributedTrainingConfig)
    phase18: Phase18TrainingConfig | None = None

    @model_validator(mode="after")
    def validate_quantization(self) -> TrainingRunConfig:  # noqa: C901
        if self.adapter_mode == AdapterMode.QLORA and not self.load_in_4bit:
            self.load_in_4bit = True
        if self.load_in_4bit and self.adapter_mode != AdapterMode.QLORA:
            raise ValueError("4-bit base loading requires adapter_mode='qlora'")
        if self.phase18 is not None:
            self.schema_version = 3
            self.distributed.enabled = True
            self.distributed.worker_count = self.phase18.requested_node_count
            self.distributed.local_steps_per_round = self.phase18.diloco_h
            self.startup_timeout_seconds = self.phase18.startup_timeout_seconds
            if (
                self.precision == Precision.FP16
                and not self.phase18.runtime_requirements.requires_cuda
            ):
                raise ValueError("fp16 Phase 18 training requires CUDA")
            if (
                self.adapter_mode == AdapterMode.QLORA
                and not self.phase18.runtime_requirements.requires_cuda
            ):
                raise ValueError("QLoRA Phase 18 training requires CUDA")
        elif self.schema_version == 3:
            raise ValueError("schema_version=3 requires a phase18 training specification")
        elif self.distributed.enabled:
            if self.distributed.worker_count != 2:
                raise ValueError("Phase 17 supports exactly two workers")
            if self.schema_version < 2:
                self.schema_version = 2
        if self.distributed.enabled:
            total_steps = self.distributed.local_steps_per_round * self.distributed.max_rounds
            self.max_steps = total_steps
        if self.smoke_run:
            self.max_steps = min(self.max_steps, 2)
            self.checkpoint_every_steps = min(self.checkpoint_every_steps, self.max_steps)
            self.sequence_length = min(self.sequence_length, 64)
            if self.distributed.enabled:
                self.distributed.max_rounds = min(self.distributed.max_rounds, 2)
                self.distributed.local_steps_per_round = min(
                    self.distributed.local_steps_per_round, 1
                )
                if self.phase18 is not None:
                    self.phase18.diloco_h = self.distributed.local_steps_per_round
                self.max_steps = (
                    self.distributed.local_steps_per_round * self.distributed.max_rounds
                )
            # Default smoke model is GPT-2-style Conv1D; peft warns unless this is True.
            if "gpt2" in self.model_name.lower():
                self.lora.fan_in_fan_out = True
        return self

    @classmethod
    def from_json_file(cls, path: Path) -> TrainingRunConfig:
        return cls.model_validate_json(path.read_text(encoding="utf-8-sig"))

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_public_dict(), indent=2), encoding="utf-8")

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize config for disk/logs with credentials and runtime env removed."""
        payload = filter_secrets(self.model_dump(mode="json"))
        assert isinstance(payload, dict)
        distributed = payload.get("distributed")
        if isinstance(distributed, dict):
            runtime = distributed.get("runtime")
            if isinstance(runtime, dict):
                # Env may hold opaque secrets under non-matching key names.
                runtime["environment"] = {}
        return payload

    def codec_id(self) -> str:
        backend = self.distributed.compression.backend
        if backend == CompressorBackend.NONE:
            return "none"
        if backend == CompressorBackend.ZEP:
            return "zep-v1"
        if backend == CompressorBackend.DEMO:
            return "demo-v1"
        raise ValueError(f"unsupported compressor backend: {backend}")


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
