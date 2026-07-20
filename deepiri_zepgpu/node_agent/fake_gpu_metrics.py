"""Fake GPU metrics for Phase 8 local room-network simulation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class FakeGpuConfig:
    gpu_count: int = 1
    gpu_name: str = "Simulated NVIDIA RTX 4090"
    total_memory_mb: int = 24_576


def build_fake_gpu_payload(config: FakeGpuConfig) -> list[dict]:
    """Build a deterministic-looking fake GPU heartbeat payload.

    The values intentionally vary a little each call so the dashboard can show
    live-looking metrics without requiring a real GPU.
    """
    now = datetime.now(UTC).isoformat()

    gpus: list[dict] = []
    for index in range(config.gpu_count):
        utilization = random.randint(5, 75)
        memory_used = random.randint(512, int(config.total_memory_mb * 0.65))
        temperature = random.randint(35, 72)

        gpus.append(
            {
                "device_id": index,
                "device_index": index,
                "name": config.gpu_name,
                "total_memory_mb": config.total_memory_mb,
                "used_memory_mb": memory_used,
                "free_memory_mb": config.total_memory_mb - memory_used,
                "available_memory_mb": config.total_memory_mb - memory_used,
                "utilization_percent": utilization,
                "temperature_c": temperature,
                "available": utilization < 85,
                "last_seen_at": now,
                "simulated": True,
            }
        )

    return gpus
