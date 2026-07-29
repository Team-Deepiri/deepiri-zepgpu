"""End-to-end local room-network simulation gate for Phase 10."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import Any

import httpx
from utils import auth_headers

from deepiri_zepgpu.node_agent.fake_gpu_metrics import FakeGpuConfig, build_fake_gpu_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the local room-network baseline.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--password", default="local-simulation-password")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def register_and_login(client: httpx.AsyncClient, username: str, password: str) -> str:
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "first_name": "Local",
            "last_name": "Simulation",
        },
    )
    if register.is_error:
        raise RuntimeError(f"Registration failed ({register.status_code}): {register.text}")
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    login.raise_for_status()
    token = login.json().get("access_token")
    require(bool(token), "Login response did not include access_token")
    return str(token)


async def post_lifecycle(
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
        headers=auth_headers(peer_token),
        json=payload or {},
    )
    response.raise_for_status()
    return dict(response.json())


async def wait_for_completed_task(
    client: httpx.AsyncClient, owner_token: str, task_id: str
) -> dict[str, Any]:
    for _ in range(20):
        response = await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers(owner_token))
        response.raise_for_status()
        task = dict(response.json())
        if task.get("status") == "completed":
            return task
        await asyncio.sleep(0.25)
    raise RuntimeError(f"Task {task_id} did not become completed through polling")


async def run_gate(args: argparse.Namespace) -> None:
    suffix = uuid.uuid4().hex[:10]
    owner_username = f"roomowner-{suffix}"
    provider_username = f"provider-{suffix}"

    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"), timeout=args.timeout
    ) as client:
        health = await client.get("/api/v1/health")
        health.raise_for_status()
        require(health.json().get("status") == "healthy", "Coordinator is not healthy")
        print("[PASS] coordinator startup and health")

        owner_token = await register_and_login(client, owner_username, args.password)
        provider_token = await register_and_login(client, provider_username, args.password)
        print("[PASS] owner and provider registration/login")

        room_response = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(owner_token),
            json={"name": f"Local Simulation {suffix}", "description": "Phase 10 gate"},
        )
        room_response.raise_for_status()
        room_id = str(room_response.json()["id"])
        print(f"[PASS] room creation ({room_id})")

        invite_response = await client.post(
            f"/api/v1/rooms/{room_id}/invites",
            headers=auth_headers(owner_token),
            json={"max_uses": 1},
        )
        invite_response.raise_for_status()
        invite_code = str(invite_response.json()["code"])
        print("[PASS] invite creation")

        join_response = await client.post(
            "/api/v1/rooms/join",
            headers=auth_headers(provider_token),
            json={"invite_code": invite_code},
        )
        join_response.raise_for_status()
        peer_id = str(join_response.json()["member"]["id"])

        config_response = await client.get(
            f"/api/v1/rooms/{room_id}/config", headers=auth_headers(provider_token)
        )
        config_response.raise_for_status()
        peer_token = config_response.json().get("auth_token")
        require(bool(peer_token), "Room config did not provide a node-agent auth token")
        print(f"[PASS] invited provider joined ({peer_id})")

        heartbeat = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
            headers=auth_headers(provider_token),
            json={
                "is_online": True,
                "endpoint": "simulation://local-provider",
                "gpu_status": build_fake_gpu_payload(FakeGpuConfig(gpu_count=1)),
            },
        )
        heartbeat.raise_for_status()
        require(heartbeat.json().get("is_online") is True, "Provider did not become online")

        nodes = await client.get(
            f"/api/v1/rooms/{room_id}/nodes", headers=auth_headers(owner_token)
        )
        nodes.raise_for_status()
        require(
            any(
                str(node.get("id")) == peer_id and node.get("gpu_count", 0) >= 1
                for node in nodes.json()
            ),
            "Simulated provider/GPU is missing from room nodes",
        )
        pool = await client.get(
            f"/api/v1/rooms/{room_id}/gpu-pool", headers=auth_headers(owner_token)
        )
        pool.raise_for_status()
        require(pool.json().get("available_gpus", 0) >= 1, "GPU pool has no available GPU")
        print("[PASS] simulated heartbeat and GPU pool summary")

        task_response = await client.post(
            "/api/v1/tasks",
            headers=auth_headers(owner_token),
            json={
                "name": "Phase 10 remote no-op",
                "func_name": "random.seed",
                "dispatch_mode": "room_auto",
                "room_id": room_id,
                "gpu_memory_mb": 0,
                "timeout_seconds": 60,
            },
        )
        task_response.raise_for_status()
        task = dict(task_response.json())
        assignment_id = str(task["assignment"]["assignment_id"])
        task_id = str(task["id"])
        print("[PASS] room-aware no-op dispatch")

        pending = await client.get(
            f"/api/v1/node-tasks/rooms/{room_id}/nodes/{peer_id}/tasks/pending",
            headers=auth_headers(str(peer_token)),
        )
        pending.raise_for_status()
        require(
            any(str(item.get("assignment_id")) == assignment_id for item in pending.json()),
            "Assignment was not visible to the provider",
        )

        accepted = await post_lifecycle(client, str(peer_token), peer_id, assignment_id, "accept")
        accepted_retry = await post_lifecycle(
            client, str(peer_token), peer_id, assignment_id, "accept"
        )
        require(accepted_retry["status"] == accepted["status"], "Accept retry was not idempotent")
        await post_lifecycle(client, str(peer_token), peer_id, assignment_id, "start")
        await post_lifecycle(client, str(peer_token), peer_id, assignment_id, "start")
        result_metadata = {
            "kind": "noop",
            "status": "ok",
            "message": "remote noop completed",
            "simulated": True,
        }
        await post_lifecycle(
            client,
            str(peer_token),
            peer_id,
            assignment_id,
            "complete",
            {"result_metadata": result_metadata},
        )
        await post_lifecycle(
            client,
            str(peer_token),
            peer_id,
            assignment_id,
            "complete",
            {"result_metadata": result_metadata},
        )
        completed_task = await wait_for_completed_task(client, owner_token, task_id)
        require(
            completed_task.get("assignment", {}).get("status") == "completed",
            "Assignment was not completed",
        )

        result = await client.get(
            f"/api/v1/node-tasks/{assignment_id}/result",
            headers=auth_headers(owner_token),
        )
        result.raise_for_status()
        require(result.json().get("result_metadata", {}).get("kind") == "noop", "Result missing")
        print("[PASS] node-agent completion, polling update, and result visibility")

        vpn_networks = await client.get("/api/v1/vpn/networks", headers=auth_headers(owner_token))
        vpn_networks.raise_for_status()
        require(
            any(str(network.get("id")) == room_id for network in vpn_networks.json()),
            "Room is not visible through the compatible VPN API",
        )
        print("[PASS] /api/v1/vpn compatibility")


def main() -> int:
    try:
        asyncio.run(run_gate(parse_args()))
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("Phase 10 local room-network simulation PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
