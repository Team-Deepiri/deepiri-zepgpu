"""Short Phase 19 soak-smoke: overlay churn + integrity + checkpoint loop (CI-safe)."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
import uuid
from pathlib import Path

from deepiri_zepgpu.training.checkpoint import make_phase18_checkpoint_metadata
from deepiri_zepgpu.training.integrity import (
    NeutralOuterUpdate,
    ReplayGuard,
    accept_outer_update,
    payload_digest,
    sign_update,
)
from deepiri_zepgpu.training.recovery import load_verified_checkpoint, write_checkpoint_integrity
from deepiri_zepgpu.vpn.overlay import InMemoryOverlayTransport, OverlayPeer
from deepiri_zepgpu.vpn.overlay.memory import InMemoryOverlayHub


async def run_soak(*, seconds: float, rounds: int) -> dict[str, object]:
    started = time.perf_counter()
    hub = InMemoryOverlayHub()
    left = InMemoryOverlayTransport(local_peer_id="soak-a", hub=hub)
    right = InMemoryOverlayTransport(local_peer_id="soak-b", hub=hub)
    received = 0

    async def _recv(_src: str, _payload: bytes) -> None:
        nonlocal received
        received += 1

    right.register_receiver(_recv)
    await left.connect(OverlayPeer(peer_id="soak-b"))
    guard = ReplayGuard()
    key = "soak-room-key"
    checkpoint_ok = 0
    integrity_ok = 0
    iteration = 0
    with tempfile.TemporaryDirectory(prefix="zepgpu-p19-soak-") as tmp:
        root = Path(tmp)
        while time.perf_counter() - started < seconds and iteration < rounds:
            iteration += 1
            payload = f"round-{iteration}".encode()
            await left.send("soak-b", payload)
            update = NeutralOuterUpdate(
                model_revision="soak",
                parameter_names=["w"],
                shapes=[[1]],
                dtype="f32",
                round=iteration,
                worker_id="soak-a",
                run_id="soak-run",
                room_id="soak-room",
                payload_sha256=payload_digest(payload),
            )
            mac = sign_update(update, room_mac_key=key)
            accept_outer_update(update, payload, room_mac_key=key, mac_hex=mac, replay_guard=guard)
            integrity_ok += 1
            ckpt = root / f"ckpt-{iteration}"
            meta = make_phase18_checkpoint_metadata(
                run_id=str(uuid.uuid4()),
                step=iteration,
                outer_round=iteration,
                directory=ckpt,
                config={},
                model_state={},
                outer_optimizer_state={},
                active_membership=["soak-a", "soak-b"],
                compression_config={},
                placement={},
                island_ids=[],
            )
            write_checkpoint_integrity(ckpt, meta)
            load_verified_checkpoint(ckpt)
            checkpoint_ok += 1
            await asyncio.sleep(0)
    await left.close()
    await right.close()
    elapsed = time.perf_counter() - started
    return {
        "elapsed_seconds": elapsed,
        "iterations": iteration,
        "overlay_received": received,
        "integrity_ok": integrity_ok,
        "checkpoint_ok": checkpoint_ok,
        "ok": received == iteration and integrity_ok == iteration and checkpoint_ok == iteration,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=5.0, help="CI default short soak")
    parser.add_argument("--rounds", type=int, default=200)
    parser.add_argument("--artifact", type=Path, default=None)
    args = parser.parse_args()
    result = asyncio.run(run_soak(seconds=args.seconds, rounds=args.rounds))
    text = json.dumps(result, indent=2)
    print(text)
    if args.artifact:
        args.artifact.write_text(text + "\n", encoding="utf-8")
    if not result["ok"]:
        print("[FAIL] Phase 19 soak smoke")
        return 1
    print("[PASS] Phase 19 soak smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
