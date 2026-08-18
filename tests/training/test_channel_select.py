"""Unit/integration tests for training data-plane channel selection."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from deepiri_zepgpu.training.binary import BinaryEnvelope
from deepiri_zepgpu.training.channel_select import (
    DataPlaneEndpoint,
    build_worker_data_plane,
    ensure_peer_connected,
    publish_endpoint,
    select_direct_backend,
    wait_for_peer_endpoint,
)
from deepiri_zepgpu.training.lan import LanDirectChannel
from deepiri_zepgpu.training.relay import BinaryRelayStore
from deepiri_zepgpu.training.transport import PcclDirectChannel, TransferManager
from deepiri_zepgpu.vpn.overlay.adapter import OverlayDirectAdapter
from deepiri_zepgpu.vpn.overlay.base import OverlayPeer


def _envelope(payload: bytes = b"hello") -> BinaryEnvelope:
    return BinaryEnvelope(
        room_id=str(uuid4()),
        run_id=str(uuid4()),
        worker_id=str(uuid4()),
        transfer_id=str(uuid4()),
        round=1,
        payload_type="adapter_delta",
        shape=(len(payload),),
        dtype="f32",
        compression="none",
        payload=payload,
    )


@pytest.mark.asyncio
async def test_advertise_wildcard_prefers_vpn_ip() -> None:
    plane = await build_worker_data_plane(
        transport_mode="wireguard",
        credential="cred-wg",
        worker_id="w0",
        peer_id="p0",
        peer_worker_id="w1",
        listen_host="0.0.0.0",
        advertise_host="10.8.0.12",
    )
    try:
        assert plane.local_endpoint is not None
        assert plane.local_endpoint.host == "10.8.0.12"
    finally:
        await plane.stop()


def test_select_direct_backend_matrix() -> None:
    assert select_direct_backend("dialout") == "none"
    assert select_direct_backend("wireguard") == "lan"
    assert select_direct_backend("overlay") == "overlay"
    assert select_direct_backend("wireguard", force_relay=True) == "none"
    assert select_direct_backend("wg") == "lan"


@pytest.mark.asyncio
async def test_wireguard_lan_direct_metric_path() -> None:
    left = await build_worker_data_plane(
        transport_mode="wireguard",
        credential="cred-wg",
        worker_id="w0",
        peer_id="p0",
        peer_worker_id="w1",
        listen_host="127.0.0.1",
    )
    right = await build_worker_data_plane(
        transport_mode="wireguard",
        credential="cred-wg",
        worker_id="w1",
        peer_id="p1",
        peer_worker_id="w0",
        listen_host="127.0.0.1",
    )
    assert isinstance(left.channel, LanDirectChannel)
    assert left.local_endpoint is not None and right.local_endpoint is not None
    await left.connect_peer("w1", right.local_endpoint)
    await right.connect_peer("w0", left.local_endpoint)

    received: list[bytes] = []
    done = asyncio.Event()

    async def _recv(payload: bytes) -> None:
        received.append(payload)
        done.set()

    right.channel.register("w1", _recv)
    manager = TransferManager(direct=left.channel, relay=BinaryRelayStore(), max_retries=0)
    _, metric = await manager.send(_envelope(b"hello-wg"), "w1")
    assert metric.path == "direct"
    assert metric.bytes > 0
    await asyncio.wait_for(done.wait(), timeout=2.0)
    assert received
    await left.stop()
    await right.stop()


@pytest.mark.asyncio
async def test_overlay_memory_direct_and_force_relay_fallback() -> None:
    left = await build_worker_data_plane(
        transport_mode="overlay",
        credential="cred-ov",
        worker_id="w0",
        peer_id="p0",
        peer_worker_id="w1",
        overlay_backend="memory",
    )
    right = await build_worker_data_plane(
        transport_mode="overlay",
        credential="cred-ov",
        worker_id="w1",
        peer_id="p1",
        peer_worker_id="w0",
        overlay_backend="memory",
    )
    assert isinstance(left.channel, OverlayDirectAdapter)
    await left._overlay.connect(OverlayPeer(peer_id="w1"))
    await right._overlay.connect(OverlayPeer(peer_id="w0"))

    got: list[bytes] = []
    done = asyncio.Event()

    async def _recv(payload: bytes) -> None:
        got.append(payload)
        done.set()

    right.channel.register("w1", _recv)
    manager = TransferManager(direct=left.channel, relay=BinaryRelayStore(), max_retries=0)
    _, metric = await manager.send(_envelope(b"ov-direct"), "w1")
    assert metric.path == "direct"
    await asyncio.wait_for(done.wait(), timeout=2.0)
    assert got

    forced = await build_worker_data_plane(
        transport_mode="overlay",
        credential="cred-ov",
        worker_id="w2",
        peer_id="p2",
        peer_worker_id="w3",
        force_relay=True,
    )
    assert isinstance(forced.channel, PcclDirectChannel)
    await left.stop()
    await right.stop()
    await forced.stop()


@pytest.mark.asyncio
async def test_unconnected_peer_falls_back_to_relay() -> None:
    plane = await build_worker_data_plane(
        transport_mode="wireguard",
        credential="cred",
        worker_id="w0",
        peer_id="p0",
        peer_worker_id="w1",
        listen_host="127.0.0.1",
    )
    manager = TransferManager(direct=plane.channel, relay=BinaryRelayStore(), max_retries=0)
    _, metric = await manager.send(_envelope(b"via-relay"), "w1")
    assert metric.path == "relay"
    await plane.stop()


@pytest.mark.asyncio
async def test_endpoint_publish_and_wait() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        publish_endpoint(root, "w0", DataPlaneEndpoint(host="127.0.0.1", port=4242, kind="vpn"))
        ep = await wait_for_peer_endpoint(root, "w0", timeout_seconds=1.0)
        assert ep.port == 4242
        plane = await build_worker_data_plane(
            transport_mode="wireguard",
            credential="c",
            worker_id="w1",
            peer_id="p1",
            peer_worker_id="w0",
        )
        attached = await ensure_peer_connected(
            plane,
            peer_worker_id="w0",
            endpoint_dir=root,
            identity_peer=None,
            timeout_seconds=1.0,
        )
        assert attached is not None
        await plane.stop()


@pytest.mark.asyncio
async def test_hmac_secret_mismatch_drops_direct_payload() -> None:
    left = await build_worker_data_plane(
        transport_mode="wireguard",
        credential="secret-a",
        worker_id="w0",
        peer_id="p0",
        peer_worker_id="w1",
        listen_host="127.0.0.1",
    )
    right = await build_worker_data_plane(
        transport_mode="wireguard",
        credential="secret-b",
        worker_id="w1",
        peer_id="p1",
        peer_worker_id="w0",
        listen_host="127.0.0.1",
    )
    assert left.local_endpoint is not None and right.local_endpoint is not None
    await left.connect_peer("w1", right.local_endpoint)
    await right.connect_peer("w0", left.local_endpoint)
    received: list[bytes] = []

    async def _recv(payload: bytes) -> None:
        received.append(payload)

    right.channel.register("w1", _recv)
    manager = TransferManager(direct=left.channel, relay=BinaryRelayStore(), max_retries=0)
    await manager.send(_envelope(b"mismatch"), "w1")
    await asyncio.sleep(0.3)
    assert received == []
    await left.stop()
    await right.stop()
