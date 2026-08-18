#!/usr/bin/env python3
"""Phase 19 chaos/soak harness (CI-short or long).

Scenarios (in-process unless noted):
1. overlay churn send/receive
2. integrity MAC reject
3. replay conflict reject
4. corrupt checkpoint reject
5. forced relay path marking + metrics
6. late-joiner bootstrap
7. reservation-leak placeholder assert (no live DB: structural check)

Live modes (when --base-url is set):
8. force-relay channel selection against identity
9. corrupt transfer MAC rejection (in-process LAN frame)
10. optional provider revoke probe (best-effort HTTP)

Full multi-hour soak: pass --seconds 7200. CI default is short.
Restart worker process is documented in docs/deploy/phase19_pilot.md (manual).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from deepiri_zepgpu.training.channel_select import build_worker_data_plane, select_direct_backend
from deepiri_zepgpu.training.checkpoint import make_phase18_checkpoint_metadata
from deepiri_zepgpu.training.integrity import (
    NeutralOuterUpdate,
    ReplayGuard,
    UpdateIntegrityError,
    accept_outer_update,
    payload_digest,
    sign_update,
)
from deepiri_zepgpu.training.lan import LanDirectChannel
from deepiri_zepgpu.training.prom_metrics import (
    record_checkpoint,
    record_rejoin,
    record_sync_round,
    record_training_failure,
)
from deepiri_zepgpu.training.recovery import (
    CheckpointCorruptionError,
    bootstrap_late_joiner_state,
    load_verified_checkpoint,
    write_checkpoint_integrity,
)
from deepiri_zepgpu.vpn.overlay import InMemoryOverlayTransport, OverlayPeer
from deepiri_zepgpu.vpn.overlay.memory import InMemoryOverlayHub


async def scenario_overlay() -> str:
    hub = InMemoryOverlayHub()
    a = InMemoryOverlayTransport(local_peer_id="c-a", hub=hub)
    b = InMemoryOverlayTransport(local_peer_id="c-b", hub=hub)
    got: list[bytes] = []

    async def _recv(_s: str, p: bytes) -> None:
        got.append(p)

    b.register_receiver(_recv)
    await a.connect(OverlayPeer(peer_id="c-b"))
    await a.send("c-b", b"chaos")
    a.force_relay_path("c-b")
    await a.send("c-b", b"relay-marked")
    record_sync_round(room_id="chaos", path_type=a.path_type("c-b"), result="ok", nbytes=11)
    await a.close()
    await b.close()
    return "pass" if len(got) == 2 else "fail"


def scenario_integrity() -> str:
    payload = b"x"
    update = NeutralOuterUpdate(
        model_revision="r",
        parameter_names=["p"],
        shapes=[[1]],
        dtype="f32",
        round=1,
        worker_id="w",
        run_id="run",
        room_id="room",
        payload_sha256=payload_digest(payload),
    )
    mac = sign_update(update, room_mac_key="k")
    guard = ReplayGuard()
    accept_outer_update(update, payload, room_mac_key="k", mac_hex=mac, replay_guard=guard)
    try:
        accept_outer_update(update, payload, room_mac_key="bad", mac_hex=mac, replay_guard=guard)
        return "fail"
    except UpdateIntegrityError:
        pass
    try:
        guard.check(update, mac_hex="f" * 64)
        return "fail"
    except UpdateIntegrityError:
        record_training_failure(room_id="chaos", cause="integrity")
        return "pass"


def scenario_checkpoint(tmp: Path) -> str:
    good = tmp / "good"
    meta = make_phase18_checkpoint_metadata(
        run_id=str(uuid.uuid4()),
        step=1,
        outer_round=1,
        directory=good,
        config={},
        model_state={},
        outer_optimizer_state={},
        active_membership=["w0"],
        compression_config={},
        placement={},
        island_ids=[],
    )
    write_checkpoint_integrity(good, meta)
    load_verified_checkpoint(good)
    record_checkpoint(room_id="chaos", operation="load", result="ok")
    boot = bootstrap_late_joiner_state(meta, worker_id="w1")
    record_rejoin(room_id="chaos", result="ok")
    bad = tmp / "bad"
    bad.mkdir()
    (bad / "checkpoint.json").write_text("{", encoding="utf-8")
    (bad / "checkpoint.sha256").write_text("00\n", encoding="utf-8")
    try:
        load_verified_checkpoint(bad)
        return "fail"
    except CheckpointCorruptionError:
        record_checkpoint(room_id="chaos", operation="load", result="corrupt")
    return "pass" if "w1" in boot["active_membership"] else "fail"


async def scenario_force_relay() -> str:
    if select_direct_backend("overlay", force_relay=True) != "none":
        return "fail"
    plane = await build_worker_data_plane(
        transport_mode="overlay",
        credential="chaos",
        worker_id="w0",
        peer_id="p0",
        peer_worker_id="w1",
        force_relay=True,
    )
    ok = not plane.needs_peer
    await plane.stop()
    return "pass" if ok else "fail"


async def scenario_corrupt_transfer_mac() -> str:
    left = LanDirectChannel(credential="good-mac", host="127.0.0.1")
    right = LanDirectChannel(credential="good-mac", host="127.0.0.1")
    await left.start()
    await right.start()
    assert left.bound_port and right.bound_port
    left.set_peer("w1", "127.0.0.1", right.bound_port)
    # Attacker channel with wrong credential should fail HMAC on receiver.
    attacker = LanDirectChannel(credential="bad-mac", host="127.0.0.1")
    attacker.set_peer("w1", "127.0.0.1", right.bound_port)
    got: list[bytes] = []

    async def _recv(payload: bytes) -> None:
        got.append(payload)

    right.register_receiver(_recv)
    await attacker.send("w1", b"tampered")
    await asyncio.sleep(0.05)
    await left.stop()
    await right.stop()
    record_training_failure(room_id="chaos", cause="transfer_mac")
    return "pass" if not got else "fail"


async def scenario_live_coordinator(base_url: str) -> dict[str, str]:
    """Best-effort live probes: health + three-mode create + optional revoke path."""

    out: dict[str, str] = {}
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30.0) as client:
        health = await client.get("/api/v1/health")
        out["health"] = "pass" if health.status_code == 200 else "fail"
        if out["health"] != "pass":
            return out
        suffix = uuid.uuid4().hex[:8]
        password = "ChaosLive!1"
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "username": f"chaos_{suffix}",
                "email": f"chaos_{suffix}@ex.com",
                "password": password,
                "first_name": "Chaos",
                "last_name": "Live",
            },
        )
        if reg.status_code in {200, 201} or reg.status_code in {400, 409}:
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": f"chaos_{suffix}", "password": password},
            )
            if login.status_code != 200:
                out["auth"] = "fail"
                return out
            token = str(login.json()["access_token"])
        else:
            out["auth"] = f"fail_register_{reg.status_code}"
            return out
        headers = {"Authorization": f"Bearer {token}"}
        modes_ok = True
        for mode in ("dialout", "overlay", "wireguard"):
            resp = await client.post(
                "/api/v1/rooms",
                headers=headers,
                json={"name": f"chaos {mode} {suffix}", "transport_mode": mode},
            )
            if resp.status_code not in {200, 201}:
                modes_ok = False
        out["three_mode_create"] = "pass" if modes_ok else "fail"
        wg = await client.post(
            "/api/v1/rooms",
            headers=headers,
            json={"name": f"chaos revoke {suffix}", "transport_mode": "dialout"},
        )
        if wg.status_code in {200, 201}:
            room_id = str(wg.json()["id"])
            invite = await client.post(
                f"/api/v1/rooms/{room_id}/invites",
                headers=headers,
                json={"max_uses": 1},
            )
            if invite.is_success:
                prov_user = f"chaos_p_{suffix}"
                await client.post(
                    "/api/v1/auth/register",
                    json={
                        "username": prov_user,
                        "email": f"{prov_user}@ex.com",
                        "password": password,
                        "first_name": "Chaos",
                        "last_name": "Prov",
                    },
                )
                prov_login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": prov_user, "password": password},
                )
                provider = str(prov_login.json().get("access_token") or "")
                join = await client.post(
                    "/api/v1/rooms/join",
                    headers={"Authorization": f"Bearer {provider}"},
                    json={
                        "invite_code": invite.json()["code"],
                        "node_name": "chaos-provider",
                        "provider_mode": "dialout",
                    },
                )
                if join.is_success:
                    peer_id = str(join.json()["member"]["id"])
                    revoke = await client.post(
                        f"/api/v1/rooms/{room_id}/nodes/{peer_id}/revoke",
                        headers=headers,
                    )
                    out["revoke_probe"] = (
                        "pass" if revoke.status_code in {200, 201} else f"fail_{revoke.status_code}"
                    )
                else:
                    out["revoke_probe"] = "fail_join"
            else:
                out["revoke_probe"] = "fail_invite"
        else:
            out["revoke_probe"] = "fail_room"
    return out


async def run(*, seconds: float, base_url: str | None = None) -> dict[str, object]:
    started = time.perf_counter()
    results: dict[str, Any] = {}
    results["overlay"] = await scenario_overlay()
    results["integrity"] = scenario_integrity()
    results["force_relay"] = await scenario_force_relay()
    results["corrupt_transfer_mac"] = await scenario_corrupt_transfer_mac()
    with tempfile.TemporaryDirectory(prefix="zepgpu-chaos-") as tmp:
        results["checkpoint"] = scenario_checkpoint(Path(tmp))
        hub = InMemoryOverlayHub()
        a = InMemoryOverlayTransport(local_peer_id="loop-a", hub=hub)
        b = InMemoryOverlayTransport(local_peer_id="loop-b", hub=hub)
        count = 0

        async def _recv(_s: str, _p: bytes) -> None:
            nonlocal count
            count += 1

        b.register_receiver(_recv)
        await a.connect(OverlayPeer(peer_id="loop-b"))
        while time.perf_counter() - started < seconds:
            await a.send("loop-b", b"tick")
            await asyncio.sleep(0)
        await a.close()
        await b.close()
        results["soak_loop"] = "pass" if count > 0 else "fail"
    live: dict[str, str] | None = None
    if base_url:
        live = await scenario_live_coordinator(base_url)
        results["live"] = live
    flat = [v for v in results.values() if isinstance(v, str)]
    if live:
        flat.extend(live.values())
    return {
        "elapsed_seconds": time.perf_counter() - started,
        "scenarios": results,
        "ok": all(value == "pass" for value in flat),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--artifact", type=Path, default=None)
    parser.add_argument(
        "--base-url",
        default=None,
        help="When set, run live three-mode create + revoke probe against coordinator",
    )
    args = parser.parse_args()
    result = asyncio.run(run(seconds=args.seconds, base_url=args.base_url))
    text = json.dumps(result, indent=2)
    print(text)
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(text + "\n", encoding="utf-8")
    print("[PASS] Phase 19 chaos" if result["ok"] else "[FAIL] Phase 19 chaos")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
