"""Shared helpers for Phase 17 multi-process / Docker training e2e launchers."""

from __future__ import annotations

from typing import Any

import httpx

from deepiri_zepgpu.node_agent.fake_gpu_metrics import FakeGpuConfig, build_fake_gpu_payload
from deepiri_zepgpu.training.config import (
    CompressionConfig,
    CompressorBackend,
    DistributedTrainingConfig,
    OverlapMode,
    Precision,
    TrainingRunConfig,
)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register_and_login(client: httpx.AsyncClient, username: str, password: str) -> str:
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "first_name": "E2E",
            "last_name": "Worker",
        },
    )
    if register.is_error and register.status_code not in {400, 409}:
        raise RuntimeError(f"register failed: {register.status_code} {register.text}")
    login = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    login.raise_for_status()
    return str(login.json()["access_token"])


def heartbeat_payload(node_name: str) -> dict[str, Any]:
    return {
        "is_online": True,
        "endpoint": "simulation://phase17-e2e",
        "agent_version": "0.2.0",
        "node_name": node_name,
        "provider_mode": "dialout",
        "gpu_status": build_fake_gpu_payload(FakeGpuConfig(gpu_count=1)),
        "capabilities": {
            "runtime": {
                "cuda_version": "12.1",
                "pytorch_version": "2.3.0",
                "driver_version": "535.0",
            },
            "topology": {"nvlink": "unavailable", "p2p": "unavailable"},
        },
        "path": {
            "path_type": "direct",
            "path_class": "same_host",
            "coordinator_rtt_ms": 5.0,
            "measurement_kind": "measured",
        },
        "coordinator_rtt_ms": 5.0,
    }


async def invite_and_join(
    client: httpx.AsyncClient,
    *,
    owner_token: str,
    provider_token: str,
    room_id: str,
    node_name: str,
    invite_code: str | None = None,
) -> tuple[str, str, str]:
    if invite_code is None:
        invite = await client.post(
            f"/api/v1/rooms/{room_id}/invites",
            headers=auth_headers(owner_token),
            json={"max_uses": 2},
        )
        invite.raise_for_status()
        invite_code = str(invite.json()["code"])
    join = await client.post(
        "/api/v1/rooms/join",
        headers=auth_headers(provider_token),
        json={
            "invite_code": invite_code,
            "node_name": node_name,
            "provider_mode": "dialout",
        },
    )
    join.raise_for_status()
    body = join.json()
    peer_id = str(body["member"]["id"])
    peer_auth = body.get("auth_token")
    if not peer_auth:
        raise RuntimeError("Join did not return room-scoped provider auth_token")
    return peer_id, str(peer_auth), invite_code


def smoke_training_config(
    *,
    run_name: str,
    compressor: str,
    overlap: str,
    startup_timeout_seconds: int = 300,
) -> TrainingRunConfig:
    return TrainingRunConfig(
        schema_version=2,
        run_name=run_name,
        model_name="hf-internal-testing/tiny-random-gpt2",
        device="cpu",
        precision=Precision.FP32,
        smoke_run=True,
        gradient_checkpointing=False,
        startup_timeout_seconds=startup_timeout_seconds,
        distributed=DistributedTrainingConfig(
            enabled=True,
            local_steps_per_round=1,
            max_rounds=2,
            compression=CompressionConfig(backend=CompressorBackend(compressor)),
            overlap_mode=OverlapMode(overlap),
        ),
    )
