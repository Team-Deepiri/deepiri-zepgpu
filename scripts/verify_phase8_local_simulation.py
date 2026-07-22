"""Phase 8 local simulation smoke test.

Verifies the local room-network simulation path:
- auth
- room creation
- simulated node heartbeat
- GPU pool visibility
- room_auto task assignment
- no-op remote completion
- final task status
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

import httpx

from scripts.run_simulated_room_node import bootstrap, complete_one_pending_noop, run
from scripts.utils import auth_headers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Phase 8 local simulation.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", default="phase8-smoke@example.com")
    parser.add_argument("--password", default="phase8password")
    parser.add_argument("--room-name", default="Phase 8 Smoke Room")
    parser.add_argument("--node-name", default="phase8-smoke-node")
    parser.add_argument("--gpu-count", type=int, default=1)
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=20.0,
        help="HTTP request timeout in seconds.",
    )
    return parser.parse_args()


async def require_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "healthy":
        raise RuntimeError(f"Backend is not healthy: {data}")

    print("[PASS] backend health is healthy")


async def require_gpu_pool(
    client: httpx.AsyncClient,
    token: str,
    room_id: str,
) -> None:
    response = await client.get(
        f"/api/v1/rooms/{room_id}/gpu-pool",
        headers=auth_headers(token),
    )
    response.raise_for_status()
    data = response.json()

    if int(data.get("total_gpus", 0)) < 1:
        raise RuntimeError(f"Expected at least one GPU in pool: {data}")

    if int(data.get("available_gpus", 0)) < 1:
        raise RuntimeError(f"Expected at least one available GPU: {data}")

    print("[PASS] simulated GPU appears in room GPU pool")


async def require_node_online(
    client: httpx.AsyncClient,
    token: str,
    room_id: str,
) -> None:
    response = await client.get(
        f"/api/v1/rooms/{room_id}/nodes",
        headers=auth_headers(token),
    )
    response.raise_for_status()
    data = response.json()

    nodes = data if isinstance(data, list) else [data]
    online_nodes = [
        node
        for node in nodes
        if isinstance(node, dict) and node.get("is_online") and int(node.get("gpu_count", 0)) >= 1
    ]

    if not online_nodes:
        raise RuntimeError(f"Expected an online simulated GPU node: {data}")

    print("[PASS] simulated node appears online")


async def submit_room_auto_task(
    client: httpx.AsyncClient,
    token: str,
    room_id: str,
) -> dict[str, Any]:
    payload = {
        "func_name": "random.seed",
        "dispatch_mode": "room_auto",
        "room_id": room_id,
        "gpu_memory_mb": 0,
        "cpu_cores": 1,
        "timeout_seconds": 60,
        "allow_fallback_cpu": True,
    }

    response = await client.post(
        "/api/v1/tasks",
        headers=auth_headers(token),
        json=payload,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "assigned":
        raise RuntimeError(f"Expected assigned task: {data}")

    if not data.get("assignment"):
        raise RuntimeError(f"Expected assignment block: {data}")

    print("[PASS] room_auto no-op task assigned")
    return data


async def require_task_completed(
    client: httpx.AsyncClient,
    token: str,
    task_id: str,
) -> None:
    response = await client.get(
        f"/api/v1/tasks/{task_id}",
        headers=auth_headers(token),
    )
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "completed":
        raise RuntimeError(f"Expected completed task: {data}")

    assignment = data.get("assignment") or {}
    if assignment.get("status") != "completed":
        raise RuntimeError(f"Expected completed assignment: {data}")

    print("[PASS] no-op remote task completed")


async def main_async(args: argparse.Namespace) -> int:
    config_args = argparse.Namespace(
        base_url=args.base_url,
        email=args.email,
        password=args.password,
        token=None,
        room_id=None,
        peer_id=None,
        peer_token=None,
        room_name=args.room_name,
        node_name=args.node_name,
        gpu_count=args.gpu_count,
        heartbeat_interval=5.0,
        once=True,
        complete_pending=False,
        state_file=".phase8_sim_state.json",
        request_timeout=args.request_timeout,
    )

    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"),
        timeout=args.request_timeout,
    ) as client:
        await require_health(client)

        config = await bootstrap(config_args)
        await run(config, once=True, complete_pending=False)

        await require_gpu_pool(client, config.token, config.room_id)
        await require_node_online(client, config.token, config.room_id)

        task = await submit_room_auto_task(client, config.token, config.room_id)

        completed = await complete_one_pending_noop(client, config)
        if not completed:
            raise RuntimeError("Simulated node did not complete a pending task")

        await require_task_completed(client, config.token, str(task["id"]))

    print("")
    print("Phase 8 local simulation smoke PASSED")
    return 0


def main() -> int:
    args = parse_args()

    try:
        return asyncio.run(main_async(args))
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
