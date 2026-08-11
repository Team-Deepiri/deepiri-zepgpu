#!/usr/bin/env python3
"""Collect Phase 19 + WireGuard live coexistence artifacts against a coordinator.

Runs verify_phase19_local, verify_wireguard_room_local, and smoke_wireguard_hub
(no --skip-coordinator) when the coordinator is reachable. Always also records
offline in-process coexistence proofs so a dated pack exists even without Compose.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def run(cmd: list[str], *, cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-40:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
        "ok": proc.returncode == 0,
    }


def coordinator_up(base_url: str) -> bool:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/v1/health", timeout=3.0)
        return response.status_code == 200
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="Default: artifacts/phase19_live_YYYYMMDD_HHMMSS",
    )
    parser.add_argument(
        "--allow-offline",
        action="store_true",
        help="Exit 0 when coordinator is down but offline gates pass",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = args.artifact_dir or (repo / "artifacts" / f"phase19_live_{stamp}")
    out.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    offline = {
        "phase19_skip": run(
            [py, "scripts/verify_phase19_local.py", "--skip-coordinator"], cwd=repo
        ),
        "wireguard_skip": run(
            [py, "scripts/verify_wireguard_room_local.py", "--skip-coordinator"],
            cwd=repo,
        ),
    }
    live: dict[str, Any] | None = None
    reachable = coordinator_up(args.base_url)
    if reachable:
        live = {
            "phase19": run(
                [py, "scripts/verify_phase19_local.py", "--base-url", args.base_url],
                cwd=repo,
            ),
            "wireguard_room": run(
                [
                    py,
                    "scripts/verify_wireguard_room_local.py",
                    "--base-url",
                    args.base_url,
                ],
                cwd=repo,
            ),
            "wg_smoke": run(
                [
                    py,
                    "scripts/smoke_wireguard_hub.py",
                    "--base-url",
                    args.base_url,
                    "--artifact-dir",
                    str(out / "wg_smoke"),
                ],
                cwd=repo,
            ),
        }
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "coordinator_reachable": reachable,
        "offline": offline,
        "live": live,
        "ok": all(bool(item.get("ok")) for item in offline.values())
        and (live is None or all(bool(item.get("ok")) for item in live.values())),
        "notes": [] if reachable else ["coordinator unreachable; live join/noop deferred"],
    }
    if not reachable and not args.allow_offline:
        artifact["ok"] = False
        artifact["notes"].append("pass --allow-offline to accept offline-only pack")
    path = out / "live_coexistence.json"
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(artifact, indent=2))
    print(f"[{'PASS' if artifact['ok'] else 'FAIL'}] wrote {path}")
    return 0 if artifact["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
