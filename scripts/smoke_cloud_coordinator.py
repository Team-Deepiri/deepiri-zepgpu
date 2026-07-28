"""Public coordinator smoke test for Phase 11 deployments."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

import httpx
from utils import auth_headers


async def smoke(base_url: str, timeout: float) -> None:
    suffix = uuid.uuid4().hex[:10]
    username = f"cloud-smoke-{suffix}"
    password = f"smoke-{uuid.uuid4().hex}"
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        health = await client.get("/api/v1/health")
        health.raise_for_status()
        print("[PASS] health endpoint")

        registered = await client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": password,
            },
        )
        if registered.is_error:
            raise RuntimeError(f"Registration failed ({registered.status_code}): {registered.text}")
        login = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        login.raise_for_status()
        token = str(login.json()["access_token"])
        print("[PASS] register/login")

        room = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(token),
            json={"name": f"Cloud Smoke {suffix}"},
        )
        room.raise_for_status()
        room_id = str(room.json()["id"])
        print("[PASS] room creation")

        invite = await client.post(
            f"/api/v1/rooms/{room_id}/invites",
            headers=auth_headers(token),
            json={"max_uses": 1},
        )
        invite.raise_for_status()
        print("[PASS] invite creation")

        rooms = await client.get("/api/v1/rooms", headers=auth_headers(token))
        rooms.raise_for_status()
        if not any(str(item.get("id")) == room_id for item in rooms.json()):
            raise RuntimeError("Created room is missing from public coordinator listing")
        print("[PASS] public room listing")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test a public ZepGPU coordinator.")
    parser.add_argument("--base-url", required=True, help="HTTPS coordinator URL")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    try:
        asyncio.run(smoke(args.base_url, args.timeout))
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return 1
    print("Cloud coordinator smoke PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
