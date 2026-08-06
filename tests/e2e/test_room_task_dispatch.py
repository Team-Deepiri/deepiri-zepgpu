"""End-to-end room_auto dispatch against a live coordinator stack (opt-in)."""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx
import pytest

from deepiri_zepgpu.node_agent.fake_gpu_metrics import FakeGpuConfig, build_fake_gpu_payload

pytestmark = pytest.mark.e2e

E2E_ENABLED = os.getenv("E2E_ROOMS_BACKEND") == "1"
BASE_URL = os.getenv("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PASSWORD = os.getenv("E2E_PASSWORD", "e2e-rooms-backend-password")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(client: httpx.AsyncClient, username: str) -> str:
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": PASSWORD,
            "first_name": "E2E",
            "last_name": "Rooms",
        },
    )
    assert register.is_success, f"register failed: {register.status_code} {register.text}"
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert login.is_success, f"login failed: {login.status_code} {login.text}"
    token = login.json().get("access_token")
    assert token, "login missing access_token"
    return str(token)


async def _lifecycle(
    client: httpx.AsyncClient,
    peer_token: str,
    peer_id: str,
    assignment_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/node-tasks/{assignment_id}/{action}",
        params={"peer_id": peer_id},
        headers=_auth(peer_token),
        json=payload or {},
    )
    assert response.is_success, f"{action} failed: {response.status_code} {response.text}"
    return dict(response.json())


@pytest.mark.skipif(
    not E2E_ENABLED,
    reason="Set E2E_ROOMS_BACKEND=1 with Docker Compose running (API on :8000)",
)
@pytest.mark.asyncio
async def test_room_auto_dispatch_happy_path() -> None:
    """Live stack: dial-out room → provider heartbeat → room_auto assign → claim/complete."""
    suffix = uuid.uuid4().hex[:10]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=45.0) as client:
        try:
            health = await client.get("/api/v1/health")
        except httpx.HTTPError as exc:
            pytest.fail(
                f"Coordinator unreachable at {BASE_URL}: {exc}. "
                "Start docker/docker-compose.prod.yml (API on :8000) before running e2e."
            )
        assert health.is_success, f"health failed: {health.status_code} {health.text}"
        assert health.json().get("status") == "healthy", health.json()

        owner_token = await _register_and_login(client, f"e2e-owner-{suffix}")
        provider_token = await _register_and_login(client, f"e2e-provider-{suffix}")

        room = await client.post(
            "/api/v1/rooms",
            headers=_auth(owner_token),
            json={
                "name": f"E2E Room {suffix}",
                "description": "room_auto e2e",
                "transport_mode": "dialout",
            },
        )
        assert room.is_success, f"create room failed: {room.status_code} {room.text}"
        room_id = str(room.json()["id"])

        invite = await client.post(
            f"/api/v1/rooms/{room_id}/invites",
            headers=_auth(owner_token),
            json={"max_uses": 1},
        )
        assert invite.is_success, f"invite failed: {invite.status_code} {invite.text}"
        invite_code = str(invite.json()["code"])

        join = await client.post(
            "/api/v1/rooms/join",
            headers=_auth(provider_token),
            json={
                "invite_code": invite_code,
                "node_name": "e2e-provider",
                "provider_mode": "dialout",
            },
        )
        assert join.is_success, f"join failed: {join.status_code} {join.text}"
        join_body = join.json()
        peer_id = str(join_body["member"]["id"])
        peer_token = join_body.get("auth_token")
        if not peer_token:
            config = await client.get(
                f"/api/v1/rooms/{room_id}/config", headers=_auth(provider_token)
            )
            assert config.is_success, config.text
            peer_token = config.json().get("auth_token")
        assert peer_token, "join/config missing provider auth_token"
        peer_token = str(peer_token)

        heartbeat = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
            headers=_auth(peer_token),
            json={
                "is_online": True,
                "endpoint": "e2e://provider",
                "agent_version": "0.2.0",
                "node_name": "e2e-provider",
                "provider_mode": "dialout",
                "gpu_status": build_fake_gpu_payload(FakeGpuConfig(gpu_count=1)),
                "capabilities": {
                    "runtime": {"cuda_version": "12.1", "pytorch_version": "2.3.0"},
                    "topology": {"nvlink": "unavailable"},
                },
                "path": {
                    "path_type": "direct",
                    "path_class": "same_host",
                    "coordinator_rtt_ms": 5.0,
                    "measurement_kind": "measured",
                },
                "coordinator_rtt_ms": 5.0,
            },
        )
        assert heartbeat.is_success, f"heartbeat failed: {heartbeat.status_code} {heartbeat.text}"
        assert heartbeat.json().get("is_online") is True

        task = await client.post(
            "/api/v1/tasks",
            headers=_auth(owner_token),
            json={
                "name": "E2E room_auto no-op",
                "func_name": "random.seed",
                "dispatch_mode": "room_auto",
                "room_id": room_id,
                "gpu_memory_mb": 0,
                "timeout_seconds": 60,
            },
        )
        assert task.is_success, f"dispatch failed: {task.status_code} {task.text}"
        task_body = task.json()
        assert task_body.get("status") == "assigned", task_body
        assignment = task_body.get("assignment") or {}
        assignment_id = str(assignment.get("assignment_id") or "")
        assert assignment_id, f"missing assignment: {task_body}"
        assert str(assignment.get("peer_id")) == peer_id

        claimed = await _lifecycle(client, peer_token, peer_id, assignment_id, "claim")
        assert claimed.get("status") in {"claimed", "accepted", "running"}, claimed
        await _lifecycle(client, peer_token, peer_id, assignment_id, "start")
        completed = await _lifecycle(
            client,
            peer_token,
            peer_id,
            assignment_id,
            "complete",
            {
                "result_metadata": {
                    "kind": "noop",
                    "status": "ok",
                    "message": "e2e remote noop",
                    "simulated": True,
                }
            },
        )
        assert completed.get("status") == "completed", completed

        result = await client.get(
            f"/api/v1/node-tasks/{assignment_id}/result",
            headers=_auth(owner_token),
        )
        assert result.is_success, result.text
        assert result.json().get("result_metadata", {}).get("kind") == "noop"
