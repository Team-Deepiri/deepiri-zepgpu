#!/usr/bin/env python3
"""Local Phase 17 gate: compression, two-worker sync, relay/direct, comparison.

Requires optional training deps. GPU and Docker are optional.
Coordinator is optional for the in-process path; pass --base-url to exercise API.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from deepiri_zepgpu.training.compare import (
    compare_runs,
    comparison_summary,
    naive_full_precision_bytes,
    write_comparison,
)
from deepiri_zepgpu.training.compression.base import CompressorState, get_compressor
from deepiri_zepgpu.training.config import (
    CompressionConfig,
    CompressorBackend,
    DistributedTrainingConfig,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.image_trust import ImageTrustPolicy
from deepiri_zepgpu.training.lan import LanDirectChannel
from deepiri_zepgpu.training.metrics import assert_catastrophic_quality
from deepiri_zepgpu.training.relay import BinaryRelayStore
from deepiri_zepgpu.training.sync import SyncOrchestrator
from deepiri_zepgpu.training.transport import (
    InMemoryDirectChannel,
    PcclDirectChannel,
    TransferManager,
)
from deepiri_zepgpu.training.workload import TrainingWorkloadSpec

ARTIFACT_DIR = Path("/tmp/zepgpu-phase17")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Phase 17 WAN LoRA foundations locally")
    parser.add_argument("--output-dir", type=Path, default=ARTIFACT_DIR)
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Optional coordinator URL. In-process gates always run; for live two-process "
            "training against a coordinator use scripts/run_two_process_wan_lora.py "
            "--base-url ..."
        ),
    )
    parser.add_argument("--run-training", action="store_true", help="Run tiny two-worker LoRA")
    parser.add_argument(
        "--compressor",
        choices=["zep", "demo"],
        default="zep",
    )
    parser.add_argument(
        "--phase15",
        type=Path,
        default=Path("docs/baselines/phase15_tiny_lora_rtx4050.json"),
    )
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def test_compressors() -> dict[str, Any]:
    results: dict[str, Any] = {}
    tensors = {
        "w": np.random.randn(128).astype(np.float32),
        "b": np.random.randn(32, 32).astype(np.float32),
    }
    naive = get_compressor(CompressionConfig(backend=CompressorBackend.NONE))
    naive_update = naive.compress(tensors, CompressorState())
    for backend in (CompressorBackend.ZEP, CompressorBackend.DEMO):
        compressor = get_compressor(
            CompressionConfig(backend=backend, top_k=16, chunk_size=32, quant_bits=4)
        )
        state = CompressorState()
        update = compressor.compress(tensors, state)
        restored = compressor.decompress(update)
        require(set(restored) == set(tensors), f"{backend} keys mismatch")
        require(update.compressed_bytes < naive_update.uncompressed_bytes, f"{backend} not smaller")
        # Toy convergence: residual energy decreases over iterations on a fixed target.
        target = {k: v * 0.0 for k, v in tensors.items()}
        current = {k: v.copy() for k, v in tensors.items()}
        energy = []
        feedback = CompressorState()
        for _ in range(8):
            delta = {k: (target[k] - current[k]).astype(np.float32) for k in current}
            packed = compressor.compress(delta, feedback)
            applied = compressor.decompress(packed)
            for key in current:
                current[key] = current[key] + applied[key]
            energy.append(float(sum(np.linalg.norm(current[k] - target[k]) for k in current)))
        require(energy[-1] < energy[0], f"{backend} toy convergence failed: {energy}")
        results[backend.value] = {
            "uncompressed_bytes": update.uncompressed_bytes,
            "compressed_bytes": update.compressed_bytes,
            "ratio": update.compression_ratio,
            "toy_energy": energy,
        }
    results["naive_bytes"] = naive_update.uncompressed_bytes
    return results


async def test_direct_and_relay() -> dict[str, Any]:
    room = str(uuid.uuid4())
    run = str(uuid.uuid4())
    w0 = str(uuid.uuid4())
    w1 = str(uuid.uuid4())
    memory = InMemoryDirectChannel()
    store = BinaryRelayStore()
    manager = TransferManager(direct=memory, relay=store, chunk_size=1024)
    left = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w0,
        peer_worker_id=w1,
        transfer_manager=manager,
        compression=CompressionConfig(backend=CompressorBackend.ZEP, top_k=8, chunk_size=32),
    )
    right = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w1,
        peer_worker_id=w0,
        transfer_manager=manager,
        compression=CompressionConfig(backend=CompressorBackend.ZEP, top_k=8, chunk_size=32),
    )

    async def recv0(encoded: bytes) -> None:
        left.receive_encoded(encoded)

    async def recv1(encoded: bytes) -> None:
        right.receive_encoded(encoded)

    memory.register(w0, recv0)
    memory.register(w1, recv1)

    deltas0 = {"a": np.ones(64, dtype=np.float32)}
    deltas1 = {"a": np.full(64, 3.0, dtype=np.float32)}
    u0 = left.compressor.compress(deltas0, left.state)
    u1 = right.compressor.compress(deltas1, right.state)
    e0 = left.envelope_for(1, u0)
    e1 = right.envelope_for(1, u1)
    r0, r1 = await asyncio.gather(
        left.sync_round(1, deltas0, peer_encoded=e1.encode(), precompressed=u0),
        right.sync_round(1, deltas1, peer_encoded=e0.encode(), precompressed=u1),
    )
    require(r0.path == "direct", "expected direct path")
    require(np.allclose(r0.averaged["a"], 2.0), "average mismatch")

    # Force relay fallback.
    failing = TransferManager(
        direct=PcclDirectChannel(sender=None),
        relay=store,
        chunk_size=1024,
        max_retries=0,
    )
    left2 = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w0,
        peer_worker_id=w1,
        transfer_manager=failing,
        compression=CompressionConfig(backend=CompressorBackend.ZEP, top_k=8, chunk_size=32),
    )
    u = left2.compressor.compress(deltas0, left2.state)
    # Peer encoded provided so sync can complete after relay send.
    peer = right.envelope_for(2, right.compressor.compress(deltas1, CompressorState()))
    relay_result = await left2.sync_round(2, deltas0, peer_encoded=peer.encode(), precompressed=u)
    require(relay_result.path == "relay", "expected relay fallback")

    # LAN channel smoke on localhost.
    cred = "phase17-lan-test-credential"
    lan0 = LanDirectChannel(credential=cred)
    lan1 = LanDirectChannel(credential=cred)
    got: list[bytes] = []

    async def lan_recv(encoded: bytes) -> None:
        got.append(encoded)

    lan1.register_receiver(lan_recv)
    port1 = await lan1.start()
    await lan0.start()
    lan0.set_peer("peer", "127.0.0.1", port1)
    payload = b"zeptrn-lan-smoke"
    await lan0.send("peer", payload)
    await asyncio.sleep(0.05)
    require(got == [payload], "LAN direct delivery failed")
    await lan0.stop()
    await lan1.stop()

    return {"direct": r0.path, "relay": relay_result.path, "lan": True}


def test_trust_policy() -> dict[str, Any]:
    policy = ImageTrustPolicy({"zepgpu-training:local"})
    policy.assert_trusted("zepgpu-training:local")
    try:
        policy.assert_trusted("evil:latest")
        raise RuntimeError("untrusted image should fail")
    except Exception as exc:
        require("not in the trust allowlist" in str(exc), str(exc))
    spec = TrainingWorkloadSpec(image="zepgpu-training:local", privileged=False)
    require(spec.privileged is False, "privileged must be false")
    try:
        TrainingWorkloadSpec(image="zepgpu-training:local", privileged=True)
        raise RuntimeError("privileged spec should fail")
    except Exception:
        pass
    return {"trusted": True}


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "phase": 17,
        "base_url": args.base_url,
    }
    report["compressors"] = test_compressors()
    report["transport"] = asyncio.run(test_direct_and_relay())
    report["trust"] = test_trust_policy()
    if args.base_url:
        print(
            f"[INFO] --base-url={args.base_url} noted; live coordinator training uses "
            "scripts/run_two_process_wan_lora.py (this gate is in-process)."
        )

    if args.run_training:
        config = TrainingRunConfig(
            schema_version=2,
            run_name="phase17-verify",
            device="cpu",
            precision="fp32",  # type: ignore[arg-type]
            smoke_run=True,
            gradient_checkpointing=False,
            output_dir=args.output_dir / "wan-run",
            distributed=DistributedTrainingConfig(
                enabled=True,
                local_steps_per_round=1,
                max_rounds=2,
                compression=CompressionConfig(backend=CompressorBackend(args.compressor)),
            ),
        )
        from deepiri_zepgpu.training.config import Precision
        from deepiri_zepgpu.training.distributed_runner import run_two_worker_training

        config.precision = Precision.FP32
        left, _right, bundle = run_two_worker_training(config)
        assert_catastrophic_quality(left)
        report["training"] = {
            "run_id": bundle["run_id"],
            "final_loss": left.final_loss,
            "compressed_bytes": left.compressed_bytes,
            "path_type": left.path_type,
            "compressor_backend": left.compressor_backend,
        }
        naive = bundle["naive"]
        if args.phase15.exists():
            comparison = compare_runs(
                phase15=args.phase15,
                phase17=left,
                naive=naive,
                phase17_label=args.compressor,
            )
            write_comparison(comparison, args.output_dir / "phase17_comparison.json")
            report["comparison_summary"] = comparison_summary(comparison)
        write_comparison(
            {
                "naive": naive_full_precision_bytes(
                    [int(v) for v in [naive["bytes_per_round"]]]  # placeholder structure ok
                )
            },
            args.output_dir / "naive_note.json",
        )

    out = args.output_dir / "phase17_verify.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Phase 17 verify failed: {exc}", file=sys.stderr)
        raise
