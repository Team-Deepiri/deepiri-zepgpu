"""Phase 8 local simulated room node.

This script provides a reproducible local simulation path for room networking:
register/login, create a room, register a simulated node, and send fake GPU
heartbeats without requiring a real GPU or cloud deployment.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from deepiri_zepgpu.node_agent.fake_gpu_metrics import (
    FakeGpuConfig,
    build_fake_gpu_payload,
)


@dataclass
class SimulatedNodeConfig:
    base_url: str
    token: str
    room_id: str
    peer_id: str
    node_name: str
    gpu_count: int
    heartbeat_interval: float
    peer_token: str | None = None
    request_timeout: float = 20.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a simulated ZepGPU room node.")

    parser.add_argument("--base-url", default="http://127.0.0.1:8000")

    parser.add_argument("--email", default="phase8-node@example.com")
    parser.add_argument("--password", default="phase8password")

    parser.add_argument("--token", default=None, help="Existing bearer token.")
    parser.add_argument("--room-id", default=None, help="Existing room id.")
    parser.add_argument("--peer-id", default=None, help="Existing peer id.")

    parser.add_argument("--room-name", default="Phase 8 Local Simulation Room")
    parser.add_argument("--node-name", default="phase8-sim-node")
    parser.add_argument("--gpu-count", type=int, default=1)
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true", help="Send one heartbeat and exit.")
    parser.add_argument(
        "--state-file",
        default=".phase8_sim_state.json",
        help="Local dev state file for generated token, room id, and peer id.",
    )

    parser.add_argument(
        "--peer-token",
        default=None,
        help="Bearer token issued to the peer/node agent for node-task endpoints.",
    )
    parser.add_argument(
        "--complete-pending",
        action="store_true",
        help="Poll and complete one pending no-op node task.",
    )

    parser.add_argument(
        "--request-timeout",
        type=float,
        default=20.0,
        help="HTTP request timeout in seconds.",
    )

    return parser.parse_args()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def write_state_file(path: str, config: SimulatedNodeConfig) -> None:
    state_path = Path(path)
    state = asdict(config)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"[phase8] wrote state file {state_path}")


async def register_user(client: httpx.AsyncClient, email: str, password: str) -> None:
    payload = {
        "email": email,
        "password": password,
        "username": email.split("@")[0],
        "first_name": "Phase8",
        "last_name": "Node",
    }

    response = await client.post("/api/v1/auth/register", json=payload)

    if response.status_code in {200, 201, 409, 400}:
        print(f"[auth] register status={response.status_code}")
        return

    print(f"[auth] register unexpected {response.status_code}: {response.text}")


async def login_user(client: httpx.AsyncClient, email: str, password: str) -> str:
    username = email.split("@")[0]

    login_payloads: list[dict[str, str]] = [
        {"username": username, "password": password},
        {"username": email, "password": password},
    ]

    last_error = ""
    for payload in login_payloads:
        response = await client.post("/api/v1/auth/login", json=payload)

        if response.status_code < 400:
            data = response.json()
            token = data.get("access_token") or data.get("token")
            if not token:
                raise RuntimeError(f"Login response did not include a token: {data}")

            print(f"[auth] login ok username={payload['username']}")
            return str(token)

        last_error = f"{response.status_code}: {response.text}"

    raise RuntimeError(f"Login failed. Last error: {last_error}")


async def create_room(client: httpx.AsyncClient, token: str, room_name: str) -> str:
    payload = {
        "name": room_name,
        "description": "Local Phase 8 simulated room",
        "network_mode": "wireguard",
    }

    response = await client.post(
        "/api/v1/rooms",
        headers=auth_headers(token),
        json=payload,
    )

    if response.status_code >= 400:
        fallback_payload = {"name": room_name}
        response = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(token),
            json=fallback_payload,
        )

    response.raise_for_status()
    data = response.json()

    room_id = data.get("id") or data.get("room_id") or data.get("network_id")
    if not room_id:
        raise RuntimeError(f"Room response did not include an id: {data}")

    print(f"[rooms] created room_id={room_id}")
    return str(room_id)


async def resolve_peer(
    client: httpx.AsyncClient,
    token: str,
    room_id: str,
    node_name: str,
) -> str:
    """Find an existing peer/node for the room.

    Phase 8 local simulation should use a real peer id from the backend instead
    of inventing one locally. A generated UUID will fail heartbeat validation
    because the backend checks that the peer exists in the room.
    """
    headers = auth_headers(token)

    list_paths = [
        f"/api/v1/rooms/{room_id}/nodes",
        f"/api/v1/rooms/{room_id}/peers",
        f"/api/v1/vpn/networks/{room_id}/peers",
    ]

    last_error = ""
    for path in list_paths:
        response = await client.get(path, headers=headers)

        if response.status_code >= 400:
            last_error = f"GET {path} -> {response.status_code}: {response.text}"
            continue

        data = response.json()

        if isinstance(data, dict):
            candidates = (
                data.get("nodes")
                or data.get("peers")
                or data.get("items")
                or data.get("data")
                or []
            )
        elif isinstance(data, list):
            candidates = data
        else:
            candidates = []

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue

            peer_id = candidate.get("id") or candidate.get("peer_id")
            if peer_id:
                print(f"[peer] resolved existing peer_id={peer_id}")
                return str(peer_id)

    raise RuntimeError(
        "Could not resolve a real peer for the room. "
        f"Last error: {last_error}. "
        "Next step is to use the room invite/join API to create a simulated peer."
    )


def find_token_in_payload(
    payload: Any,
    *,
    max_depth: int = 8,
    current_depth: int = 0,
) -> str | None:
    """Search a bounded response payload for a peer/node auth token."""
    if current_depth > max_depth:
        return None

    token_keys = {
        "auth_token",
        "peer_auth_token",
        "node_auth_token",
        "node_token",
        "agent_token",
    }

    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in token_keys and isinstance(value, str) and value:
                return value

        for value in payload.values():
            found = find_token_in_payload(
                value,
                max_depth=max_depth,
                current_depth=current_depth + 1,
            )
            if found:
                return found

    if isinstance(payload, list):
        for item in payload:
            found = find_token_in_payload(
                item,
                max_depth=max_depth,
                current_depth=current_depth + 1,
            )
            if found:
                return found

    return None


async def resolve_peer_token(
    client: httpx.AsyncClient,
    token: str,
    room_id: str,
) -> str | None:
    """Try to fetch the peer/node token from local room config endpoints."""
    headers = auth_headers(token)

    config_paths = [
        f"/api/v1/rooms/{room_id}/config",
        f"/api/v1/vpn/networks/{room_id}/config",
    ]

    last_error = ""
    for path in config_paths:
        response = await client.get(path, headers=headers)

        if response.status_code >= 400:
            last_error = f"GET {path} -> {response.status_code}: {response.text}"
            continue

        data = response.json()
        peer_token = find_token_in_payload(data)
        if peer_token:
            print(f"[peer] resolved peer auth token from {path}")
            return peer_token

        print(f"[peer] config endpoint had no peer token: {path}")

    print(f"[peer] could not resolve peer token. Last error: {last_error}")
    return None


async def bootstrap(args: argparse.Namespace) -> SimulatedNodeConfig:
    base_url = args.base_url.rstrip("/")

    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=args.request_timeout,
    ) as client:
        token = args.token
        if not token:
            await register_user(client, args.email, args.password)
            token = await login_user(client, args.email, args.password)

        room_id = args.room_id
        if not room_id:
            room_id = await create_room(client, token, args.room_name)

        peer_id = args.peer_id
        if not peer_id:
            peer_id = await resolve_peer(client, token, room_id, args.node_name)

        peer_token = args.peer_token
        if not peer_token:
            peer_token = await resolve_peer_token(client, token, room_id)

    return SimulatedNodeConfig(
        base_url=base_url,
        token=token,
        room_id=room_id,
        peer_id=peer_id,
        node_name=args.node_name,
        gpu_count=args.gpu_count,
        heartbeat_interval=args.heartbeat_interval,
        peer_token=peer_token,
        request_timeout=args.request_timeout,
    )


async def send_heartbeat(client: httpx.AsyncClient, config: SimulatedNodeConfig) -> None:
    gpu_payload = build_fake_gpu_payload(
        FakeGpuConfig(
            gpu_count=config.gpu_count,
        )
    )

    payload: dict[str, Any] = {
        "peer_id": config.peer_id,
        "node_name": config.node_name,
        "hostname": config.node_name,
        "status": "online",
        "gpu_count": config.gpu_count,
        "gpus": gpu_payload,
        "gpu_status": gpu_payload,
        "metrics": {
            "simulated": True,
            "cpu_percent": 12.5,
            "memory_percent": 33.0,
        },
        "metadata": {
            "phase": "phase8",
            "simulated": True,
        },
    }

    room_heartbeat_path = f"/api/v1/rooms/{config.room_id}/nodes/{config.peer_id}/heartbeat"

    response = await client.post(
        room_heartbeat_path,
        headers=auth_headers(config.token),
        json=payload,
    )

    if response.status_code == 404:
        response = await client.post("/api/v1/vpn/peers/heartbeat", json=payload)

    if response.status_code >= 400:
        print(f"[heartbeat] failed {response.status_code}: {response.text}")
        return

    print(f"[heartbeat] ok node={config.node_name} gpus={config.gpu_count}")


def node_task_headers(config: SimulatedNodeConfig) -> dict[str, str]:
    if not config.peer_token:
        raise RuntimeError(
            "peer_token is required for node-task endpoints. "
            "Run bootstrap so it can resolve one, or pass --peer-token explicitly."
        )

    return auth_headers(config.peer_token)


async def poll_pending_node_tasks(
    client: httpx.AsyncClient,
    config: SimulatedNodeConfig,
) -> list[dict[str, Any]]:
    response = await client.get(
        f"/api/v1/node-tasks/rooms/{config.room_id}/nodes/{config.peer_id}/tasks/pending",
        headers=node_task_headers(config),
        params={"limit": 1},
    )

    if response.status_code >= 400:
        print(f"[node-task] pending failed {response.status_code}: {response.text}")
        return []

    data = response.json()
    if not isinstance(data, list):
        print(f"[node-task] pending returned unexpected payload: {data}")
        return []

    return [item for item in data if isinstance(item, dict)]


async def post_node_task_state(
    client: httpx.AsyncClient,
    config: SimulatedNodeConfig,
    assignment_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    response = await client.post(
        f"/api/v1/node-tasks/{assignment_id}/{action}",
        headers=node_task_headers(config),
        params={"peer_id": config.peer_id},
        json=payload or {},
    )

    if response.status_code >= 400:
        print(
            f"[node-task] {action} failed "
            f"assignment={assignment_id} status={response.status_code}: {response.text}"
        )
        return None

    data = response.json()
    print(f"[node-task] {action} ok assignment={assignment_id}")
    return data if isinstance(data, dict) else {}


async def complete_one_pending_noop(
    client: httpx.AsyncClient,
    config: SimulatedNodeConfig,
) -> bool:
    pending = await poll_pending_node_tasks(client, config)
    if not pending:
        print("[node-task] no pending assignments")
        return False

    assignment = pending[0]
    assignment_id = str(assignment["assignment_id"])
    task_id = str(assignment["task_id"])

    print(f"[node-task] picked assignment={assignment_id} task={task_id}")

    accepted = await post_node_task_state(client, config, assignment_id, "accept")
    if accepted is None:
        return False

    started = await post_node_task_state(client, config, assignment_id, "start")
    if started is None:
        return False

    completed = await post_node_task_state(
        client,
        config,
        assignment_id,
        "complete",
        {
            "result_metadata": {
                "simulated": True,
                "runner": config.node_name,
                "task_id": task_id,
                "message": "Phase 8 simulated no-op task completed locally.",
            }
        },
    )

    if completed is None:
        return False

    print(f"[node-task] completed no-op assignment={assignment_id}")
    return True


async def run(
    config: SimulatedNodeConfig,
    once: bool,
    complete_pending: bool,
) -> None:
    async with httpx.AsyncClient(
        base_url=config.base_url,
        timeout=config.request_timeout,
    ) as client:
        print("[phase8] simulated node started")
        print(f"[phase8] base_url={config.base_url}")
        print(f"[phase8] room_id={config.room_id}")
        print(f"[phase8] peer_id={config.peer_id}")

        while True:
            await send_heartbeat(client, config)

            if complete_pending:
                await complete_one_pending_noop(client, config)

            if once:
                return

            await asyncio.sleep(config.heartbeat_interval)


def main() -> int:
    args = parse_args()

    try:
        config = asyncio.run(bootstrap(args))
        write_state_file(args.state_file, config)
        asyncio.run(
            run(
                config,
                once=args.once,
                complete_pending=args.complete_pending,
            )
        )
    except KeyboardInterrupt:
        print("\n[phase8] simulated node stopped")
        return 0
    except Exception as exc:
        print(f"[phase8] failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
