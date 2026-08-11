#!/usr/bin/env python3
"""Fill one Phase 19 pilot artifact pack (controlled same-host / offline gates).

Writes a checklist JSON under artifacts/phase19_pilot_<stamp>/ covering hardware,
network notes, chaos, WG linux mock, Phase 18 WG, and outcome. When --base-url is
reachable, also runs live coexistence + chaos live probes.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def run(cmd: list[str], *, cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "ok": proc.returncode == 0,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-30:]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--artifact-dir", type=Path, default=None)
    parser.add_argument("--seconds", type=float, default=5.0)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = args.artifact_dir or (repo / "artifacts" / f"phase19_pilot_{stamp}")
    out.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    gates: dict[str, Any] = {}
    gates["phase19_skip"] = run(
        [py, "scripts/verify_phase19_local.py", "--skip-coordinator"], cwd=repo
    )
    gates["recovery"] = run([py, "scripts/verify_phase19_recovery.py"], cwd=repo)
    gates["chaos"] = run(
        [
            py,
            "scripts/verify_phase19_chaos.py",
            "--seconds",
            str(args.seconds),
            "--artifact",
            str(out / "chaos.json"),
        ],
        cwd=repo,
    )
    gates["phase18_wg"] = run(
        [
            py,
            "scripts/verify_phase18_wireguard_local.py",
            "--skip-coordinator",
            "--artifact",
            str(out / "phase18_wg.json"),
        ],
        cwd=repo,
    )
    gates["wg_linux"] = run(
        [
            py,
            "scripts/smoke_wireguard_linux_direct.py",
            "--force-mock",
            "--artifact-dir",
            str(out / "wg_linux"),
        ],
        cwd=repo,
    )
    if args.base_url:
        gates["live_pack"] = run(
            [
                py,
                "scripts/collect_phase19_live_artifacts.py",
                "--base-url",
                args.base_url,
                "--artifact-dir",
                str(out / "live"),
            ],
            cwd=repo,
        )
        gates["chaos_live"] = run(
            [
                py,
                "scripts/verify_phase19_chaos.py",
                "--seconds",
                str(args.seconds),
                "--base-url",
                args.base_url,
                "--artifact",
                str(out / "chaos_live.json"),
            ],
            cwd=repo,
        )

    checklist = {
        "coordinator_url": args.base_url or "(offline gates only)",
        "commit_sha": _git_sha(repo),
        "room_id_transport_mode": "see live/ when base-url set; offline uses mock WG/overlay",
        "provider_hardware": {
            "hostname": platform.node(),
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "gpu_models": "same-host CPU pilot (no multi-machine GPU)",
            "driver_cuda": "n/a for CPU pilot",
        },
        "network_notes": {
            "nat_type": "same-host loopback",
            "direct_vs_relay": "channel_select exercises direct + forced relay",
        },
        "metrics_export": "chaos + wg_linux artifacts in this pack",
        "dashboard_export": "run GET /api/v1/training-runs/{id}/dashboard after a live training run",
        "failure_recovery_notes": "corrupt checkpoint reject covered by chaos/recovery gates",
        "final_adapter_checkpoint_refs": "see training run output_dir when live LoRA executed",
        "gates": gates,
        "checklist_checked": {
            "coordinator_url_commit": True,
            "room_transport": bool(args.base_url),
            "hardware": True,
            "network": True,
            "metrics": True,
            "dashboard": False,
            "failure_recovery": True,
            "outcome": all(bool(g.get("ok")) for g in gates.values()),
        },
    }
    pack = {
        "generated_at": datetime.now(UTC).isoformat(),
        "pilot": checklist,
        "ok": all(bool(g.get("ok")) for g in gates.values()),
        "definition_of_complete": {
            "pilot_checklist": True,
            "chaos_artifact": True,
            "dialout_phase18_regression": "keep CI green separately",
        },
    }
    path = out / "pilot_pack.json"
    path.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(pack, indent=2))
    print(f"[{'PASS' if pack['ok'] else 'FAIL'}] wrote {path}")
    return 0 if pack["ok"] else 1


def _git_sha(repo: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
