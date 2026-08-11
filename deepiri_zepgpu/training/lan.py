"""LAN/same-host authenticated binary direct channel for Phase 17."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import socket
import struct
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field

from deepiri_zepgpu.training.transport import DirectUnavailable

_HEADER = struct.Struct("!I32s")  # length, hmac-sha256
DEFAULT_MAX_FRAME_BYTES = 64 * 1024 * 1024


@dataclass
class LanDirectChannel:
    """Length-prefixed authenticated binary peer channel over TCP.

    Each worker binds an ephemeral server socket and dials the peer. Messages are
    HMAC-SHA256 authenticated with the short-lived run credential so only room/run
    participants can inject envelopes.
    """

    credential: str
    host: str = "127.0.0.1"
    port: int = 0
    connect_timeout_seconds: float = 5.0
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    _server: asyncio.AbstractServer | None = field(default=None, init=False, repr=False)
    _bound_port: int | None = field(default=None, init=False, repr=False)
    _receiver: Callable[[bytes], Awaitable[None]] | None = field(
        default=None, init=False, repr=False
    )
    _targets: dict[str, tuple[str, int]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.credential or not self.credential.strip():
            raise ValueError("LAN direct credential cannot be empty")
        if self.max_frame_bytes < 1:
            raise ValueError("max_frame_bytes must be positive")

    def _mac(self, payload: bytes) -> bytes:
        return hmac.new(self.credential.encode("utf-8"), payload, hashlib.sha256).digest()

    def register_receiver(self, receiver: Callable[[bytes], Awaitable[None]]) -> None:
        self._receiver = receiver

    def register(self, worker_id: str, receiver: Callable[[bytes], Awaitable[None]]) -> None:
        """Compatibility with InMemoryDirectChannel.register for runner injection."""
        _ = worker_id
        self.register_receiver(receiver)

    def set_peer(self, worker_id: str, host: str, port: int) -> None:
        self._targets[worker_id] = (host, port)

    @property
    def bound_port(self) -> int | None:
        return self._bound_port

    async def start(self) -> int:
        if self._server is not None:
            assert self._bound_port is not None
            return self._bound_port

        async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    header = await reader.readexactly(_HEADER.size)
                    length, digest = _HEADER.unpack(header)
                    if length > self.max_frame_bytes:
                        raise PermissionError(
                            f"LAN frame length {length} exceeds max_frame_bytes "
                            f"{self.max_frame_bytes}"
                        )
                    payload = await reader.readexactly(length)
                    if not hmac.compare_digest(digest, self._mac(payload)):
                        raise PermissionError("LAN direct HMAC authentication failed")
                    if self._receiver is not None:
                        await self._receiver(payload)
            except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
                return
            except PermissionError:
                return
            finally:
                writer.close()
                with suppress(Exception):
                    await writer.wait_closed()

        self._server = await asyncio.start_server(_handle, host=self.host, port=self.port)
        sockets: list[socket.socket] = list(self._server.sockets or [])
        if not sockets:
            raise DirectUnavailable("LAN direct server failed to bind")
        self._bound_port = int(sockets[0].getsockname()[1])
        return self._bound_port

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        self._bound_port = None

    async def send(self, target_worker_id: str, encoded: bytes) -> None:
        if len(encoded) > self.max_frame_bytes:
            raise DirectUnavailable(
                f"LAN payload {len(encoded)} exceeds max_frame_bytes {self.max_frame_bytes}"
            )
        target = self._targets.get(target_worker_id)
        if target is None:
            raise DirectUnavailable(f"no LAN address for worker {target_worker_id}")
        host, port = target
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=self.connect_timeout_seconds,
            )
        except (TimeoutError, OSError, ConnectionError) as exc:
            raise DirectUnavailable(f"LAN direct connect failed: {exc}") from exc
        try:
            writer.write(_HEADER.pack(len(encoded), self._mac(encoded)) + encoded)
            await writer.drain()
        finally:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            _ = reader


@dataclass
class LanPairDirectChannel:
    """Routes sends to per-worker LAN channels for in-process two-worker loopback tests."""

    channels: dict[str, LanDirectChannel]

    def register(self, worker_id: str, receiver: Callable[[bytes], Awaitable[None]]) -> None:
        channel = self.channels.get(worker_id)
        if channel is None:
            raise DirectUnavailable(f"no LAN channel for worker {worker_id}")
        channel.register_receiver(receiver)

    async def send(self, target_worker_id: str, encoded: bytes) -> None:
        for channel in self.channels.values():
            if target_worker_id in channel._targets:
                await channel.send(target_worker_id, encoded)
                return
        raise DirectUnavailable(f"no LAN route to worker {target_worker_id}")


def build_direct_channel(
    backend: str,
    *,
    credential: str | None = None,
    pccl_sender: Callable[[str, bytes], Awaitable[None]] | None = None,
    local_peer_id: str | None = None,
    overlay_backend: str = "memory",
) -> object:
    """Factory for memory / lan / pccl / overlay direct backends."""
    from deepiri_zepgpu.training.transport import InMemoryDirectChannel, PcclDirectChannel

    if backend == "memory":
        return InMemoryDirectChannel()
    if backend == "lan":
        if not credential:
            raise ValueError("LAN direct backend requires a run credential")
        return LanDirectChannel(credential=credential)
    if backend == "pccl":
        return PcclDirectChannel(sender=pccl_sender)
    if backend == "overlay":
        from deepiri_zepgpu.vpn.overlay import OverlayDirectAdapter, build_overlay_transport

        if not local_peer_id:
            raise ValueError("overlay direct backend requires local_peer_id")
        transport = build_overlay_transport(
            overlay_backend,
            local_peer_id=local_peer_id,
            credential=credential,
        )
        return OverlayDirectAdapter(overlay=transport)
    raise ValueError(f"unknown direct backend: {backend}")
