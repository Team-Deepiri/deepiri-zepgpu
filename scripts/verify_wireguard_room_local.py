#!/usr/bin/env python3
"""WireGuard room local verify (mock tunnel; no wg-quick required).

Exercises: WG room create, AllowedIPs defaults, mock tunnel bring-up/teardown,
and three-mode coexistence create when a coordinator is available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx

from deepiri_zepgpu.rooms.transport import requires_wireguard_udp
from deepiri_zepgpu.vpn.mock_tunnel import bring_up_mock_tunnel, tear_down_mock_tunnel
from deepiri_zepgpu.vpn.wg_config import WireGuardConfigGenerator


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def verify_in_process(tmp: Path) -> dict[str, str]:
    require(requires_wireguard_udp("wireguard") is True, "WG must require UDP")
    gen = WireGuardConfigGenerator(vpn_ip="10.8.0.2", private_key="PRIVKEY")
    gen.add_peer("PUBKEY", endpoint="127.0.0.1:51820")
    text = gen.generate()
    require("10.8.0.0/24" in text, "room CIDR AllowedIPs missing")
    state = bring_up_mock_tunnel(
        room_id=str(uuid.uuid4()),
        peer_id=str(uuid.uuid4()),
        vpn_ip="10.8.0.5",
        state_path=tmp / "wg_mock.json",
        config_text=text,
    )
    require(state.up and state.vpn_ip == "10.8.0.5", "mock tunnel failed")
    require(tear_down_mock_tunnel(tmp / "wg_mock.json"), "teardown failed")
    return {"config": "pass", "mock_tunnel": "pass"}


async def verify_coordinator(base_url: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        health = await client.get("/api/v1/health")
        require(health.status_code == 200, "health failed")

        async def token_for(username: str) -> str:
            password = "WgVerify!1"
            reg = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": username,
                    "email": f"{username}@ex.com",
                    "password": password,
                    "first_name": "WG",
                    "last_name": "Verify",
                },
            )
            if reg.is_error and reg.status_code not in {400, 409}:
                raise AssertionError(f"register failed: {reg.status_code} {reg.text}")
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": password},
            )
            require(login.status_code == 200, f"login failed: {login.text}")
            return str(login.json()["access_token"])

        headers = {"Authorization": f"Bearer {await token_for(f'wg_owner_{suffix}')}"}
        out: dict[str, str] = {}
        for mode in ("wireguard", "dialout", "overlay"):
            resp = await client.post(
                "/api/v1/rooms",
                headers=headers,
                json={"name": f"WG verify {mode} {suffix}", "transport_mode": mode},
            )
            require(resp.status_code in {200, 201}, f"create {mode}: {resp.text}")
            body = resp.json()
            require(body.get("transport_mode") == mode, f"mode {mode}")
            require(
                body.get("requires_wireguard_udp") is (mode == "wireguard"),
                f"udp flag {mode}",
            )
            out[mode] = "pass"
        return out


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--skip-coordinator", action="store_true")
    parser.add_argument("--artifact", type=Path, default=None)
    parser.add_argument(
        "--require-real-wg",
        action="store_true",
        help="Fail unless wg-quick and /dev/net/tun are present",
    )
    args = parser.parse_args()
    tmp = Path("/tmp") / f"zepgpu-wg-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True, exist_ok=True)
    if args.require_real_wg:
        import shutil

        if shutil.which("wg-quick") is None or not Path("/dev/net/tun").exists():
            print("[FAIL] --require-real-wg: wg-quick or /dev/net/tun missing", file=sys.stderr)
            return 1
    artifact: dict[str, object] = {"in_process": verify_in_process(tmp)}
    if not args.skip_coordinator:
        try:
            artifact["coordinator"] = await verify_coordinator(args.base_url.rstrip("/"))
        except Exception as exc:
            artifact["coordinator"] = {"error": str(exc)}
            print(json.dumps(artifact, indent=2))
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 1
    else:
        artifact["coordinator"] = "skipped"
    print(json.dumps(artifact, indent=2))
    if args.artifact:
        args.artifact.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print("[PASS] WireGuard room local verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
