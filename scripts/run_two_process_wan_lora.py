#!/usr/bin/env python3
"""Launch two OS-process WAN LoRA workers against a live coordinator (:8000).

Creates a dial-out room, two providers, a distributed training run, issues
per-worker credentials, spawns process workers, starts the run, and waits for
completion. Artifacts land under --output-dir.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from training_e2e_common import (  # noqa: E402
    auth_headers,
    heartbeat_payload,
    invite_and_join,
    register_and_login,
    run_reached_success,
    smoke_training_config,
)

DEFAULT_OUTPUT = Path("/tmp/zepgpu-two-process-wan")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Two-process Phase 17 WAN LoRA against live API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--password", default="two-process-wan-password")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--compressor", choices=["zep", "demo", "none"], default="zep")
    parser.add_argument("--overlap", choices=["blocking", "eager"], default="eager")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter for worker subprocesses",
    )
    return parser.parse_args()


def write_worker_files(
    work: Path,
    *,
    identity: dict[str, Any],
    config_json: dict[str, Any],
    credential: str,
    provider_token: str,
) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "identity.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    (work / "config.json").write_text(json.dumps(config_json, indent=2), encoding="utf-8")
    (work / "run.cred").write_text(credential, encoding="utf-8")
    (work / "provider.token").write_text(provider_token, encoding="utf-8")
    os.chmod(work, 0o700)
    for path in work.iterdir():
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)


async def wait_run_state(
    client: httpx.AsyncClient,
    *,
    run_id: str,
    owner_token: str,
    wanted: set[str],
    timeout: float,
    fail_states: set[str] | None = None,
) -> dict[str, Any]:
    fail = fail_states or {"failed", "cancelled", "timed_out"}
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        inspect = await client.get(
            f"/api/v1/training-runs/{run_id}", headers=auth_headers(owner_token)
        )
        inspect.raise_for_status()
        body = dict(inspect.json())
        state = str(body.get("state"))
        if state in wanted:
            return body
        if state in fail:
            raise RuntimeError(f"run ended in {state}: {body.get('error')}")
        await asyncio.sleep(0.5)
    raise TimeoutError(f"timed out waiting for run states {sorted(wanted)}")


async def main_async(args: argparse.Namespace) -> int:
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex[:8]
    password = args.password
    repo_root = Path(__file__).resolve().parents[1]

    async with httpx.AsyncClient(base_url=args.base_url, timeout=60.0) as client:
        owner_token = await register_and_login(client, f"owner-{suffix}", password)
        provider_tokens = [
            await register_and_login(client, f"provider{index}-{suffix}", password)
            for index in range(2)
        ]

        room = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(owner_token),
            json={
                "name": f"two-process-wan-{suffix}",
                "description": "Phase 17 two-process LoRA",
                "transport_mode": "dialout",
            },
        )
        room.raise_for_status()
        room_id = str(room.json()["id"])

        peer_ids: list[str] = []
        peer_auths: list[str] = []
        invite_code: str | None = None
        for index, token in enumerate(provider_tokens):
            peer_id, peer_auth, invite_code = await invite_and_join(
                client,
                owner_token=owner_token,
                provider_token=token,
                room_id=room_id,
                node_name=f"wan-worker-{index}",
                invite_code=invite_code,
            )
            peer_ids.append(peer_id)
            peer_auths.append(peer_auth)
            hb = await client.post(
                f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
                headers=auth_headers(peer_auth),
                json=heartbeat_payload(f"wan-worker-{index}"),
            )
            hb.raise_for_status()

        config = smoke_training_config(
            run_name=f"two-process-wan-{suffix}",
            compressor=args.compressor,
            overlap=args.overlap,
        )
        create = await client.post(
            "/api/v1/training-runs",
            headers=auth_headers(owner_token),
            json={
                "room_id": room_id,
                "provider_ids": peer_ids,
                "config": config.to_public_dict(),
            },
        )
        create.raise_for_status()
        run = create.json()
        run_id = str(run["id"])
        workers = {str(w["peer_id"]): str(w["id"]) for w in run["workers"]}
        peer_worker = {
            peer_ids[0]: workers[peer_ids[1]],
            peer_ids[1]: workers[peer_ids[0]],
        }

        processes: list[subprocess.Popen[Any]] = []
        work_dirs: list[Path] = []
        log_files: list[Any] = []
        try:
            for index, peer_id in enumerate(peer_ids):
                work = output / f"worker-{index}"
                work_dirs.append(work)
                cred = await client.post(
                    f"/api/v1/training-runs/{run_id}/workers/{workers[peer_id]}/credential",
                    params={"peer_id": peer_id},
                    headers=auth_headers(peer_auths[index]),
                )
                cred.raise_for_status()
                write_worker_files(
                    work,
                    identity={
                        "run_id": run_id,
                        "room_id": room_id,
                        "worker_id": workers[peer_id],
                        "peer_id": peer_id,
                        "peer_worker_id": peer_worker[peer_id],
                    },
                    config_json=config.to_public_dict(),
                    credential=str(cred.json()["credential"]),
                    provider_token=peer_auths[index],
                )
                log_path = work / "worker.log"
                log_file = log_path.open("w", encoding="utf-8")
                log_files.append(log_file)
                proc = subprocess.Popen(
                    [
                        args.python,
                        "-m",
                        "deepiri_zepgpu.training.process_worker",
                        "--work-dir",
                        str(work),
                        "--base-url",
                        args.base_url,
                    ],
                    cwd=str(repo_root),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                processes.append(proc)
                # Stagger worker-1 until worker-0 has reported ready (stable under load).
                if index == 0:
                    deadline = time.perf_counter() + 60.0
                    while time.perf_counter() < deadline:
                        inspect = await client.get(
                            f"/api/v1/training-runs/{run_id}",
                            headers=auth_headers(owner_token),
                        )
                        inspect.raise_for_status()
                        body = inspect.json()
                        worker0 = next(
                            item for item in body["workers"] if item["peer_id"] == peer_ids[0]
                        )
                        if worker0.get("ready_at"):
                            break
                        if proc.poll() not in (None, 0):
                            raise RuntimeError("first worker exited before ready")
                        await asyncio.sleep(0.25)
                    else:
                        raise TimeoutError("first worker did not become ready")

            body = await wait_run_state(
                client,
                run_id=run_id,
                owner_token=owner_token,
                wanted={"ready"},
                timeout=min(args.timeout, 180.0),
            )
            started = await client.post(
                f"/api/v1/training-runs/{run_id}/start", headers=auth_headers(owner_token)
            )
            started.raise_for_status()

            end = time.perf_counter() + args.timeout
            while time.perf_counter() < end:
                inspect = await client.get(
                    f"/api/v1/training-runs/{run_id}", headers=auth_headers(owner_token)
                )
                inspect.raise_for_status()
                body = inspect.json()
                state = body.get("state")
                if run_reached_success(body):
                    codes = [proc.wait(timeout=30) for proc in processes]
                    if any(code != 0 for code in codes):
                        raise RuntimeError(f"worker process non-zero exit: {codes}")
                    summary = {
                        "run_id": run_id,
                        "room_id": room_id,
                        "state": "completed" if state == "completed" else "completed_workers",
                        "worker_dirs": [str(path) for path in work_dirs],
                    }
                    (output / "summary.json").write_text(
                        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
                    )
                    print(json.dumps(summary, indent=2))
                    return 0
                if state in {"failed", "cancelled", "timed_out"}:
                    raise RuntimeError(f"run ended in {state}: {body.get('error')}")
                if any(proc.poll() not in (None, 0) for proc in processes):
                    raise RuntimeError("a worker process exited early with failure")
                await asyncio.sleep(1.0)
            raise TimeoutError("timed out waiting for training run completion")
        except Exception:
            with contextlib.suppress(Exception):
                await client.post(
                    f"/api/v1/training-runs/{run_id}/abort", headers=auth_headers(owner_token)
                )
            for proc in processes:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGTERM)
            for proc in processes:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=15)
                if proc.poll() is None:
                    proc.kill()
            raise
        finally:
            for handle in log_files:
                with contextlib.suppress(Exception):
                    handle.close()


def main() -> None:
    args = parse_args()
    try:
        raise SystemExit(asyncio.run(main_async(args)))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
