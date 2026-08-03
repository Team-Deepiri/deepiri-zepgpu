#!/usr/bin/env python3
"""Supervised Docker e2e: two zepgpu-training:local workers against live :8000.

Requires a built allowlisted image:
  docker build -f docker/Dockerfile.training.cpu -t zepgpu-training:local .
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
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
    smoke_training_config,
)

from deepiri_zepgpu.training.image_trust import ImageTrustPolicy
from deepiri_zepgpu.training.runtime import TrainingRuntime, TrainingRuntimeError
from deepiri_zepgpu.training.workload import TrainingWorkloadSpec

DEFAULT_OUTPUT = Path("/tmp/zepgpu-docker-wan")
DEFAULT_ALLOWLIST = Path(__file__).resolve().parents[1] / "docker" / "training-images.allowlist"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Docker Phase 17 WAN LoRA against live API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--worker-base-url",
        default="http://host.docker.internal:8000",
        help="Coordinator URL as seen from inside training containers",
    )
    parser.add_argument("--password", default="docker-wan-password")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Host work root (default: {DEFAULT_OUTPUT}/<run-suffix>)",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--compressor", choices=["zep", "demo", "none"], default="zep")
    parser.add_argument("--overlap", choices=["blocking", "eager"], default="eager")
    parser.add_argument("--image", default="zepgpu-training:local")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
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
    (work / "artifacts").mkdir(exist_ok=True)
    (work / "checkpoints").mkdir(exist_ok=True)
    (work / "logs").mkdir(exist_ok=True)
    (work / "identity.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    (work / "config.json").write_text(json.dumps(config_json, indent=2), encoding="utf-8")
    (work / "run.cred").write_text(credential, encoding="utf-8")
    (work / "provider.token").write_text(provider_token, encoding="utf-8")
    # Container runs as uid 999 (`zepgpu`). Make the bind-mounted work tree
    # readable/writable regardless of host uid mapping.
    for path in [work, *work.rglob("*")]:
        try:
            if path.is_dir():
                os.chmod(path, 0o777)
            else:
                os.chmod(path, 0o666)
        except OSError:
            pass


async def wait_run_state(
    client: httpx.AsyncClient,
    *,
    run_id: str,
    owner_token: str,
    wanted: set[str],
    timeout: float,
) -> dict[str, Any]:
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
        if state in {"failed", "cancelled", "timed_out"}:
            raise RuntimeError(f"run ended in {state}: {body.get('error')}")
        await asyncio.sleep(0.5)
    raise TimeoutError(f"timed out waiting for run states {sorted(wanted)}")


async def main_async(args: argparse.Namespace) -> int:
    output = (args.output_dir or (DEFAULT_OUTPUT / uuid.uuid4().hex[:8])).resolve()
    output.mkdir(parents=True, exist_ok=True)
    suffix = uuid.uuid4().hex[:8]
    password = args.password
    runtime = TrainingRuntime(
        trust_policy=(
            ImageTrustPolicy.from_file(args.allowlist)
            if args.allowlist.exists()
            else ImageTrustPolicy({args.image})
        ),
        allow_missing_allowlist=True,
    )
    handles: list[Any] = []

    async with httpx.AsyncClient(base_url=args.base_url, timeout=60.0) as client:
        owner_token = await register_and_login(client, f"docker-owner-{suffix}", password)
        provider_tokens = [
            await register_and_login(client, f"docker-provider{index}-{suffix}", password)
            for index in range(2)
        ]

        room = await client.post(
            "/api/v1/rooms",
            headers=auth_headers(owner_token),
            json={
                "name": f"docker-wan-{suffix}",
                "description": "Phase 17 Docker WAN LoRA",
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
                node_name=f"docker-worker-{index}",
                invite_code=invite_code,
            )
            peer_ids.append(peer_id)
            peer_auths.append(peer_auth)
            hb = await client.post(
                f"/api/v1/rooms/{room_id}/nodes/{peer_id}/heartbeat",
                headers=auth_headers(peer_auth),
                json=heartbeat_payload(f"docker-worker-{index}"),
            )
            hb.raise_for_status()

        config = smoke_training_config(
            run_name=f"docker-wan-{suffix}",
            compressor=args.compressor,
            overlap=args.overlap,
            startup_timeout_seconds=300,
        )
        create = await client.post(
            "/api/v1/training-runs",
            headers=auth_headers(owner_token),
            json={
                "room_id": room_id,
                "provider_ids": peer_ids,
                "config": config.model_dump(mode="json"),
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

        try:
            for index, peer_id in enumerate(peer_ids):
                work = output / f"worker-{index}"
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
                    config_json=config.model_dump(mode="json"),
                    credential=str(cred.json()["credential"]),
                    provider_token=peer_auths[index],
                )
                # Credentials live on the mounted work dir (env keys matching
                # filter_secrets would be stripped by TrainingWorkloadSpec).
                spec = TrainingWorkloadSpec(
                    image=args.image,
                    command=[
                        "python",
                        "-m",
                        "deepiri_zepgpu.training.process_worker",
                        "--work-dir",
                        "/workspace/run",
                        "--base-url",
                        args.worker_base_url,
                    ],
                    gpu_devices=[],
                    environment={
                        "PYTHONUNBUFFERED": "1",
                        "HF_HOME": "/workspace/run/hf-cache",
                        "TRANSFORMERS_CACHE": "/workspace/run/hf-cache",
                        "TORCH_HOME": "/workspace/run/torch-cache",
                    },
                    timeout_seconds=int(args.timeout),
                    memory_limit_mb=4096,
                    cpu_limit=2.0,
                    network_enabled=True,
                    privileged=False,
                    read_only_rootfs=True,
                    extra_hosts=["host.docker.internal:host-gateway"],
                    host_work_dir=work,
                    host_checkpoint_dir=work / "checkpoints",
                    host_artifact_dir=work / "artifacts",
                    host_log_dir=work / "logs",
                    mount_root=output,
                )
                handle = await runtime.start_docker(spec)
                handles.append(handle)
                if index == 0:
                    deadline = time.perf_counter() + 120.0
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
                        await asyncio.sleep(0.5)
                    else:
                        raise TimeoutError("first docker worker did not become ready")

            await wait_run_state(
                client,
                run_id=run_id,
                owner_token=owner_token,
                wanted={"ready"},
                timeout=min(args.timeout, 300.0),
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
                worker_states = {item.get("state") for item in body.get("workers", [])}
                # Prefer coordinator completed; also accept all workers completed
                # (heals pre-reconcile coordinators stuck in checkpointing).
                if state == "completed" or worker_states == {"completed"}:
                    exit_codes = []
                    for handle in handles:
                        exit_codes.append(await runtime.wait(handle, timeout_seconds=60.0))
                    if any(code != 0 for code in exit_codes):
                        raise TrainingRuntimeError(f"container non-zero exit: {exit_codes}")
                    summary = {
                        "run_id": run_id,
                        "room_id": room_id,
                        "state": "completed" if state == "completed" else "completed_workers",
                        "image": args.image,
                        "worker_dirs": [str(output / f"worker-{i}") for i in range(2)],
                        "container_names": [h.container_name for h in handles],
                    }
                    (output / "summary.json").write_text(
                        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
                    )
                    print(json.dumps(summary, indent=2))
                    return 0
                if state in {"failed", "cancelled", "timed_out"}:
                    raise RuntimeError(f"run ended in {state}: {body.get('error')}")
                await asyncio.sleep(1.0)
            raise TimeoutError("timed out waiting for docker training run completion")
        except Exception:
            with contextlib.suppress(Exception):
                await client.post(
                    f"/api/v1/training-runs/{run_id}/abort", headers=auth_headers(owner_token)
                )
            raise
        finally:
            for handle in handles:
                with contextlib.suppress(Exception):
                    await runtime.cleanup(handle)


def main() -> None:
    args = parse_args()
    try:
        raise SystemExit(asyncio.run(main_async(args)))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
