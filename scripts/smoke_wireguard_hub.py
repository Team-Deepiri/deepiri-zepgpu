#!/usr/bin/env python3
"""WireGuard hub smoke against a live coordinator.

Records three-mode coexistence, invite join (API-level, mock-friendly),
heartbeat, and noop node-task claim/complete on a WG room.

Full UDP hub + real wg-quick is environment-specific; see
scripts/smoke_wireguard_linux_direct.py for CAP_NET_ADMIN direct-over-VPN LoRA.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from deepiri_zepgpu.node_agent.fake_gpu_metrics import FakeGpuConfig, build_fake_gpu_payload


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def heartbeat_payload(node_name: str, *, provider_mode: str = "wireguard") -> dict[str, Any]:
    return {
        "is_online": True,
        "endpoint": "simulation://wg-smoke",
        "agent_version": "0.2.0",
        "node_name": node_name,
        "provider_mode": provider_mode,
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
            "path_class": "wan",
            "coordinator_rtt_ms": 12.0,
            "measurement_kind": "measured",
        },
        "coordinator_rtt_ms": 12.0,
    }


async def register_token(client: httpx.AsyncClient, username: str, password: str) -> str:
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@ex.com",
            "password": password,
            "first_name": "WG",
            "last_name": "Smoke",
        },
    )
    if reg.is_error and reg.status_code not in {400, 409}:
        raise RuntimeError(f"register failed: {reg.status_code} {reg.text}")
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    login.raise_for_status()
    return str(login.json()["access_token"])


def elevate_to_researcher(username: str) -> None:
    """Task submission requires researcher/admin. Local Compose has no promote API."""

    import os
    import subprocess

    # Prefer direct docker exec against compose DB; fall back to psql URL if set.
    db_url = os.environ.get("DATABASE_SYNC_URL") or os.environ.get("ZEPGPU_POSTGRES_URL")
    sql = f"UPDATE users SET role = 'researcher' WHERE username = '{username}'"
    try:
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "zepgpu-db",
                "psql",
                "-U",
                "zepgpu",
                "-d",
                "zepgpu",
                "-c",
                sql,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return
    except (OSError, subprocess.CalledProcessError):
        pass
    if not db_url:
        raise RuntimeError(
            "cannot elevate owner to researcher (docker zepgpu-db unavailable and "
            "DATABASE_SYNC_URL unset); task create requires researcher role"
        )
    subprocess.run(
        ["psql", db_url, "-c", sql],
        check=True,
        capture_output=True,
        text=True,
    )


async def invite_and_join(
    client: httpx.AsyncClient,
    *,
    owner_token: str,
    provider_token: str,
    room_id: str,
    provider_mode: str,
) -> tuple[str, str, str]:
    invite = await client.post(
        f"/api/v1/rooms/{room_id}/invites",
        headers=auth_headers(owner_token),
        json={"max_uses": 4},
    )
    invite.raise_for_status()
    code = str(invite.json()["code"])
    join = await client.post(
        "/api/v1/rooms/join",
        headers=auth_headers(provider_token),
        json={"invite_code": code, "provider_mode": provider_mode},
    )
    join.raise_for_status()
    body = join.json()
    peer_id = str(body["member"]["id"])
    peer_auth = str(body["auth_token"])
    return peer_id, peer_auth, code


async def post_lifecycle(
    client: httpx.AsyncClient,
    peer_auth: str,
    peer_id: str,
    assignment_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/node-tasks/{assignment_id}/{action}",
        params={"peer_id": peer_id},
        headers=auth_headers(peer_auth),
        json=payload or {},
    )
    resp.raise_for_status()
    return dict(resp.json())


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--artifact-dir", type=Path, default=Path("/tmp/zepgpu-wg-smoke"))
    args = parser.parse_args()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex[:8]
    base = args.base_url.rstrip("/")
    password = "WgSmoke!123"

    async with httpx.AsyncClient(base_url=base, timeout=60.0) as client:
        health = await client.get("/api/v1/health")
        health.raise_for_status()
        owner_username = f"wg_smoke_owner_{suffix}"
        owner_token = await register_token(client, owner_username, password)
        elevate_to_researcher(owner_username)
        # Re-login so JWT carries the elevated role.
        owner_token = (
            await client.post(
                "/api/v1/auth/login",
                json={"username": owner_username, "password": password},
            )
        ).json()["access_token"]
        provider_token = await register_token(client, f"wg_smoke_prov_{suffix}", password)
        provider2_token = await register_token(client, f"wg_smoke_prov2_{suffix}", password)
        headers = auth_headers(owner_token)
        checks: dict[str, object] = {"health": "pass"}

        room_ids: dict[str, str] = {}
        for mode in ("wireguard", "dialout", "overlay"):
            resp = await client.post(
                "/api/v1/rooms",
                headers=headers,
                json={"name": f"smoke {mode} {suffix}", "transport_mode": mode},
            )
            resp.raise_for_status()
            body = resp.json()
            room_ids[mode] = str(body["id"])
            checks[mode] = {
                "room_id": body.get("id"),
                "transport_mode": body.get("transport_mode"),
                "requires_wireguard_udp": body.get("requires_wireguard_udp"),
            }

        wg_room = room_ids["wireguard"]
        peer_id, peer_auth, invite_code = await invite_and_join(
            client,
            owner_token=owner_token,
            provider_token=provider_token,
            room_id=wg_room,
            provider_mode="wireguard",
        )
        hb = await client.post(
            f"/api/v1/rooms/{wg_room}/nodes/{peer_id}/heartbeat",
            headers=auth_headers(peer_auth),
            json=heartbeat_payload(f"wg-smoke-{suffix}"),
        )
        hb.raise_for_status()
        peer2_id, peer2_auth, _invite2 = await invite_and_join(
            client,
            owner_token=owner_token,
            provider_token=provider2_token,
            room_id=wg_room,
            provider_mode="wireguard",
        )
        hb2 = await client.post(
            f"/api/v1/rooms/{wg_room}/nodes/{peer2_id}/heartbeat",
            headers=auth_headers(peer2_auth),
            json=heartbeat_payload(f"wg-smoke-2-{suffix}"),
        )
        hb2.raise_for_status()
        checks["join_heartbeat"] = {
            "peer_id": peer_id,
            "peer2_id": peer2_id,
            "invite_code_prefix": invite_code[:6],
            "status": "pass",
            "providers": 2,
        }

        task_response = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "name": f"WG smoke noop {suffix}",
                "func_name": "math.sqrt",
                "args": [4],
                "dispatch_mode": "room_auto",
                "room_id": wg_room,
                "gpu_memory_mb": 0,
                "timeout_seconds": 60,
            },
        )
        if task_response.status_code >= 400:
            raise RuntimeError(
                f"task create failed: {task_response.status_code} {task_response.text}"
            )
        task = task_response.json()
        assignment_id = str(task["assignment"]["assignment_id"])
        task_id = str(task["id"])

        pending = await client.get(
            f"/api/v1/node-tasks/rooms/{wg_room}/nodes/{peer_id}/tasks/pending",
            headers=auth_headers(peer_auth),
        )
        pending.raise_for_status()
        if not any(str(item.get("assignment_id")) == assignment_id for item in pending.json()):
            raise RuntimeError("noop assignment not visible on WG room")

        await post_lifecycle(client, peer_auth, peer_id, assignment_id, "claim")
        await post_lifecycle(client, peer_auth, peer_id, assignment_id, "start")
        await post_lifecycle(
            client,
            peer_auth,
            peer_id,
            assignment_id,
            "complete",
            {
                "result_metadata": {
                    "kind": "noop",
                    "status": "ok",
                    "message": "wg hub smoke",
                    "simulated": True,
                }
            },
        )
        checks["noop"] = {"task_id": task_id, "assignment_id": assignment_id, "status": "pass"}

        artifact = {
            "base_url": base,
            "generated_at": datetime.now(UTC).isoformat(),
            "checks": checks,
            "ok": True,
        }
        path = args.artifact_dir / f"wg-smoke-{suffix}.json"
        path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(artifact, indent=2))
        print(f"[PASS] wrote {path}")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
