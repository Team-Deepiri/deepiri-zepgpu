from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import deepiri_zepgpu.training.runner as runner
from deepiri_zepgpu.training.config import AdapterMode, Precision, TrainingRunConfig


def _fake_torch(*, available: bool, count: int = 0) -> Any:
    selected: list[Any] = []

    def device(value: str) -> Any:
        device_type, _, raw_index = value.partition(":")
        return SimpleNamespace(
            type=device_type,
            index=int(raw_index) if raw_index else None,
        )

    return SimpleNamespace(
        device=device,
        cuda=SimpleNamespace(
            is_available=lambda: available,
            device_count=lambda: count,
            set_device=selected.append,
        ),
        selected=selected,
    )


def test_training_device_defaults_to_cuda_zero_and_accepts_explicit_cuda_zero() -> None:
    assert TrainingRunConfig().device == "cuda:0"
    assert TrainingRunConfig(device="cuda:0").device == "cuda:0"


@pytest.mark.parametrize("device", ["cuda", "cuda:-1", "cuda:abc", "mps", "gpu:0"])
def test_invalid_training_device_is_rejected(device: str) -> None:
    with pytest.raises(ValidationError):
        TrainingRunConfig(device=device)


def test_cuda_unavailable_has_clear_error() -> None:
    with pytest.raises(RuntimeError, match="CUDA.*requested.*unavailable"):
        runner._resolve_device(TrainingRunConfig(), _fake_torch(available=False))


def test_unavailable_cuda_index_is_rejected() -> None:
    with pytest.raises(ValueError, match="index 2 is unavailable.*found 1"):
        runner._resolve_device(
            TrainingRunConfig(device="cuda:2"), _fake_torch(available=True, count=1)
        )


def test_cpu_device_resolves_without_selecting_cuda() -> None:
    torch = _fake_torch(available=False)
    device = runner._resolve_device(
        TrainingRunConfig(device="cpu", precision=Precision.FP32), torch
    )
    assert device.type == "cpu"
    assert torch.selected == []


def test_cpu_accumulation_moves_inputs_and_labels_consistently() -> None:
    torch = pytest.importorskip("torch")
    seen_devices: list[tuple[str, str, str]] = []

    class Model:
        def __call__(self, *, input_ids: Any, attention_mask: Any, labels: Any) -> Any:
            seen_devices.append(
                (input_ids.device.type, attention_mask.device.type, labels.device.type)
            )
            loss = input_ids.float().sum() * 0 + torch.tensor(1.0, requires_grad=True)
            return SimpleNamespace(loss=loss)

    config = TrainingRunConfig(
        device="cpu",
        precision=Precision.FP32,
        batch_size=1,
        gradient_accumulation_steps=1,
    )
    encoded = {
        "input_ids": torch.tensor([[1, 2, 0], [3, 4, 5]]),
        "attention_mask": torch.tensor([[1, 1, 0], [1, 1, 1]]),
    }
    tokens, samples, losses = runner._accumulate_step(
        config, Model(), encoded, ["one", "two"], 1, torch.device("cpu")
    )
    assert (tokens, samples) == (2, 1)
    assert losses == [1.0]
    assert seen_devices == [("cpu", "cpu", "cpu")]


def test_qlora_keeps_transformers_device_map() -> None:
    torch = pytest.importorskip("torch")
    transformers = SimpleNamespace(
        __version__="5.0.0",
        BitsAndBytesConfig=lambda **kwargs: kwargs,
    )
    config = TrainingRunConfig(adapter_mode=AdapterMode.QLORA, device="cuda:0")
    kwargs = runner._model_load_kwargs(
        config, torch, transformers, torch.float16, torch.device("cuda:0")
    )
    assert kwargs["device_map"] == {"": 0}
    assert kwargs["quantization_config"]["load_in_4bit"] is True


def test_nvml_unavailable_reports_no_utilization(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(runner, "import_module", unavailable)
    assert runner._gpu_utilization() is None
