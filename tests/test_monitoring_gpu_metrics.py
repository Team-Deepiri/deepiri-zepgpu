"""Tests for normalized GPU telemetry in the monitoring compatibility model."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from deepiri_gpu_utils import GpuBackend, GpuDevice, GpuInventory, GpuMemory

from deepiri_zepgpu.monitoring.metrics import MetricsCollector


@pytest.mark.asyncio
async def test_metrics_collector_maps_normalized_telemetry_and_missing_fields() -> None:
    inventory = GpuInventory(
        backend=GpuBackend.ROCM,
        devices=(
            GpuDevice(
                backend=GpuBackend.ROCM,
                index=3,
                name="MI300X",
                memory=GpuMemory(total_mib=1000, free_mib=250),
                utilization_percent=0,
                temperature_c=None,
                power_watts=300.5,
            ),
        ),
    )
    collector = MetricsCollector()
    with patch("deepiri_zepgpu.monitoring.metrics.discover_gpus", return_value=inventory):
        await collector._collect_gpu_metrics()

    metric = collector.get_gpu_metrics()[0]
    assert metric.device_id == 3
    assert metric.name == "MI300X"
    assert metric.utilization_percent == 0
    assert metric.memory_used_mb == 750
    assert metric.memory_total_mb == 1000
    assert metric.memory_percent == 75
    assert metric.temperature_celsius == 0
    assert metric.power_watts == 300.5


@pytest.mark.asyncio
async def test_metrics_collector_tolerates_missing_or_broken_vendor_tooling() -> None:
    collector = MetricsCollector()
    with patch(
        "deepiri_zepgpu.monitoring.metrics.discover_gpus",
        return_value=GpuInventory(backend=GpuBackend.CPU),
    ):
        await collector._collect_gpu_metrics()
    with patch("deepiri_zepgpu.monitoring.metrics.discover_gpus", side_effect=OSError):
        await collector._collect_gpu_metrics()
    assert collector.get_gpu_metrics() == []
