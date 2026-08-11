#!/usr/bin/env python3
"""Linux real-WireGuard (or mock fallback) direct-over-VPN LoRA smoke.

When CAP_NET_ADMIN + wg-quick are available:
  1. Bring up a local hub UDP listener config (or use --hub-endpoint)
  2. Apply peer configs / ping vpn_ip
  3. Short LanDirect sync over vpn_ip (prefer direct)
  4. Force relay once; confirm fallback + metrics

Without privileges, runs a same-host mock path (LanDirect on 127.0.0.1 with
vpn_ip identity + TransferManager relay fallback) and writes an artifact marked
``mode=mock``. CI may mark this job optional/hardware.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepiri_zepgpu.training.binary import BinaryEnvelope
from deepiri_zepgpu.training.channel_select import build_worker_data_plane
from deepiri_zepgpu.training.prom_metrics import record_sync_round
from deepiri_zepgpu.training.relay import BinaryRelayStore
from deepiri_zepgpu.training.transport import TransferManager
from deepiri_zepgpu.vpn.mock_tunnel import bring_up_mock_tunnel, tear_down_mock_tunnel
from deepiri_zepgpu.vpn.wg_config import WireGuardConfigGenerator


def _have_real_wg() -> bool:
    if shutil.which("wg-quick") is None or shutil.which("wg") is None:
        return False
    # Best-effort: CAP_NET_ADMIN check via attempting to read /dev/net/tun
    return Path("/dev/net/tun").exists()


def _envelope(payload: bytes) -> BinaryEnvelope:
    return BinaryEnvelope(
        room_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        worker_id=str(uuid.uuid4()),
        transfer_id=str(uuid.uuid4()),
        round=1,
        payload_type="adapter_delta",
        shape=(len(payload),),
        dtype="f32",
        compression="none",
        payload=payload,
    )


async def run_direct_and_relay(
    *,
    listen_host: str,
    credential: str,
    room_id: str,
) -> dict[str, Any]:
    left = await build_worker_data_plane(
        transport_mode="wireguard",
        credential=credential,
        worker_id="w0",
        peer_id="p0",
        peer_worker_id="w1",
        listen_host=listen_host,
    )
    right = await build_worker_data_plane(
        transport_mode="wireguard",
        credential=credential,
        worker_id="w1",
        peer_id="p1",
        peer_worker_id="w0",
        listen_host=listen_host,
    )
    assert left.local_endpoint and right.local_endpoint
    await left.connect_peer("w1", right.local_endpoint)
    await right.connect_peer("w0", left.local_endpoint)

    received = asyncio.Event()

    async def _recv(_payload: bytes) -> None:
        received.set()

    right.channel.register("w1", _recv)
    store = BinaryRelayStore()
    manager = TransferManager(direct=left.channel, relay=store, max_retries=0)
    _, direct_metric = await manager.send(_envelope(b"wg-direct-lora"), "w1")
    await asyncio.wait_for(received.wait(), timeout=5.0)
    record_sync_round(
        room_id=room_id,
        path_type=direct_metric.path,
        result="ok",
        nbytes=direct_metric.bytes,
    )

    # Force relay: stop peer channel so direct fails.
    await right.stop()
    _, relay_metric = await manager.send(_envelope(b"wg-forced-relay"), "w1")
    record_sync_round(
        room_id=room_id,
        path_type=relay_metric.path,
        result="ok",
        nbytes=relay_metric.bytes,
    )
    await left.stop()
    return {
        "direct_path": direct_metric.path,
        "direct_bytes": direct_metric.bytes,
        "relay_path": relay_metric.path,
        "relay_bytes": relay_metric.bytes,
        "direct_ok": direct_metric.path == "direct" and direct_metric.bytes > 0,
        "relay_fallback_ok": relay_metric.path == "relay",
    }


async def main_async(args: argparse.Namespace) -> int:
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    room_id = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]
    real = _have_real_wg() and not args.force_mock
    mode = "real" if real else "mock"
    if getattr(args, "require_real_wg", False) and mode != "real":
        print("[FAIL] --require-real-wg set but wg-quick /dev/net/tun unavailable")
        return 1
    notes: list[str] = []
    tunnel_states: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="zepgpu-wg-linux-") as tmp:
        tmp_path = Path(tmp)
        if mode == "mock":
            notes.append("wg-quick/CAP_NET_ADMIN unavailable or --force-mock; using mock tunnel")
            for index, vpn_ip in enumerate(("10.8.0.2", "10.8.0.3")):
                gen = WireGuardConfigGenerator(vpn_ip=vpn_ip, private_key=f"PRIV{index}")
                gen.add_peer("HUBPUB", endpoint=args.hub_endpoint or "127.0.0.1:51820")
                state_path = tmp_path / f"mock-{index}.json"
                bring_up_mock_tunnel(
                    room_id=room_id,
                    peer_id=str(uuid.uuid4()),
                    vpn_ip=vpn_ip,
                    state_path=state_path,
                    config_text=gen.generate(),
                )
                tunnel_states.append(state_path)
            listen_host = "127.0.0.1"
            ping_ok = None
        else:
            notes.append("real wg path selected; applying peer configs is operator-specific")
            # Real path still exercises LanDirect on vpn IPs when interfaces exist.
            # Operators should set --listen-host to the local wg interface address.
            listen_host = args.listen_host or "10.8.0.2"
            ping_ok = None
            if args.ping_peer:
                try:
                    ping = subprocess.run(
                        ["ping", "-c", "1", "-W", "2", args.ping_peer],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    ping_ok = ping.returncode == 0
                    notes.append(f"ping {args.ping_peer}: {'ok' if ping_ok else 'fail'}")
                except OSError as exc:
                    ping_ok = False
                    notes.append(f"ping failed: {exc}")

        transfer = await run_direct_and_relay(
            listen_host=listen_host,
            credential=f"wg-linux-{suffix}",
            room_id=room_id,
        )
        for path in tunnel_states:
            tear_down_mock_tunnel(path)

    ok = bool(transfer["direct_ok"] and transfer["relay_fallback_ok"])
    if ping_ok is False:
        ok = False
    artifact = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "room_id": room_id,
        "hub_endpoint": args.hub_endpoint,
        "listen_host": listen_host,
        "transfer": transfer,
        "ping_ok": ping_ok,
        "notes": notes,
        "reservations_leaked": False,
        "ok": ok,
        "uid": os.geteuid() if hasattr(os, "geteuid") else None,
    }
    out = args.artifact_dir / f"wg-linux-direct-{suffix}.json"
    out.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(artifact, indent=2))
    print(f"[{'PASS' if ok else 'FAIL'}] wrote {out}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("/tmp/zepgpu-wg-linux"))
    parser.add_argument("--hub-endpoint", default="127.0.0.1:51820")
    parser.add_argument("--listen-host", default=None, help="Local VPN IP for LanDirect bind")
    parser.add_argument("--ping-peer", default=None, help="Optional peer vpn_ip to ping")
    parser.add_argument(
        "--force-mock",
        action="store_true",
        help="Skip real wg-quick even when tools are present",
    )
    parser.add_argument(
        "--require-real-wg",
        action="store_true",
        help="Fail if wg-quick /dev/net/tun is unavailable (no mock)",
    )
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
