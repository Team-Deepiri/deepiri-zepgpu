#!/usr/bin/env python3
"""Phase 19 local verify: overlay mode, integrity, durable checkpoint, coexistence.

No GPU required. Expects a running coordinator (default http://127.0.0.1:8000)
for the room-coexistence checks; integrity/checkpoint/overlay in-process checks
always run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx

from deepiri_zepgpu.rooms.transport import (
    is_experimental_transport,
    normalize_transport_mode,
    requires_wireguard_udp,
)
from deepiri_zepgpu.training.checkpoint import make_phase18_checkpoint_metadata
from deepiri_zepgpu.training.integrity import (
    NeutralOuterUpdate,
    ReplayGuard,
    accept_outer_update,
    payload_digest,
    sign_update,
)
from deepiri_zepgpu.training.recovery import load_verified_checkpoint, write_checkpoint_integrity
from deepiri_zepgpu.vpn.overlay import (
    InMemoryOverlayTransport,
    OverlayPeer,
    build_overlay_transport,
)
from deepiri_zepgpu.vpn.overlay.memory import InMemoryOverlayHub


def require(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


async def verify_in_process(tmp: Path) -> dict[str, str]:
    require(normalize_transport_mode("overlay") == "overlay", "overlay mode invalid")
    require(is_experimental_transport("overlay") is False, "overlay still experimental")
    require(requires_wireguard_udp("overlay") is False, "overlay must not require WG UDP")

    hub = InMemoryOverlayHub()
    left = InMemoryOverlayTransport(local_peer_id="v0", hub=hub)
    right = InMemoryOverlayTransport(local_peer_id="v1", hub=hub)
    got: list[bytes] = []

    async def _recv(_src: str, payload: bytes) -> None:
        got.append(payload)

    right.register_receiver(_recv)
    await left.connect(OverlayPeer(peer_id="v1"))
    await left.send("v1", b"phase19-verify")
    require(got == [b"phase19-verify"], "overlay memory send failed")
    require(left.path_type("v1") == "direct", "expected direct path")
    await left.close()
    await right.close()

    # iroh fail-closed without package
    try:
        build_overlay_transport("iroh", local_peer_id="x")
        iroh_status = "bindings-present-unwired"
    except Exception as exc:
        iroh_status = f"fail-closed:{type(exc).__name__}"

    payload = b"outer-update"
    update = NeutralOuterUpdate(
        model_revision="rev1",
        parameter_names=["p0"],
        shapes=[[2, 2]],
        dtype="f32",
        round=1,
        worker_id="w0",
        run_id="run",
        room_id="room",
        payload_sha256=payload_digest(payload),
    )
    mac = sign_update(update, room_mac_key="k")
    accept_outer_update(update, payload, room_mac_key="k", mac_hex=mac, replay_guard=ReplayGuard())

    ckpt_dir = tmp / "ckpt"
    meta = make_phase18_checkpoint_metadata(
        run_id="run",
        step=1,
        outer_round=1,
        directory=ckpt_dir,
        config={},
        model_state={},
        outer_optimizer_state={},
        active_membership=["w0"],
        compression_config={},
        placement={},
        island_ids=[],
    )
    write_checkpoint_integrity(ckpt_dir, meta)
    loaded = load_verified_checkpoint(ckpt_dir)
    require(loaded.outer_round == 1, "checkpoint round mismatch")

    return {"overlay": "pass", "integrity": "pass", "checkpoint": "pass", "iroh": iroh_status}


async def verify_coordinator(base_url: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        health = await client.get("/api/v1/health")
        require(health.status_code == 200, f"health failed: {health.status_code}")

        async def register(username: str) -> str:
            password = "Phase19Verify!1"
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": username,
                    "email": f"{username}@example.com",
                    "password": password,
                    "first_name": "P19",
                    "last_name": "Verify",
                },
            )
            if resp.is_error and resp.status_code not in {400, 409}:
                raise AssertionError(
                    f"register failed for {username}: {resp.status_code} {resp.text}"
                )
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": password},
            )
            require(login.status_code == 200, f"login failed for {username}: {login.text}")
            return str(login.json()["access_token"])

        owner_token = await register(f"p19_owner_{suffix}")
        headers = {"Authorization": f"Bearer {owner_token}"}
        results: dict[str, str] = {}
        for mode in ("dialout", "wireguard", "overlay"):
            room = await client.post(
                "/api/v1/rooms",
                headers=headers,
                json={"name": f"P19 {mode} {suffix}", "transport_mode": mode},
            )
            require(room.status_code in {200, 201}, f"create {mode} room failed: {room.text}")
            body = room.json()
            require(body.get("transport_mode") == mode, f"mode mismatch for {mode}")
            if mode == "wireguard":
                require(body.get("requires_wireguard_udp") is True, "WG UDP flag wrong")
            else:
                require(body.get("requires_wireguard_udp") is False, f"{mode} UDP flag wrong")
            if mode == "overlay":
                require(body.get("transport_experimental") in (False, None), "overlay experimental")
            results[mode] = "pass"
        return results


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--skip-coordinator", action="store_true")
    parser.add_argument("--artifact", type=Path, default=None)
    args = parser.parse_args()

    tmp = Path("/tmp") / f"zepgpu-p19-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    artifact: dict[str, object] = {"in_process": await verify_in_process(tmp)}
    if not args.skip_coordinator:
        try:
            artifact["coordinator"] = await verify_coordinator(args.base_url.rstrip("/"))
        except Exception as exc:
            artifact["coordinator"] = {"error": str(exc)}
            print(json.dumps(artifact, indent=2))
            print(f"[FAIL] coordinator checks: {exc}", file=sys.stderr)
            return 1
    else:
        artifact["coordinator"] = "skipped"

    text = json.dumps(artifact, indent=2)
    print(text)
    if args.artifact:
        args.artifact.write_text(text + "\n", encoding="utf-8")
    print("[PASS] Phase 19 local verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
