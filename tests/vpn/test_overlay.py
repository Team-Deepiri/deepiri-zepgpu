"""Phase 19.1 overlay transport unit tests."""

from __future__ import annotations

import asyncio

import pytest

from deepiri_zepgpu.rooms.transport import is_experimental_transport, normalize_transport_mode
from deepiri_zepgpu.training.binary import BinaryEnvelope
from deepiri_zepgpu.training.relay import BinaryRelayStore
from deepiri_zepgpu.training.transport import TransferManager
from deepiri_zepgpu.vpn.overlay import (
    InMemoryOverlayTransport,
    OverlayClosedError,
    OverlayDirectAdapter,
    OverlayPeer,
    OverlayUnavailable,
    build_overlay_transport,
)
from deepiri_zepgpu.vpn.overlay.factory import default_memory_hub
from deepiri_zepgpu.vpn.overlay.iroh_backend import iroh_available
from deepiri_zepgpu.vpn.overlay.memory import InMemoryOverlayHub
from deepiri_zepgpu.vpn.overlay.tcp import TcpOverlayTransport
from deepiri_zepgpu.vpn.overlay.udp import UdpOverlayTransport


@pytest.mark.unit
def test_iroh_dial_is_wired() -> None:
    from deepiri_zepgpu.vpn.overlay import iroh_dial_wired

    assert iroh_dial_wired() is True


@pytest.mark.unit
def test_overlay_mode_is_first_class() -> None:
    assert normalize_transport_mode("overlay") == "overlay"
    assert is_experimental_transport("overlay") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_overlay_connect_send_close() -> None:
    hub = InMemoryOverlayHub()
    left = InMemoryOverlayTransport(local_peer_id="a", hub=hub)
    right = InMemoryOverlayTransport(local_peer_id="b", hub=hub)
    received: list[tuple[str, bytes]] = []

    async def _recv(source: str, payload: bytes) -> None:
        received.append((source, payload))

    right.register_receiver(_recv)
    await left.connect(OverlayPeer(peer_id="b"))
    assert left.path_type("b") == "direct"
    await left.send("b", b"hello-overlay")
    assert received == [("a", b"hello-overlay")]
    await left.close()
    with pytest.raises(OverlayClosedError):
        await left.send("b", b"nope")
    await right.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_overlay_missing_peer_fails_closed() -> None:
    hub = InMemoryOverlayHub()
    left = InMemoryOverlayTransport(local_peer_id="a", hub=hub)
    with pytest.raises(OverlayUnavailable, match="not reachable"):
        await left.connect(OverlayPeer(peer_id="missing"))
    await left.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_overlay_double_close_is_safe() -> None:
    hub = InMemoryOverlayHub()
    transport = InMemoryOverlayTransport(local_peer_id="solo", hub=hub)
    await transport.close()
    await transport.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tcp_overlay_direct_roundtrip() -> None:
    left = TcpOverlayTransport(local_peer_id="tcp-a", credential="secret-run")
    right = TcpOverlayTransport(local_peer_id="tcp-b", credential="secret-run")
    received: list[bytes] = []
    done = asyncio.Event()

    async def _recv(source: str, payload: bytes) -> None:
        assert source == "tcp-a"
        received.append(payload)
        done.set()

    right.register_receiver(_recv)
    right_port = await right.start()
    left_port = await left.start()
    await left.connect(OverlayPeer(peer_id="tcp-b", host="127.0.0.1", port=right_port))
    await right.connect(OverlayPeer(peer_id="tcp-a", host="127.0.0.1", port=left_port))
    await left.send("tcp-b", b"tcp-payload")
    await asyncio.wait_for(done.wait(), timeout=2.0)
    assert received == [b"tcp-payload"]
    assert left.path_type("tcp-b") == "direct"
    await left.close()
    await right.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tcp_overlay_bad_hmac_dropped() -> None:
    left = TcpOverlayTransport(local_peer_id="tcp-a", credential="secret-a")
    right = TcpOverlayTransport(local_peer_id="tcp-b", credential="secret-b")
    received: list[bytes] = []

    async def _recv(_source: str, payload: bytes) -> None:
        received.append(payload)

    right.register_receiver(_recv)
    right_port = await right.start()
    await left.start()
    # TCP connect succeeds; mismatched HMAC means the receiver drops the frame.
    await left.connect(OverlayPeer(peer_id="tcp-b", host="127.0.0.1", port=right_port))
    await left.send("tcp-b", b"evil")
    await asyncio.sleep(0.1)
    assert received == []
    await left.close()
    await right.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_adapter_transfer_manager_direct() -> None:
    hub = InMemoryOverlayHub()
    left_overlay = InMemoryOverlayTransport(local_peer_id="w0", hub=hub)
    right_overlay = InMemoryOverlayTransport(local_peer_id="w1", hub=hub)
    left = OverlayDirectAdapter(overlay=left_overlay)
    right = OverlayDirectAdapter(overlay=right_overlay)
    store = BinaryRelayStore()
    manager = TransferManager(direct=left, relay=store, max_retries=0)
    received: list[BinaryEnvelope] = []

    async def _on_bytes(encoded: bytes) -> None:
        received.append(BinaryEnvelope.decode(encoded))

    right.register("w1", _on_bytes)
    await left_overlay.connect(OverlayPeer(peer_id="w1"))
    env = BinaryEnvelope(
        room_id="00000000-0000-4000-8000-000000000001",
        run_id="00000000-0000-4000-8000-000000000002",
        worker_id="00000000-0000-4000-8000-000000000003",
        transfer_id="00000000-0000-4000-8000-000000000004",
        round=1,
        payload_type="adapter_delta",
        shape=(2,),
        dtype="f32",
        compression="none",
        payload=b"delta-bytes",
    )
    _received_env, metric = await manager.send(env, target_worker_id="w1")
    assert metric.path == "direct"
    assert len(received) == 1
    assert received[0].payload == b"delta-bytes"
    await left_overlay.close()
    await right_overlay.close()


@pytest.mark.unit
def test_build_overlay_factory_and_iroh_fail_closed() -> None:
    hub = default_memory_hub()
    transport = build_overlay_transport("memory", local_peer_id="factory-a", hub=hub)
    assert isinstance(transport, InMemoryOverlayTransport)
    with pytest.raises(ValueError, match="unknown overlay backend"):
        build_overlay_transport("not-a-backend", local_peer_id="x")
    with pytest.raises(ValueError, match="requires a credential"):
        build_overlay_transport("iroh", local_peer_id="iroh-a")
    iroh = build_overlay_transport("iroh", local_peer_id="iroh-a", credential="secret")
    assert iroh.path_type() == "unknown"
    _ = iroh_available()
    quic = build_overlay_transport("quic", local_peer_id="quic-a", credential="secret")
    assert quic.path_type() == "unknown"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_udp_overlay_direct_roundtrip() -> None:
    left = UdpOverlayTransport(local_peer_id="udp-a", credential="secret-run")
    right = UdpOverlayTransport(local_peer_id="udp-b", credential="secret-run")
    received: list[bytes] = []
    done = asyncio.Event()

    async def _recv(source: str, payload: bytes) -> None:
        assert source == "udp-a"
        received.append(payload)
        done.set()

    right.register_receiver(_recv)
    right_port = await right.start()
    left_port = await left.start()
    await left.connect(OverlayPeer(peer_id="udp-b", host="127.0.0.1", port=right_port))
    await right.connect(OverlayPeer(peer_id="udp-a", host="127.0.0.1", port=left_port))
    await left.send("udp-b", b"udp-payload")
    await asyncio.wait_for(done.wait(), timeout=2.0)
    assert received == [b"udp-payload"]
    await left.close()
    await right.close()
