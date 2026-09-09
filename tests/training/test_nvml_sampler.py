"""Regression tests for the legacy training telemetry sampler adapter."""

from __future__ import annotations

from unittest.mock import patch

from deepiri_gpu_utils import GpuBackend, GpuDevice, GpuInventory, GpuMemory

from deepiri_zepgpu.training.runner import NvmlSampler


def _inventory(*devices: GpuDevice) -> GpuInventory:
    return GpuInventory(
        backend=devices[0].backend if devices else GpuBackend.CPU,
        devices=devices,
    )


def test_sampler_selects_requested_index_and_preserves_zero_utilization() -> None:
    inventory = _inventory(
        GpuDevice(
            backend=GpuBackend.CUDA,
            index=0,
            memory=GpuMemory(total_mib=8192),
            utilization_percent=0,
        ),
        GpuDevice(
            backend=GpuBackend.CUDA,
            index=2,
            memory=GpuMemory(total_mib=24576),
            utilization_percent=42,
        ),
    )
    sampler = NvmlSampler(device_index=2)
    with patch("deepiri_zepgpu.training.runner.discover_gpus", return_value=inventory):
        assert sampler.sample() == 42

    zero_sampler = NvmlSampler(device_index=0)
    with patch("deepiri_zepgpu.training.runner.discover_gpus", return_value=inventory):
        assert zero_sampler.sample() == 0


def test_missing_tooling_malformed_telemetry_and_probe_failures_are_safe() -> None:
    sampler = NvmlSampler(device_index=0, poll_interval_seconds=0)
    missing_metric = _inventory(
        GpuDevice(
            backend=GpuBackend.ROCM,
            index=0,
            memory=GpuMemory(total_mib=196608),
            utilization_percent=None,
        )
    )
    with patch("deepiri_zepgpu.training.runner.discover_gpus", return_value=missing_metric):
        assert sampler.sample() is None


def test_sampler_throttles_subprocess_backed_inventory() -> None:
    inventory = _inventory(
        GpuDevice(
            backend=GpuBackend.CUDA,
            index=0,
            memory=GpuMemory(total_mib=8192),
            utilization_percent=17,
        )
    )
    sampler = NvmlSampler(device_index=0, poll_interval_seconds=5)
    with (
        patch("deepiri_zepgpu.training.runner.discover_gpus", return_value=inventory) as discover,
        patch("deepiri_zepgpu.training.runner.time.monotonic", side_effect=[10.0, 11.0, 16.0]),
    ):
        assert sampler.sample() == 17
        assert sampler.sample() == 17
        assert sampler.sample() == 17
    assert discover.call_count == 2
    with patch("deepiri_zepgpu.training.runner.discover_gpus", side_effect=OSError):
        assert sampler.sample() is None


def test_shutdown_is_idempotent_and_stops_future_samples() -> None:
    sampler = NvmlSampler(device_index=0)
    sampler.shutdown()
    sampler.shutdown()
    with patch("deepiri_zepgpu.training.runner.discover_gpus") as discover:
        assert sampler.sample() is None
    discover.assert_not_called()
