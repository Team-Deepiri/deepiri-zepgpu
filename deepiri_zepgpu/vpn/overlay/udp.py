"""HMAC-authenticated UDP overlay (QUIC-class datagrams, not TCP).

Large training payloads are chunked. This is the production overlay dial when
native iroh bindings are unavailable. WireGuard rooms do not use this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from deepiri_zepgpu.vpn.overlay.base import (
    OverlayClosedError,
    OverlayPeer,
    OverlayUnavailable,
    PathType,
)
from deepiri_zepgpu.vpn.overlay.metrics import (
    record_overlay_bytes,
    record_overlay_join,
    record_overlay_path,
)

logger = logging.getLogger(__name__)

BACKEND = "quic"
_MAGIC = b"ZQ1U"
_HEADER = struct.Struct("!4s16sHH32s")  # magic, msg_id, index, total, hmac
_CHUNK = 1024
_PROBE = b"\x00OVERLAY_UDP_PROBE"


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, owner: UdpOverlayTransport) -> None:
        self._owner = owner

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._owner._on_datagram(data, addr)


@dataclass
class UdpOverlayTransport:
    """Bind a UDP socket and exchange HMAC-chunked frames with overlay peers."""

    local_peer_id: str
    credential: str
    host: str = "127.0.0.1"
    port: int = 0
    backend_name: str = BACKEND
    max_frame_bytes: int = 64 * 1024 * 1024
    _transport: asyncio.DatagramTransport | None = field(default=None, init=False, repr=False)
    _bound_port: int | None = field(default=None, init=False, repr=False)
    _receiver: Callable[[str, bytes], Awaitable[None]] | None = field(
        default=None, init=False, repr=False
    )
    _peers: dict[str, OverlayPeer] = field(default_factory=dict, init=False, repr=False)
    _path_types: dict[str, PathType] = field(default_factory=dict, init=False, repr=False)
    _partial: dict[bytes, list[bytes | None]] = field(default_factory=dict, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.local_peer_id.strip():
            raise ValueError("local_peer_id cannot be empty")
        if not self.credential.strip():
            raise ValueError("overlay credential cannot be empty")

    def _mac(self, payload: bytes) -> bytes:
        return hmac.new(self.credential.encode("utf-8"), payload, hashlib.sha256).digest()

    @property
    def bound_port(self) -> int | None:
        return self._bound_port

    def register_receiver(self, receiver: Callable[[str, bytes], Awaitable[None]]) -> None:
        self._receiver = receiver

    async def start(self) -> int:
        self._ensure_open()
        if self._transport is not None:
            assert self._bound_port is not None
            return self._bound_port
        loop = asyncio.get_running_loop()
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self),
            local_addr=(self.host, self.port),
        )
        self._transport = transport
        sockname = transport.get_extra_info("sockname")
        self._bound_port = int(sockname[1])
        return self._bound_port

    def _on_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) < _HEADER.size:
            logger.debug("overlay UDP drop from %s: truncated header (%s bytes)", addr, len(data))
            return
        magic, msg_id, index, total, digest = _HEADER.unpack(data[: _HEADER.size])
        if magic != _MAGIC or total < 1 or index >= total:
            logger.debug(
                "overlay UDP drop from %s: bad magic or chunk index=%s total=%s",
                addr,
                index,
                total,
            )
            return
        chunk = data[_HEADER.size :]
        body = msg_id + struct.pack("!HH", index, total) + chunk
        if not hmac.compare_digest(digest, self._mac(body)):
            logger.warning(
                "overlay UDP drop from %s: HMAC mismatch (wrong data-plane secret?)", addr
            )
            return
        slots = self._partial.setdefault(msg_id, [None] * total)
        if len(slots) != total:
            self._partial[msg_id] = [None] * total
            slots = self._partial[msg_id]
        slots[index] = chunk
        if any(item is None for item in slots):
            return
        payload = b"".join(item for item in slots if item is not None)
        del self._partial[msg_id]
        if len(payload) < 2:
            logger.debug("overlay UDP drop from %s: empty reassembled payload", addr)
            return
        name_len = int.from_bytes(payload[:2], "big")
        if name_len < 1 or 2 + name_len > len(payload):
            logger.warning("overlay UDP drop from %s: malformed peer-id prefix", addr)
            return
        peer_name = payload[2 : 2 + name_len].decode("utf-8", errors="replace")
        body_payload = payload[2 + name_len :]
        if body_payload == _PROBE:
            return
        if self._receiver is not None:
            asyncio.create_task(self._receiver(peer_name, body_payload))

    async def connect(self, peer: OverlayPeer) -> None:
        self._ensure_open()
        if self._transport is None:
            await self.start()
        if not peer.host or peer.port is None:
            record_overlay_join(result="failure", backend=self.backend_name)
            raise OverlayUnavailable("UDP overlay peer requires host and port")
        try:
            await self._send_raw(peer.host, int(peer.port), _PROBE)
        except OverlayUnavailable:
            record_overlay_join(result="failure", backend=self.backend_name)
            raise
        self._peers[peer.peer_id] = peer
        self._path_types[peer.peer_id] = "direct"
        record_overlay_join(result="success", backend=self.backend_name)

    async def send(self, peer_id: str, payload: bytes) -> None:
        self._ensure_open()
        peer = self._peers.get(peer_id)
        if peer is None or not peer.host or peer.port is None:
            raise OverlayUnavailable(f"overlay peer {peer_id} is not connected")
        if len(payload) > self.max_frame_bytes:
            raise OverlayUnavailable("overlay payload exceeds max_frame_bytes")
        await self._send_raw(peer.host, int(peer.port), payload)
        path: PathType = self._path_types.get(peer_id, "direct")
        record_overlay_path(path_type=path, backend=self.backend_name)
        record_overlay_bytes(path_type=path, backend=self.backend_name, nbytes=len(payload))

    async def _send_raw(self, host: str, port: int, payload: bytes) -> None:
        if self._transport is None:
            raise OverlayUnavailable("UDP overlay is not started")
        framed = len(self.local_peer_id.encode("utf-8")).to_bytes(2, "big")
        framed += self.local_peer_id.encode("utf-8") + payload
        msg_id = os.urandom(16)
        chunks = [framed[i : i + _CHUNK] for i in range(0, len(framed), _CHUNK)] or [b""]
        total = len(chunks)
        try:
            for index, chunk in enumerate(chunks):
                body = msg_id + struct.pack("!HH", index, total) + chunk
                packet = _HEADER.pack(_MAGIC, msg_id, index, total, self._mac(body)) + chunk
                self._transport.sendto(packet, (host, port))
            await asyncio.sleep(0)
        except OSError as exc:
            raise OverlayUnavailable(str(exc)) from exc

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._peers.clear()
        self._path_types.clear()
        self._partial.clear()
        if self._transport is not None:
            self._transport.close()
            self._transport = None
            self._bound_port = None

    def path_type(self, peer_id: str | None = None) -> PathType:
        if peer_id is None:
            return "unknown"
        return self._path_types.get(peer_id, "unknown")

    def _ensure_open(self) -> None:
        if self._closed:
            raise OverlayClosedError("overlay transport is closed")
