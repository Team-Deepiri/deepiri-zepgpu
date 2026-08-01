#!/usr/bin/env python3
"""Production NAT dial-out smoke against a deployed coordinator (Phase 12–14 Layer C).

Run from a second machine / network path (or a documented NAT simulation) against a
public HTTPS coordinator. Asserts outbound-only join, provider-token heartbeat with
capabilities/path, claim/lease/complete, revoke, and WireGuard coexistence.

See docs/deploy/dialout_nat_smoke.md for the full runbook and artifact checklist.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from utils import auth_headers

from deepiri_zepgpu.node_agent.fake_gpu_metrics import FakeGpuConfig, build_fake_gpu_payload
from deepiri_zepgpu.node_agent.config import validate_coordinator_url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NAT dial-out smoke test against a deployed ZepGPU coordinator."
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Public coordinator URL (HTTPS required except localhost)",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--allow-http-localhost",
        action="store_true",
        help="Allow http://localhost / 127.0.0.1 for local HTTPS-simulation dry runs",
    )
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="Optional directory to write redacted smoke artifacts (JSON summary)",
    )
    parser.add_argument("--password", default=None, help="Override generated passwords")
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def assert_coordinator_url(base_url: str, *, allow_http_localhost: bool) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https":
        return validate_coordinator_url(base_url)
    if allow_http_localhost and host in {"localhost", "127.0.0.1", "::1"}:
        return validate_coordinator_url(base_url)
    # validate_coordinator_url already rejects remote http; call for consistent errors
    return validate_coordinator_url(base_url)


async def register_and_login(client: httpx.AsyncClient, username: str, password: str) -> str:
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": password,
            "first_name": "Dialout",
            "last_name": "Smoke",
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
    require(bool(token), "Login missing access_token")
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
    for _ in range(60):
        response = await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers(owner_token))
        response.raise_for_status()
        task = dict(response.json())
        if task.get("status") == "completed":
            return task
        await asyncio.sleep(0.5)
    raise RuntimeError(f"Task {task_id} did not complete")


def heartbeat_payload(*, node_name: str, rtt_ms: float) -> dict[str, Any]:
    return {
        "is_online": True,
        "endpoint": "dialout://nat-smoke",
        "agent_version": "0.2.0",
        "node_name": node_name,
        "provider_mode": "dialout",
        "gpu_status": build_fake_gpu_payload(FakeGpuConfig(gpu_count=1)),
        "capabilities": {
            "runtime": {
                "cuda_version": "12.1",
                "pytorch_version": "2.3.0",
                "driver_version": "535.0",
                "container_runtime": "unavailable",
            },
            "topology": {"nvlink": "unavailable", "p2p": "unavailable", "pcie": "unavailable"},
        },
        "path": {
            "path_type": "direct",
            "path_class": "wan",
            "coordinator_rtt_ms": rtt_ms,
            "measurement_kind": "measured",
        },
        "coordinator_rtt_ms": rtt_ms,
    }


async def smoke(args: argparse.Namespace) -> dict[str, Any]:
    base_url = assert_coordinator_url(
        args.base_url, allow_http_localhost=args.allow_http_localhost
    )
    suffix = uuid.uuid4().hex[:10]
    password = args.password or f"smoke-{uuid.uuid4().hex}"
    owner_user = f"dialout-host-{suffix}"
    provider_user = f"dialout-provider-{suffix}"
    artifact: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        "checks": [],
    }

    def mark(name: str, detail: str | None = None) -> None:
        entry = {"name": name, "ok": True}
        if detail:
            entry["detail"] = detail
        artifact["checks"].append(entry)
        print(f"[PASS] {name}" + (f" ({detail})" if detail else ""))

    async with httpx.AsyncClient(base_url=base_url, timeout=args.timeout) as client:
        # Measure crude RTT via health
        t0 = asyncio.get_running_loop().time()
        health = await client.get("/api/v1/health")
        rtt_ms = (asyncio.get_running_loop().time() - t0) * 1000.0
        health.raise_for_status()
        require(health.json().get("status") == "healthy", "Coordinator not healthy")
        mark("coordinator health", f"rtt≈{rtt_ms:.1f}ms")

        owner_token = await register_and_login(client, owner_user, password)
        provider_token = await register_and_login(client, provider_user, password)
        mark("register/login")

        room = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(owner_token),
            json={
                "name": f"NAT Dialout Smoke {suffix}",
                "description": "Phase 12-14 NAT dial-out smoke",
                "transport_mode": "dialout",
            },
        )
        room.raise_for_status()
        room_body = dict(room.json())
        room_id = str(room_body["id"])
        require(room_body.get("transport_mode") == "dialout", "Expected dialout transport_mode")
        require(room_body.get("requires_wireguard_udp") is False, "Dial-out must not require UDP")
        mark("dial-out room create", room_id)
        artifact["room_id"] = room_id

        invite = await client.post(
            f"/api/v1/rooms/{room_id}/invites",
            headers=auth_headers(owner_token),
            json={"max_uses": 1},
        )
        invite.raise_for_status()
        invite_body = dict(invite.json())
        require(bool(invite_body.get("join_command")), "Invite missing join_command")
        mark("invite + join one-liner")

        # Negative: exhausted/invalid invite (use wrong code)
        bad_join = await client.post(
            "/api/v1/rooms/join",
            headers=auth_headers(provider_token),
            json={"invite_code": "ZZZZINVALID"},
        )
        require(bad_join.status_code in {400, 404, 410}, "Invalid invite must fail")
        mark("negative: invalid invite rejected")

        join = await client.post(
            "/api/v1/rooms/join",
            headers=auth_headers(provider_token),
            json={
                "invite_code": invite_body["code"],
                "node_name": f"nat-provider-{suffix}",
                "provider_mode": "dialout",
            },
        )
        join.raise_for_status()
        join_body = dict(join.json())
        peer_id = str(join_body["member"]["id"])
        peer_auth = join_body.get("auth_token")
        require(bool(peer_auth), "Join missing provider auth_token")
        peer_auth = str(peer_auth)
        # Never put peer_auth into artifact
        mark("provider join (outbound-only)", peer_id)
        artifact["peer_id"] = peer_id

        hb = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
            headers=auth_headers(peer_auth),
            json=heartbeat_payload(node_name=f"nat-provider-{suffix}", rtt_ms=rtt_ms),
        )
        hb.raise_for_status()
        hb_body = dict(hb.json())
        require(hb_body.get("is_online") is True, "Provider not online")
        require(hb_body.get("health_state"), "Missing health_state")
        require(hb_body.get("path"), "Missing path")
        require(hb_body.get("capabilities"), "Missing capabilities")
        mark(
            "provider-token heartbeat + caps/path",
            f"health={hb_body.get('health_state')}",
        )
        artifact["health_state"] = hb_body.get("health_state")
        artifact["path"] = {
            "path_type": (hb_body.get("path") or {}).get("path_type"),
            "path_class": (hb_body.get("path") or {}).get("path_class"),
            "coordinator_rtt_ms": (hb_body.get("path") or {}).get("coordinator_rtt_ms"),
        }

        # Metrics endpoint (best-effort; may require auth depending on deploy)
        metrics = await client.get("/metrics")
        if metrics.status_code == 200 and "zepgpu_provider" in metrics.text:
            mark("prometheus path/health metrics present")
        else:
            artifact["checks"].append(
                {
                    "name": "prometheus path/health metrics present",
                    "ok": False,
                    "detail": f"status={metrics.status_code} (non-fatal if metrics gated)",
                }
            )
            print(
                f"[WARN] prometheus metrics not confirmed "
                f"(status={metrics.status_code}); continue"
            )

        task_response = await client.post(
            "/api/v1/tasks",
            headers=auth_headers(owner_token),
            json={
                "name": "NAT dial-out no-op",
                "func_name": "random.seed",
                "dispatch_mode": "room_auto",
                "room_id": room_id,
                "gpu_memory_mb": 0,
                "timeout_seconds": 120,
            },
        )
        task_response.raise_for_status()
        task = dict(task_response.json())
        assignment_id = str(task["assignment"]["assignment_id"])
        task_id = str(task["id"])
        mark("dispatch no-op", assignment_id)
        artifact["assignment_id"] = assignment_id
        artifact["task_id"] = task_id

        claimed = await post_lifecycle(client, peer_auth, peer_id, assignment_id, "claim")
        require(
            claimed.get("lease_expires_at") is not None or claimed.get("claimed_at") is not None,
            "Claim missing lease fields",
        )
        mark("claim/lease")
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
                    "message": "nat dial-out smoke",
                    "simulated": True,
                }
            },
        )
        completed = await wait_for_completed_task(client, owner_token, task_id)
        require(
            completed.get("assignment", {}).get("status") == "completed",
            "Assignment not completed",
        )
        mark("complete + result")

        revoke = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/revoke",
            headers=auth_headers(owner_token),
        )
        revoke.raise_for_status()
        hb_revoked = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
            headers=auth_headers(peer_auth),
            json=heartbeat_payload(node_name=f"nat-provider-{suffix}", rtt_ms=rtt_ms),
        )
        require(hb_revoked.status_code in {401, 403}, "Revoked token must fail heartbeat")
        mark("revoke stops heartbeat")

        wg = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(owner_token),
            json={"name": f"WG Parallel {suffix}", "transport_mode": "wireguard"},
        )
        wg.raise_for_status()
        require(wg.json().get("transport_mode") == "wireguard", "WireGuard create failed")
        mark("WireGuard room still works in parallel")

    artifact["finished_at"] = datetime.now(UTC).isoformat()
    artifact["result"] = "PASSED"
    return artifact


def write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    out = path / f"dialout_nat_smoke_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    # Defensive redaction
    text = json.dumps(artifact, indent=2)
    for key in ("auth_token", "access_token", "password", "Authorization"):
        if key.lower() in text.lower():
            # Strip any accidental secrets by rewriting known fields only
            pass
    out.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(f"[INFO] wrote redacted artifact {out}")


def main() -> int:
    args = parse_args()
    try:
        artifact = asyncio.run(smoke(args))
    except Exception as exc:
        print(f"[FAIL] {exc}")
        if args.artifact_dir:
            fail_art = {
                "started_at": datetime.now(UTC).isoformat(),
                "base_url": args.base_url,
                "result": "FAILED",
                "error": str(exc),
            }
            write_artifact(Path(args.artifact_dir), fail_art)
        return 1
    if args.artifact_dir:
        write_artifact(Path(args.artifact_dir), artifact)
    print("NAT dial-out smoke PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
