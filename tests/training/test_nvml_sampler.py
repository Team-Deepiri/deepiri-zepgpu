from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import deepiri_zepgpu.training.runner as runner


class FakeNvml:
    def __init__(
        self,
        utilization: int = 37,
        *,
        fail_init: bool = False,
        fail_handle: bool = False,
        fail_sample: bool = False,
    ) -> None:
        self.utilization = utilization
        self.fail_init = fail_init
        self.fail_handle = fail_handle
        self.fail_sample = fail_sample
        self.init_calls = 0
        self.handle_indices: list[int] = []
        self.sample_calls = 0
        self.shutdown_calls = 0
        self.handle = object()

    def nvmlInit(self) -> None:
        self.init_calls += 1
        if self.fail_init:
            raise RuntimeError("init failed")

    def nvmlDeviceGetHandleByIndex(self, device_index: int) -> object:
        self.handle_indices.append(device_index)
        if self.fail_handle:
            raise RuntimeError("handle failed")
        return self.handle

    def nvmlDeviceGetUtilizationRates(self, handle: object) -> Any:
        assert handle is self.handle
        self.sample_calls += 1
        if self.fail_sample:
            raise RuntimeError("sample failed")
        return SimpleNamespace(gpu=self.utilization)

    def nvmlShutdown(self) -> None:
        self.shutdown_calls += 1


def test_nvml_initializes_once_caches_selected_handle_and_shuts_down_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nvml = FakeNvml(utilization=42)
    monkeypatch.setattr(runner, "import_module", lambda name: nvml)
    sampler = runner.NvmlSampler(device_index=2)

    assert sampler.sample() == 42
    assert sampler.sample() == 42
    assert nvml.init_calls == 1
    assert nvml.handle_indices == [2]
    assert nvml.sample_calls == 2

    sampler.shutdown()
    sampler.shutdown()
    assert nvml.shutdown_calls == 1
    assert sampler.sample() is None


def test_nvml_preserves_zero_utilization(monkeypatch: pytest.MonkeyPatch) -> None:
    nvml = FakeNvml(utilization=0)
    monkeypatch.setattr(runner, "import_module", lambda name: nvml)
    sampler = runner.NvmlSampler(device_index=0)

    assert sampler.sample() == 0
    sampler.shutdown()


def test_nvml_import_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    imports = 0

    def unavailable(name: str) -> Any:
        nonlocal imports
        imports += 1
        raise ImportError(name)

    monkeypatch.setattr(runner, "import_module", unavailable)
    sampler = runner.NvmlSampler(device_index=0)

    assert sampler.sample() is None
    assert sampler.sample() is None
    assert imports == 1
    sampler.shutdown()


def test_nvml_initialization_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    nvml = FakeNvml(fail_init=True)
    monkeypatch.setattr(runner, "import_module", lambda name: nvml)
    sampler = runner.NvmlSampler(device_index=0)

    assert sampler.sample() is None
    assert sampler.sample() is None
    assert nvml.init_calls == 1
    assert nvml.shutdown_calls == 0


def test_nvml_handle_failure_is_safe_and_releases_initialized_nvml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nvml = FakeNvml(fail_handle=True)
    monkeypatch.setattr(runner, "import_module", lambda name: nvml)
    sampler = runner.NvmlSampler(device_index=3)

    assert sampler.sample() is None
    assert nvml.handle_indices == [3]
    assert nvml.shutdown_calls == 1
    sampler.shutdown()
    assert nvml.shutdown_calls == 1


def test_nvml_sampling_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    nvml = FakeNvml(fail_sample=True)
    monkeypatch.setattr(runner, "import_module", lambda name: nvml)
    sampler = runner.NvmlSampler(device_index=0)

    assert sampler.sample() is None
    assert nvml.init_calls == 1
    assert nvml.sample_calls == 1
    sampler.shutdown()
    assert nvml.shutdown_calls == 1
