#!/usr/bin/env python3
"""Local control-plane gate for Phases 10–16 on a single machine.

Extends the Phases 12–14 dial-out gate with:
  - invite/token/cross-room negative pack
  - training-run create + two workers + tiny relay exchange + abort/cleanup
  - redacted artifact under /tmp/zepgpu-phase10-16/

Requires a running coordinator (see docs/room_network_local_testing.md).
No GPU or inbound provider ports required. Training relay needs Redis.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from utils import auth_headers

from deepiri_zepgpu.node_agent.fake_gpu_metrics import FakeGpuConfig, build_fake_gpu_payload
from deepiri_zepgpu.training.binary import BinaryEnvelope

ARTIFACT_DIR = Path("/tmp/zepgpu-phase10-16")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Phases 10–16 control plane on one machine."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--password", default="phases-10-16-local-password")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--skip-training",
        action="store_true",
        help="Skip training-run / relay checks if Redis is unavailable.",
    )
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"auth_token", "access_token", "credential", "password", "token"}:
                out[key] = "<redacted>"
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        redacted = value
        redacted = re.sub(
            r"(Bearer\s+)[A-Za-z0-9._\-+=/]+",
            r"\1<redacted>",
            redacted,
            flags=re.IGNORECASE,
        )
        return redacted
    return value


def write_artifact(name: str, payload: dict[str, Any]) -> Path:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / name
    path.write_text(json.dumps(redact(payload), indent=2, sort_keys=True, default=str) + "\n")
    return path


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
    for _ in range(40):
        response = await client.get(f"/api/v1/tasks/{task_id}", headers=auth_headers(owner_token))
        response.raise_for_status()
        task = dict(response.json())
        if task.get("status") == "completed":
            return task
        await asyncio.sleep(0.25)
    raise RuntimeError(f"Task {task_id} did not become completed through polling")


def heartbeat_payload(*, rtt_ms: float = 12.5) -> dict[str, Any]:
    return {
        "is_online": True,
        "endpoint": "simulation://phases-10-16",
        "agent_version": "0.2.0",
        "node_name": "phases-10-16-provider",
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
            "coordinator_rtt_ms": rtt_ms,
            "measurement_kind": "measured",
        },
        "coordinator_rtt_ms": rtt_ms,
    }


async def create_dialout_room(
    client: httpx.AsyncClient, owner_token: str, name: str
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/rooms",
        headers=auth_headers(owner_token),
        json={"name": name, "description": "Phases 10-16 local gate", "transport_mode": "dialout"},
    )
    response.raise_for_status()
    body = dict(response.json())
    require(body.get("transport_mode") == "dialout", "Room transport_mode != dialout")
    return body


async def invite_and_join(
    client: httpx.AsyncClient,
    *,
    owner_token: str,
    provider_token: str,
    room_id: str,
    node_name: str,
    max_uses: int = 2,
) -> tuple[str, str, dict[str, Any]]:
    invite = await client.post(
        f"/api/v1/rooms/{room_id}/invites",
        headers=auth_headers(owner_token),
        json={"max_uses": max_uses},
    )
    invite.raise_for_status()
    invite_body = dict(invite.json())
    join = await client.post(
        "/api/v1/rooms/join",
        headers=auth_headers(provider_token),
        json={
            "invite_code": invite_body["code"],
            "node_name": node_name,
            "provider_mode": "dialout",
        },
    )
    join.raise_for_status()
    join_body = dict(join.json())
    peer_id = str(join_body["member"]["id"])
    peer_auth = join_body.get("auth_token")
    require(bool(peer_auth), "Join did not return room-scoped provider auth_token")
    return peer_id, str(peer_auth), invite_body


async def run_negative_pack(
    client: httpx.AsyncClient,
    *,
    owner_token: str,
    provider_token: str,
    room_id: str,
    peer_id: str,
    peer_auth: str,
    invite_code: str,
    assignment_id: str | None,
    other_peer_id: str,
    other_peer_auth: str,
) -> dict[str, Any]:
    results: dict[str, Any] = {}

    jwt_hb = await client.post(
        f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
        headers=auth_headers(provider_token),
        json=heartbeat_payload(),
    )
    require(jwt_hb.status_code in {401, 403}, "Human JWT must not authorize heartbeat")
    results["human_jwt_heartbeat"] = jwt_hb.status_code

    bad_invite = await client.post(
        "/api/v1/rooms/join",
        headers=auth_headers(provider_token),
        json={"invite_code": "NOTAREAL", "provider_mode": "dialout"},
    )
    require(bad_invite.status_code in {400, 404, 422}, "Bad invite must be rejected")
    results["bad_invite"] = bad_invite.status_code

    reuse = await client.post(
        "/api/v1/rooms/join",
        headers=auth_headers(provider_token),
        json={"invite_code": invite_code, "provider_mode": "dialout"},
    )
    # Already a member or invite still valid with remaining uses — either way, token misuse below.
    results["invite_reuse_status"] = reuse.status_code

    forged = await client.post(
        f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
        headers=auth_headers("forged-provider-token"),
        json=heartbeat_payload(),
    )
    require(forged.status_code in {401, 403}, "Forged provider token must fail")
    results["forged_token"] = forged.status_code

    if assignment_id:
        cross = await client.post(
            f"/api/v1/node-tasks/{assignment_id}/claim",
            params={"peer_id": other_peer_id},
            headers=auth_headers(other_peer_auth),
            json={},
        )
        require(cross.status_code in {403, 404, 409}, "Cross-room claim must be rejected")
        results["cross_room_claim"] = cross.status_code

    # Cross-room heartbeat: other room's token against this peer.
    cross_hb = await client.post(
        f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
        headers=auth_headers(other_peer_auth),
        json=heartbeat_payload(),
    )
    require(cross_hb.status_code in {401, 403, 404}, "Cross-room token must fail heartbeat")
    results["cross_room_heartbeat"] = cross_hb.status_code
    return results


async def run_training_pack(
    client: httpx.AsyncClient,
    *,
    owner_token: str,
    room_id: str,
    peer_ids: list[str],
    peer_auths: list[str],
) -> dict[str, Any]:
    create = await client.post(
        "/api/v1/training-runs",
        headers=auth_headers(owner_token),
        json={
            "room_id": room_id,
            "provider_ids": peer_ids,
            "config": {
                "run_name": "phases-10-16-smoke",
                "smoke_run": True,
                "startup_timeout_seconds": 30,
                "device": "cpu",
            },
        },
    )
    if create.status_code == 404:
        raise RuntimeError("Training-run API not mounted (404)")
    create.raise_for_status()
    run = dict(create.json())
    require(len(run.get("workers") or []) == 2, "Expected two training workers")
    workers = {str(w["peer_id"]): str(w["id"]) for w in run["workers"]}

    credentials: dict[str, str] = {}
    for peer_id, peer_auth in zip(peer_ids, peer_auths, strict=True):
        cred = await client.post(
            f"/api/v1/training-runs/{run['id']}/workers/{workers[peer_id]}/credential",
            params={"peer_id": peer_id},
            headers=auth_headers(peer_auth),
        )
        cred.raise_for_status()
        credentials[peer_id] = str(cred.json()["credential"])

    source_peer, target_peer = peer_ids
    envelope = BinaryEnvelope(
        room_id=room_id,
        run_id=str(run["id"]),
        worker_id=workers[source_peer],
        transfer_id=str(uuid.uuid4()),
        round=1,
        payload_type="gradient",
        shape=(2,),
        dtype="float32",
        compression="none",
        payload=b"p1016",
    )
    encoded = envelope.encode()
    begin = await client.post(
        f"/api/v1/training-runs/relay/{envelope.transfer_id}/begin",
        params={"peer_id": source_peer},
        headers={
            **auth_headers(credentials[source_peer]),
            "ZepGPU-Room-ID": room_id,
            "ZepGPU-Run-ID": str(run["id"]),
            "ZepGPU-Target-Worker-ID": workers[target_peer],
            "ZepGPU-Total-Chunks": "1",
            "ZepGPU-Round": "1",
        },
    )
    begin.raise_for_status()
    chunk = await client.put(
        f"/api/v1/training-runs/relay/{envelope.transfer_id}/chunks/0",
        params={"peer_id": source_peer},
        headers={
            **auth_headers(credentials[source_peer]),
            "ZepGPU-Room-ID": room_id,
            "Content-Type": "application/octet-stream",
        },
        content=encoded,
    )
    chunk.raise_for_status()
    complete = await client.post(
        f"/api/v1/training-runs/relay/{envelope.transfer_id}/complete",
        params={"peer_id": source_peer},
        headers={
            **auth_headers(credentials[source_peer]),
            "ZepGPU-Room-ID": room_id,
        },
    )
    complete.raise_for_status()
    download = await client.get(
        f"/api/v1/training-runs/relay/{envelope.transfer_id}/payload",
        params={"peer_id": target_peer},
        headers={
            **auth_headers(credentials[target_peer]),
            "ZepGPU-Room-ID": room_id,
        },
    )
    download.raise_for_status()
    require(download.content == encoded, "Relay payload mismatch")

    # Cross-room relay denial
    other_room = await create_dialout_room(
        client, owner_token, f"Train Cross {uuid.uuid4().hex[:6]}"
    )
    cross = await client.post(
        f"/api/v1/training-runs/relay/{uuid.uuid4()}/begin",
        params={"peer_id": source_peer},
        headers={
            **auth_headers(credentials[source_peer]),
            "ZepGPU-Room-ID": str(other_room["id"]),
            "ZepGPU-Run-ID": str(run["id"]),
            "ZepGPU-Target-Worker-ID": workers[target_peer],
            "ZepGPU-Total-Chunks": "1",
            "ZepGPU-Round": "1",
        },
    )
    require(cross.status_code in {403, 404}, "Cross-room relay must be denied")

    cleanup = await client.delete(
        f"/api/v1/training-runs/relay/{envelope.transfer_id}",
        params={"peer_id": source_peer},
        headers={
            **auth_headers(credentials[source_peer]),
            "ZepGPU-Room-ID": room_id,
        },
    )
    # Delivered transfers may already be gone (404); otherwise owner abort clears them (204).
    require(cleanup.status_code in {204, 404}, f"Relay cleanup unexpected: {cleanup.status_code}")

    abort = await client.post(
        f"/api/v1/training-runs/{run['id']}/abort",
        headers=auth_headers(owner_token),
    )
    abort.raise_for_status()
    require(
        abort.json().get("state") in {"cancelled", "aborted", "failed"}, "Abort state unexpected"
    )

    return {
        "run_id": run["id"],
        "workers": list(workers.values()),
        "relay_bytes": len(encoded),
        "abort_state": abort.json().get("state"),
        "cross_room_relay": cross.status_code,
    }


async def run_gate(args: argparse.Namespace) -> None:
    suffix = uuid.uuid4().hex[:10]
    owner_username = f"p1016-owner-{suffix}"
    provider_username = f"p1016-provider-{suffix}"
    provider2_username = f"p1016-provider2-{suffix}"
    artifact: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "checks": {},
    }

    async with httpx.AsyncClient(
        base_url=args.base_url.rstrip("/"), timeout=args.timeout
    ) as client:
        health = await client.get("/api/v1/health")
        health.raise_for_status()
        require(health.json().get("status") == "healthy", "Coordinator is not healthy")
        print("[PASS] coordinator health")
        artifact["checks"]["health"] = "pass"

        owner_token = await register_and_login(client, owner_username, args.password)
        provider_token = await register_and_login(client, provider_username, args.password)
        provider2_token = await register_and_login(client, provider2_username, args.password)
        print("[PASS] owner + two providers registered")

        dialout = await create_dialout_room(client, owner_token, f"Dialout Gate {suffix}")
        room_id = str(dialout["id"])
        print(f"[PASS] dial-out room created ({room_id})")
        artifact["checks"]["room"] = {"room_id": room_id, "transport_mode": "dialout"}

        peer_id, peer_auth, invite_body = await invite_and_join(
            client,
            owner_token=owner_token,
            provider_token=provider_token,
            room_id=room_id,
            node_name="phases-10-16-provider",
        )
        invite_code = str(invite_body["code"])
        require(bool(invite_body.get("join_command")), "Invite missing join_command")
        print(f"[PASS] provider joined with provider token ({peer_id})")

        hb = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
            headers=auth_headers(peer_auth),
            json=heartbeat_payload(),
        )
        hb.raise_for_status()
        hb_body = dict(hb.json())
        require(hb_body.get("is_online") is True, "Provider did not become online")
        require(hb_body.get("health_state"), "Heartbeat missing health_state")
        require(hb_body.get("path"), "Heartbeat missing path observability")
        print(
            f"[PASS] provider-token heartbeat "
            f"(health={hb_body.get('health_state')}, "
            f"path={hb_body.get('path', {}).get('path_class')})"
        )

        # Second provider in a different room (for cross-room negatives + training).
        other_room = await create_dialout_room(client, owner_token, f"Other Dialout {suffix}")
        other_id = str(other_room["id"])
        peer2_id, peer2_auth, _ = await invite_and_join(
            client,
            owner_token=owner_token,
            provider_token=provider2_token,
            room_id=other_id,
            node_name="phases-10-16-provider2",
            max_uses=1,
        )
        await client.post(
            f"/api/v1/rooms/{other_id}/nodes/{peer2_id}/heartbeat",
            headers=auth_headers(peer2_auth),
            json=heartbeat_payload(rtt_ms=18.0),
        )

        # Claim / lease / complete
        task_response = await client.post(
            "/api/v1/tasks",
            headers=auth_headers(owner_token),
            json={
                "name": "Phases 10-16 remote no-op",
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

        claimed = await post_lifecycle(client, peer_auth, peer_id, assignment_id, "claim")
        accepted = await post_lifecycle(client, peer_auth, peer_id, assignment_id, "accept")
        require(
            claimed.get("status") == accepted.get("status"),
            "Claim/accept must share assignment status",
        )
        print("[PASS] claim/accept same status")

        await post_lifecycle(client, peer_auth, peer_id, assignment_id, "start")
        await post_lifecycle(
            client,
            peer_auth,
            peer_id,
            assignment_id,
            "complete",
            {"result_metadata": {"kind": "noop", "status": "ok", "simulated": True}},
        )
        completed = await wait_for_completed_task(client, owner_token, task_id)
        require(
            completed.get("assignment", {}).get("status") == "completed",
            "Assignment not completed",
        )
        print("[PASS] start/complete lifecycle")
        artifact["checks"]["task"] = {"task_id": task_id, "assignment_id": assignment_id}

        negatives = await run_negative_pack(
            client,
            owner_token=owner_token,
            provider_token=provider_token,
            room_id=room_id,
            peer_id=peer_id,
            peer_auth=peer_auth,
            invite_code=invite_code,
            assignment_id=assignment_id,
            other_peer_id=peer2_id,
            other_peer_auth=peer2_auth,
        )
        print(f"[PASS] negative pack {negatives}")
        artifact["checks"]["negatives"] = negatives

        # Second provider joins primary room for training (two workers same room).
        invite2 = await client.post(
            f"/api/v1/rooms/{room_id}/invites",
            headers=auth_headers(owner_token),
            json={"max_uses": 1},
        )
        invite2.raise_for_status()
        join_train = await client.post(
            "/api/v1/rooms/join",
            headers=auth_headers(provider2_token),
            json={
                "invite_code": invite2.json()["code"],
                "node_name": "phases-10-16-train-b",
                "provider_mode": "dialout",
            },
        )
        # Provider2 may already be in other room only; join primary room for training.
        if join_train.status_code >= 400:
            # Create a dedicated training room with both providers.
            train_room = await create_dialout_room(client, owner_token, f"Train Room {suffix}")
            train_room_id = str(train_room["id"])
            p1_id, p1_auth, _ = await invite_and_join(
                client,
                owner_token=owner_token,
                provider_token=provider_token,
                room_id=train_room_id,
                node_name="train-a",
            )
            p2_id, p2_auth, _ = await invite_and_join(
                client,
                owner_token=owner_token,
                provider_token=provider2_token,
                room_id=train_room_id,
                node_name="train-b",
                max_uses=1,
            )
            for pid, auth in ((p1_id, p1_auth), (p2_id, p2_auth)):
                await client.post(
                    f"/api/v1/rooms/{train_room_id}/nodes/{pid}/heartbeat",
                    headers=auth_headers(auth),
                    json=heartbeat_payload(),
                )
            train_peers = [p1_id, p2_id]
            train_auths = [p1_auth, p2_auth]
            train_room_id_final = train_room_id
        else:
            train_peer2 = str(join_train.json()["member"]["id"])
            train_auth2 = str(join_train.json()["auth_token"])
            await client.post(
                f"/api/v1/rooms/{room_id}/nodes/{train_peer2}/heartbeat",
                headers=auth_headers(train_auth2),
                json=heartbeat_payload(),
            )
            train_peers = [peer_id, train_peer2]
            train_auths = [peer_auth, train_auth2]
            train_room_id_final = room_id

        if args.skip_training:
            print("[SKIP] training pack (--skip-training)")
            artifact["checks"]["training"] = "skipped"
        else:
            try:
                training = await run_training_pack(
                    client,
                    owner_token=owner_token,
                    room_id=train_room_id_final,
                    peer_ids=train_peers,
                    peer_auths=train_auths,
                )
                print(f"[PASS] training-run + relay + abort ({training.get('run_id')})")
                artifact["checks"]["training"] = training
            except Exception as exc:
                print(f"[WARN] training pack failed: {exc}")
                artifact["checks"]["training"] = {"error": str(exc)}
                raise

        # Revoke primary provider
        revoke = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/revoke",
            headers=auth_headers(owner_token),
        )
        revoke.raise_for_status()
        hb_after = await client.post(
            f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
            headers=auth_headers(peer_auth),
            json=heartbeat_payload(),
        )
        require(hb_after.status_code in {401, 403}, "Revoked provider token must fail heartbeat")
        print("[PASS] host revoke stops provider heartbeat")
        artifact["checks"]["revoke"] = "pass"

        wg = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(owner_token),
            json={"name": f"WG Coexist {suffix}", "transport_mode": "wireguard"},
        )
        wg.raise_for_status()
        require(wg.json().get("transport_mode") == "wireguard", "WireGuard room mode wrong")
        print("[PASS] WireGuard room coexistence on same coordinator")
        artifact["checks"]["wireguard_coexist"] = "pass"

    artifact["finished_at"] = datetime.now(UTC).isoformat()
    artifact["result"] = "PASSED"
    path = write_artifact(f"gate-{suffix}.json", artifact)
    print(f"[PASS] wrote redacted artifact {path}")


def main() -> int:
    try:
        asyncio.run(run_gate(parse_args()))
    except Exception as exc:
        fail_path = write_artifact(
            f"gate-fail-{uuid.uuid4().hex[:8]}.json",
            {"result": "FAILED", "error": str(exc), "at": datetime.now(UTC).isoformat()},
        )
        print(f"[FAIL] {exc}")
        print(f"[FAIL] artifact {fail_path}")
        return 1
    print("Phases 10–16 local simulation PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
