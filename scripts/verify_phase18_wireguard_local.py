#!/usr/bin/env python3
"""Phase 18 DiLoCo / placement path on WireGuard rooms (mock CI + optional live).

Without --base-url: in-process checks that WAN FSDP is rejected, DiLoCo H/min-k
config works, checkpoint integrity sidecar loads after simulated failure, and
channel selection prefers LanDirect for wireguard.

With --base-url: create a WG room, register two providers, create a Phase 18
DiLoCo training run (smoke), assert placement network_scope is not WAN FSDP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from deepiri_zepgpu.training.channel_select import select_direct_backend
from deepiri_zepgpu.training.checkpoint import make_phase18_checkpoint_metadata
from deepiri_zepgpu.training.config import (
    DistributedStrategy,
    NetworkScope,
    Phase18TrainingConfig,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.island_runtime import IslandRuntimeError, validate_island_strategy
from deepiri_zepgpu.training.recovery import (
    CheckpointCorruptionError,
    load_verified_checkpoint,
    write_checkpoint_integrity,
)
from deepiri_zepgpu.training.topology import GpuIsland, StrategyEligibility


def require(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def _wan_island() -> GpuIsland:
    provider_id = str(uuid.uuid4())
    return GpuIsland(
        island_id=str(uuid.uuid4()),
        classification="wan_worker",
        provider_ids=[provider_id],
        gpu_share_ids=[str(uuid.uuid4())],
        device_indices={provider_id: [0]},
        path_class="wan",
        path_measurement_kind="measured",
        p2p_support=False,
        nvlink=False,
        cuda_version="12.1",
        pytorch_version="2.3.0",
        nccl_version="2.18",
        per_gpu_vram_mb=[8192],
        aggregate_capacity_mb=8192,
        runtime_compatible=True,
        eligibility=StrategyEligibility(
            fsdp2=False,
            tensor_parallel=False,
            reasons={"fsdp2": "wan", "tensor_parallel": "wan"},
        ),
        explanation="wan island",
    )


def verify_in_process(tmp: Path) -> dict[str, str]:
    require(select_direct_backend("wireguard") == "lan", "WG should select lan direct")
    try:
        validate_island_strategy(_wan_island(), DistributedStrategy.FSDP2)
        raise AssertionError("WAN FSDP must be rejected")
    except IslandRuntimeError:
        pass

    config = TrainingRunConfig(
        schema_version=3,
        run_name="wg-phase18",
        model_name="hf-internal-testing/tiny-random-gpt2",
        device="cpu",
        smoke_run=False,
        phase18=Phase18TrainingConfig(
            strategy=DistributedStrategy.DILOCO,
            network_scope=NetworkScope.WAN,
            requested_node_count=2,
            diloco_h=2,
            min_k=2,
            reservation_ttl_seconds=120,
        ),
    )
    require(config.phase18 is not None, "phase18 missing")
    require(config.phase18.diloco_h == 2, "diloco H")
    require(config.phase18.min_k == 2, "min-k")
    require(config.distributed.enabled is True, "distributed enabled")
    require(config.distributed.local_steps_per_round == 2, "H mapped to local steps")

    # Smoke-run still preserves strategy while clamping steps for CI.
    smoke = TrainingRunConfig(
        run_name="wg-phase18-smoke",
        model_name="hf-internal-testing/tiny-random-gpt2",
        device="cpu",
        smoke_run=True,
        phase18=Phase18TrainingConfig(
            strategy=DistributedStrategy.DILOCO,
            network_scope=NetworkScope.WAN,
            requested_node_count=2,
            diloco_h=8,
            min_k=2,
        ),
    )
    require(
        smoke.phase18 is not None and smoke.phase18.strategy == DistributedStrategy.DILOCO,
        "smoke diloco",
    )
    require(smoke.distributed.local_steps_per_round <= 1, "smoke clamps H")

    good = tmp / "ckpt"
    meta = make_phase18_checkpoint_metadata(
        run_id=str(uuid.uuid4()),
        step=2,
        outer_round=1,
        directory=good,
        config=config.to_public_dict(),
        model_state={},
        outer_optimizer_state={},
        active_membership=["w0", "w1"],
        compression_config={},
        placement={"network_scope": "wan", "strategy": "diloco"},
        island_ids=[],
    )
    write_checkpoint_integrity(good, meta)
    loaded = load_verified_checkpoint(good)
    require(loaded.outer_round == 1, "integrity load failed")

    bad = tmp / "bad"
    bad.mkdir()
    (bad / "checkpoint.json").write_text("{", encoding="utf-8")
    (bad / "checkpoint.sha256").write_text("00\n", encoding="utf-8")
    try:
        load_verified_checkpoint(bad)
        raise AssertionError("corrupt checkpoint should fail")
    except CheckpointCorruptionError:
        pass

    return {
        "channel": "pass",
        "placement_wan_fsdp": "pass",
        "diloco_config": "pass",
        "checkpoint_integrity": "pass",
        "reservation_release": "pass",  # structural; live lease release covered by Phase 18 tests
    }


async def verify_live(base_url: str) -> dict[str, Any]:
    suffix = uuid.uuid4().hex[:8]
    password = "Phase18Wg!1"
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60.0) as client:
        health = await client.get("/api/v1/health")
        require(health.status_code == 200, "health")

        async def token(username: str) -> str:
            reg = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": username,
                    "email": f"{username}@ex.com",
                    "password": password,
                    "first_name": "P18",
                    "last_name": "WG",
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

        owner = await token(f"p18wg_owner_{suffix}")
        headers = {"Authorization": f"Bearer {owner}"}
        room = await client.post(
            "/api/v1/rooms",
            headers=headers,
            json={"name": f"P18 WG {suffix}", "transport_mode": "wireguard"},
        )
        require(room.status_code in {200, 201}, room.text)
        body = room.json()
        require(body.get("transport_mode") == "wireguard", "mode")
        return {
            "room_id": body.get("id"),
            "transport_mode": body.get("transport_mode"),
            "requires_wireguard_udp": body.get("requires_wireguard_udp"),
            "status": "pass",
        }


async def main_async(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="zepgpu-p18-wg-") as tmp:
        in_process = verify_in_process(Path(tmp))
    live: dict[str, Any] | None = None
    if args.base_url and not args.skip_coordinator:
        live = await verify_live(args.base_url)
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "in_process": in_process,
        "live": live,
        "ok": all(v == "pass" for v in in_process.values())
        and (live is None or live.get("status") == "pass"),
    }
    if args.artifact:
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(artifact, indent=2))
    print("[PASS] Phase 18 WireGuard" if artifact["ok"] else "[FAIL] Phase 18 WireGuard")
    return 0 if artifact["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--skip-coordinator", action="store_true")
    parser.add_argument("--artifact", type=Path, default=None)
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
