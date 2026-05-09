"""Local GPU discovery and heartbeat payload building (peer side)."""

from __future__ import annotations

from typing import Any

from deepiri_zepgpu.vpn.peer_node import GpuInfo, discover_local_gpus


def local_gpu_status_payload() -> list[dict[str, Any]]:
    """Return GPU status dicts suitable for PeerHeartbeatRequest.gpu_status."""
    return [g.model_dump() for g in discover_local_gpus()]


def format_gpu_infos(infos: list[GpuInfo]) -> list[dict[str, Any]]:
    return [g.model_dump() for g in infos]
