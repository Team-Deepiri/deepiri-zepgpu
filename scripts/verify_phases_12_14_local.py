#!/usr/bin/env python3
"""Local control-plane gate for Phases 12–14 on a single machine.

Covers: dial-out room → invite join → provider-token heartbeat (capabilities/path)
→ claim/lease → complete → revoke → WireGuard room coexistence.

Requires a running coordinator (see docs/room_network_local_testing.md).
No GPU or inbound provider ports required.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import Any

import httpx
from utils import auth_headers, elevate_to_researcher

from deepiri_zepgpu.node_agent.fake_gpu_metrics import FakeGpuConfig, build_fake_gpu_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Phases 12–14 dial-out control plane on one machine."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--password", default="phases-12-14-local-password")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--transport-mode",
        default="dialout",
        choices=("dialout", "wireguard", "overlay"),
        help="Primary room transport for the full join/heartbeat/claim/revoke matrix",
    )
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
            "first_name": "Phase",
            "last_name": "Gate",
        },
    )
    if register.is_error and register.status_code not in {400, 409}:
        raise RuntimeError(f"Registration failed ({register.status_code}): {register.text}")
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    login.raise_for_status()
    token = login.json().get("access_token")
    require(bool(token), "Login response did not include access_token")
    return str(token)


async def register_researcher(client: httpx.AsyncClient, username: str, password: str) -> str:
    await register_and_login(client, username, password)
    elevate_to_researcher(username)
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    login.raise_for_status()
    return str(login.json()["access_token"])


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
    for _ in range(40):
        response = await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers(owner_token))
        response.raise_for_status()
        task = dict(response.json())
        if task.get("status") == "completed":
            return task
        await asyncio.sleep(0.25)
    raise RuntimeError(f"Task {task_id} did not become completed through polling")


def heartbeat_payload(*, rtt_ms: float = 12.5, provider_mode: str = "dialout") -> dict[str, Any]:
    return {
        "is_online": True,
        "endpoint": "simulation://phases-12-14",
        "agent_version": "0.2.0",
        "node_name": "phases-12-14-provider",
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
            "path_class": "same_host",
            "coordinator_rtt_ms": rtt_ms,
            "measurement_kind": "measured",
        },
        "coordinator_rtt_ms": rtt_ms,
    }


async def run_gate(args: argparse.Namespace) -> None:
    suffix = uuid.uuid4().hex[:10]
    owner_username = f"p1214-owner-{suffix}"
    provider_username = f"p1214-provider-{suffix}"
    provider2_username = f"p1214-provider2-{suffix}"

    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"), timeout=args.timeout
    ) as client:
        health = await client.get("/api/v1/health")
        health.raise_for_status()
        require(health.json().get("status") == "healthy", "Coordinator is not healthy")
        print("[PASS] coordinator health")

        owner_token = await register_researcher(client, owner_username, args.password)
        provider_token = await register_and_login(client, provider_username, args.password)
        provider2_token = await register_and_login(client, provider2_username, args.password)
        print("[PASS] owner + two providers registered")

        # --- Primary room (parameterized transport_mode) ---
        primary = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(owner_token),
            json={
                "name": f"{args.transport_mode} Gate {suffix}",
                "description": "Phases 12-14 local gate",
                "transport_mode": args.transport_mode,
            },
        )
        primary.raise_for_status()
        primary_body = dict(primary.json())
        room_id = str(primary_body["id"])
        require(
            primary_body.get("transport_mode") == args.transport_mode,
            f"Room transport_mode != {args.transport_mode}",
        )
        require(
            primary_body.get("requires_wireguard_udp") is (args.transport_mode == "wireguard"),
            "requires_wireguard_udp mismatch",
        )
        print(f"[PASS] {args.transport_mode} room created ({room_id})")

        invite = await client.post(
            f"/api/v1/rooms/{room_id}/invites",
            headers=auth_headers(owner_token),
            json={"max_uses": 2},
        )
        invite.raise_for_status()
        invite_body = dict(invite.json())
        invite_code = str(invite_body["code"])
        require(bool(invite_body.get("join_command")), "Invite missing join_command one-liner")
        require("zepgpu-node join" in str(invite_body["join_command"]), "join_command malformed")
        print("[PASS] invite with join one-liner")

        join = await client.post(
            "/api/v1/rooms/join",
            headers=auth_headers(provider_token),
            json={
                "invite_code": invite_code,
                "node_name": "phases-12-14-provider",
                "provider_mode": args.transport_mode,
            },
        )
        join.raise_for_status()
        join_body = dict(join.json())
        peer_id = str(join_body["member"]["id"])
        peer_auth = join_body.get("auth_token")
        require(bool(peer_auth), "Join did not return room-scoped provider auth_token")
        peer_auth = str(peer_auth)
        print(f"[PASS] provider joined with provider token ({peer_id})")

        # Human JWT must not authorize provider heartbeat
        jwt_hb = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
            headers=auth_headers(provider_token),
            json=heartbeat_payload(provider_mode=args.transport_mode),
        )
        require(jwt_hb.status_code in {401, 403}, "Human JWT must not authorize heartbeat")
        print("[PASS] human JWT rejected on provider heartbeat")

        hb = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
            headers=auth_headers(peer_auth),
            json=heartbeat_payload(provider_mode=args.transport_mode),
        )
        hb.raise_for_status()
        hb_body = dict(hb.json())
        require(hb_body.get("is_online") is True, "Provider did not become online")
        require(hb_body.get("health_state"), "Heartbeat missing health_state")
        require(hb_body.get("path"), "Heartbeat missing path observability")
        require(hb_body.get("capabilities"), "Heartbeat missing capabilities")
        print(
            f"[PASS] provider-token heartbeat "
            f"(health={hb_body.get('health_state')}, "
            f"path={hb_body.get('path', {}).get('path_class')})"
        )

        nodes = await client.get(
            f"/api/v1/rooms/{room_id}/nodes", headers=auth_headers(owner_token)
        )
        nodes.raise_for_status()
        node = next((n for n in nodes.json() if str(n.get("id")) == peer_id), None)
        require(node is not None, "Provider missing from room nodes")
        require(node.get("gpu_count", 0) >= 1, "GPU inventory missing on node")
        require(node.get("path", {}).get("coordinator_rtt_ms") is not None, "RTT missing")
        print("[PASS] host sees capabilities/path/health on node list")

        # --- Claim / lease / complete (Phase 13) ---
        task_response = await client.post(
            "/api/v1/tasks",
            headers=auth_headers(owner_token),
            json={
                "name": "Phases 12-14 remote no-op",
                "func_name": "math.sqrt",
                "args": [4],
                "dispatch_mode": "room_auto",
                "room_id": room_id,
                "gpu_memory_mb": 0,
                "timeout_seconds": 60,
            },
        )
        if task_response.status_code >= 400:
            raise RuntimeError(
                f"task create failed: {task_response.status_code} {task_response.text}"
            )
        task = dict(task_response.json())
        assignment_id = str(task["assignment"]["assignment_id"])
        task_id = str(task["id"])
        print("[PASS] room-aware no-op dispatch")

        pending = await client.get(
            f"/api/v1/node-tasks/rooms/{room_id}/nodes/{peer_id}/tasks/pending",
            headers=auth_headers(peer_auth),
        )
        pending.raise_for_status()
        require(
            any(str(item.get("assignment_id")) == assignment_id for item in pending.json()),
            "Assignment not visible to provider",
        )

        claimed = await post_lifecycle(client, peer_auth, peer_id, assignment_id, "claim")
        require(claimed.get("claimed_at") or claimed.get("accepted_at"), "Claim missing timestamps")
        require(
            claimed.get("lease_expires_at") is not None
            or claimed.get("claim_generation") is not None,
            "Claim missing lease/generation fields",
        )
        claimed_retry = await post_lifecycle(client, peer_auth, peer_id, assignment_id, "claim")
        require(
            claimed_retry.get("status") == claimed.get("status"),
            "Duplicate claim was not idempotent",
        )
        print("[PASS] claim/lease idempotent")

        # Cross-room claim denial: join second dial-out room and try claim with wrong peer token
        other_room = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(owner_token),
            json={"name": f"Other Dialout {suffix}", "transport_mode": "dialout"},
        )
        other_room.raise_for_status()
        other_id = str(other_room.json()["id"])
        other_invite = await client.post(
            f"/api/v1/rooms/{other_id}/invites",
            headers=auth_headers(owner_token),
            json={"max_uses": 1},
        )
        other_invite.raise_for_status()
        join2 = await client.post(
            "/api/v1/rooms/join",
            headers=auth_headers(provider2_token),
            json={"invite_code": other_invite.json()["code"], "provider_mode": "dialout"},
        )
        join2.raise_for_status()
        peer2_id = str(join2.json()["member"]["id"])
        peer2_auth = str(join2.json()["auth_token"])
        cross = await client.post(
            f"/api/v1/node-tasks/{assignment_id}/claim",
            params={"peer_id": peer2_id},
            headers=auth_headers(peer2_auth),
            json={},
        )
        require(cross.status_code in {403, 404, 409}, "Cross-room claim must be rejected")
        print("[PASS] cross-room claim denied")

        await post_lifecycle(client, peer_auth, peer_id, assignment_id, "start")
        result_metadata = {
            "kind": "noop",
            "status": "ok",
            "message": "phases 12-14 gate",
            "simulated": True,
        }
        await post_lifecycle(
            client,
            peer_auth,
            peer_id,
            assignment_id,
            "complete",
            {"result_metadata": result_metadata},
        )
        completed = await wait_for_completed_task(client, owner_token, task_id)
        require(
            completed.get("assignment", {}).get("status") == "completed",
            "Assignment not completed",
        )
        print("[PASS] start/complete lifecycle")

        # Reconcile endpoint (Phase 13)
        reconcile = await client.post(
            f"/api/v1/node-tasks/rooms/{room_id}/nodes/{peer_id}/reconcile",
            headers=auth_headers(peer_auth),
            json={"assignment_ids": [assignment_id]},
        )
        reconcile.raise_for_status()
        print("[PASS] provider reconcile")

        # --- Revoke (Phase 12) ---
        revoke = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/revoke",
            headers=auth_headers(owner_token),
        )
        revoke.raise_for_status()
        require(revoke.json().get("revoked_at"), "Revoke response missing revoked_at")

        hb_after = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
            headers=auth_headers(peer_auth),
            json=heartbeat_payload(provider_mode=args.transport_mode),
        )
        require(hb_after.status_code in {401, 403}, "Revoked provider token must fail heartbeat")
        print("[PASS] host revoke stops provider heartbeat")

        # --- Coexistence: remaining transport modes on the same coordinator ---
        for mode in ("dialout", "wireguard", "overlay"):
            if mode == args.transport_mode:
                continue
            other = await client.post(
                "/api/v1/rooms",
                headers=auth_headers(owner_token),
                json={"name": f"{mode} Coexist {suffix}", "transport_mode": mode},
            )
            other.raise_for_status()
            body = dict(other.json())
            require(body.get("transport_mode") == mode, f"{mode} room mode wrong")
            require(
                body.get("requires_wireguard_udp") is (mode == "wireguard"),
                f"{mode} UDP flag wrong",
            )
        print("[PASS] dialout/wireguard/overlay coexistence on same coordinator")


def main() -> int:
    try:
        asyncio.run(run_gate(parse_args()))
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("Phases 12–14 local simulation PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
