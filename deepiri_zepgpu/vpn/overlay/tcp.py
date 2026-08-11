"""Authenticated TCP overlay helper (LAN/CI stand-in, not the WireGuard path).

WireGuard rooms stay on UDP L3. Overlay ``tcp`` only exists so tests and LAN
rooms can exercise direct→metrics without native iroh/QUIC dial. Intended
overlay backend remains iroh (QUIC/UDP) via ``iroh_backend``.
Frames are length-prefixed and HMAC-SHA256 authenticated with the run credential.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import socket
import struct
from collections.abc import Awaitable, Callable
from contextlib import suppress
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

_HEADER = struct.Struct("!I32s")  # length, hmac-sha256
DEFAULT_MAX_FRAME_BYTES = 64 * 1024 * 1024
BACKEND = "tcp"
_PROBE_BODY = b"\x00OVERLAY_PROBE"


@dataclass
class TcpOverlayTransport:
    """Bind a local TCP listener and dial peers for authenticated binary frames."""

    local_peer_id: str
    credential: str
    host: str = "127.0.0.1"
    port: int = 0
    connect_timeout_seconds: float = 5.0
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    backend_name: str = BACKEND
    _server: asyncio.AbstractServer | None = field(default=None, init=False, repr=False)
    _bound_port: int | None = field(default=None, init=False, repr=False)
    _receiver: Callable[[str, bytes], Awaitable[None]] | None = field(
        default=None, init=False, repr=False
    )
    _peers: dict[str, OverlayPeer] = field(default_factory=dict, init=False, repr=False)
    _path_types: dict[str, PathType] = field(default_factory=dict, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.local_peer_id.strip():
            raise ValueError("local_peer_id cannot be empty")
        if not self.credential.strip():
            raise ValueError("overlay credential cannot be empty")
        if self.max_frame_bytes < 1:
            raise ValueError("max_frame_bytes must be positive")

    def _mac(self, payload: bytes) -> bytes:
        return hmac.new(self.credential.encode("utf-8"), payload, hashlib.sha256).digest()

    @property
    def bound_port(self) -> int | None:
        return self._bound_port

    def register_receiver(self, receiver: Callable[[str, bytes], Awaitable[None]]) -> None:
        self._receiver = receiver

    async def start(self) -> int:
        self._ensure_open()
        if self._server is not None:
            assert self._bound_port is not None
            return self._bound_port

        async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            peer_name = "unknown"
            try:
                header = await reader.readexactly(_HEADER.size)
                length, digest = _HEADER.unpack(header)
                if length > self.max_frame_bytes:
                    return
                payload = await reader.readexactly(length)
                if not hmac.compare_digest(digest, self._mac(payload)):
                    return
                # First frame after connect may include peer id length-prefixed UTF-8.
                if len(payload) < 2:
                    return
                name_len = int.from_bytes(payload[:2], "big")
                if name_len < 1 or 2 + name_len > len(payload):
                    return
                peer_name = payload[2 : 2 + name_len].decode("utf-8")
                body = payload[2 + name_len :]
                if body == _PROBE_BODY:
                    return
                if self._receiver is not None:
                    await self._receiver(peer_name, body)
            except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
                return
            finally:
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()

        self._server = await asyncio.start_server(_handle, host=self.host, port=self.port)
        sockets: list[socket.socket] = list(self._server.sockets or [])
        if not sockets:
            raise OverlayUnavailable("TCP overlay server failed to bind")
        self._bound_port = int(sockets[0].getsockname()[1])
        return self._bound_port

    async def connect(self, peer: OverlayPeer) -> None:
        self._ensure_open()
        if self._server is None:
            await self.start()
        if not peer.host or peer.port is None:
            record_overlay_join(result="failure", backend=self.backend_name)
            raise OverlayUnavailable("TCP overlay peer requires host and port")
        # Probe connectivity with an authenticated control frame (not delivered to apps).
        try:
            await self._dial(peer.host, int(peer.port), _PROBE_BODY)
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
            raise OverlayUnavailable(
                f"overlay payload {len(payload)} exceeds max_frame_bytes {self.max_frame_bytes}"
            )
        path: PathType = self._path_types.get(peer_id, "direct")
        try:
            await self._dial(peer.host, int(peer.port), payload)
        except OverlayUnavailable:
            record_overlay_path(path_type="unknown", backend=self.backend_name)
            raise
        record_overlay_path(path_type=path, backend=self.backend_name)
        record_overlay_bytes(path_type=path, backend=self.backend_name, nbytes=len(payload))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._peers.clear()
        self._path_types.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            self._bound_port = None

    def path_type(self, peer_id: str | None = None) -> PathType:
        if peer_id is None:
            if any(value == "direct" for value in self._path_types.values()):
                return "direct"
            if any(value == "relay" for value in self._path_types.values()):
                return "relay"
            return "unknown"
        return self._path_types.get(peer_id, "unknown")

    def mark_relay(self, peer_id: str) -> None:
        if peer_id not in self._peers:
            raise OverlayUnavailable(f"overlay peer {peer_id} is not connected")
        self._path_types[peer_id] = "relay"

    async def _dial(self, host: str, port: int, body: bytes) -> None:
        name = self.local_peer_id.encode("utf-8")
        if len(name) > 65535:
            raise OverlayUnavailable("local_peer_id too long")
        framed = len(name).to_bytes(2, "big") + name + body
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self.connect_timeout_seconds,
            )
        except (TimeoutError, OSError, ConnectionError) as exc:
            raise OverlayUnavailable(f"TCP overlay connect failed: {exc}") from exc
        try:
            writer.write(_HEADER.pack(len(framed), self._mac(framed)) + framed)
            await writer.drain()
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    def _ensure_open(self) -> None:
        if self._closed:
            raise OverlayClosedError("overlay transport is closed")
