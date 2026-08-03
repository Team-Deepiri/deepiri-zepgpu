from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from deepiri_zepgpu.training.config import (
    AdapterMode,
    DatasetConfig,
    TrainingRunConfig,
    filter_secrets,
)
from deepiri_zepgpu.training.metrics import (
    StepMetric,
    TrainingMetrics,
    communication_to_compute_ratio,
)


def test_config_validation_and_qlora_defaults() -> None:
    config = TrainingRunConfig(adapter_mode=AdapterMode.QLORA)
    assert config.load_in_4bit is True
    with pytest.raises(ValidationError):
        TrainingRunConfig(load_in_4bit=True)
    with pytest.raises(ValidationError):
        TrainingRunConfig(sequence_length=2)
    assert TrainingRunConfig.model_validate({"schema_version": 2}).schema_version == 2
    with pytest.raises(ValidationError):
        TrainingRunConfig.model_validate({"schema_version": 3})
    with pytest.raises(ValidationError):
        DatasetConfig(texts=[])
    with pytest.raises(ValidationError):
        DatasetConfig(texts=["valid", "  "])


def test_smoke_run_is_bounded() -> None:
    config = TrainingRunConfig(smoke_run=True, max_steps=100, sequence_length=2048)
    assert config.max_steps == 2
    assert config.sequence_length == 64


def test_config_file_accepts_utf8_bom(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"schema_version": 1}', encoding="utf-8-sig")

    config = TrainingRunConfig.from_json_file(config_path)

    assert config.schema_version == 1


def test_secret_filter_is_recursive() -> None:
    filtered = filter_secrets({"api_token": "secret", "nested": {"password": "pw", "safe": "yes"}})
    assert filtered == {
        "api_token": "[REDACTED]",
        "nested": {"password": "[REDACTED]", "safe": "yes"},
    }


def test_public_config_dict_redacts_secrets_and_runtime_env() -> None:
    config = TrainingRunConfig(
        distributed={
            "enabled": True,
            "runtime": {"environment": {"HF_TOKEN": "hf_secret", "SAFE": "1"}},
        }
    )
    public = config.to_public_dict()
    assert public["distributed"]["runtime"]["environment"] == {}
    # Credential-like keys elsewhere are still redacted.
    leaked = filter_secrets({"run_credential": "abc", "ok": 1})
    assert leaked["run_credential"] == "[REDACTED]"
    assert leaked["ok"] == 1


def test_ratio_math_and_single_node_metrics() -> None:
    now = datetime.now(UTC)
    metrics = TrainingMetrics(
        run_id="run",
        started_at=now,
        completed_at=now,
        model="tiny",
        dataset="inline",
        adapter_mode="lora",
        precision="fp16",
        batch_size=1,
        sequence_length=64,
        gradient_accumulation_steps=2,
        steps=[
            StepMetric(
                step=1,
                tokens=100,
                samples=2,
                step_seconds=2,
                compute_seconds=2,
            )
        ],
    )
    assert metrics.tokens_per_second == 50
    assert metrics.samples_per_second == 1
    assert metrics.sync_seconds == 0
    assert metrics.blocked_sync_seconds == 0
    assert metrics.bytes_sent == 0
    assert metrics.bytes_received == 0
    assert metrics.communication_compute_ratio == 0
    assert communication_to_compute_ratio(2, 8) == 0.25
    with pytest.raises(ValueError):
        communication_to_compute_ratio(-1, 1)


def test_metric_schema_rejects_inconsistent_or_unknown_data() -> None:
    now = datetime.now(UTC)
    common = {
        "run_id": "run",
        "started_at": now,
        "completed_at": now,
        "model": "tiny",
        "dataset": "inline",
        "adapter_mode": "lora",
        "precision": "fp16",
        "batch_size": 1,
        "sequence_length": 64,
        "gradient_accumulation_steps": 1,
    }
    with pytest.raises(ValidationError):
        TrainingMetrics(
            **common,
            steps=[
                StepMetric(
                    step=1,
                    tokens=1,
                    samples=1,
                    step_seconds=1,
                    compute_seconds=2,
                )
            ],
        )
    with pytest.raises(ValidationError):
        StepMetric.model_validate(
            {
                "step": 1,
                "tokens": 1,
                "samples": 1,
                "step_seconds": 1,
                "compute_seconds": 1,
                "unknown": True,
            }
        )
