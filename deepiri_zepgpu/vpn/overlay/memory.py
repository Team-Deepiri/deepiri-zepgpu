"""In-memory overlay transport for CI and same-process tests (direct path)."""

from __future__ import annotations

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

BACKEND = "memory"


@dataclass
class InMemoryOverlayHub:
    """Shared hub so two InMemoryOverlayTransport instances can find each other."""

    peers: dict[str, InMemoryOverlayTransport] = field(default_factory=dict)

    def register(self, transport: InMemoryOverlayTransport) -> None:
        self.peers[transport.local_peer_id] = transport

    def unregister(self, peer_id: str) -> None:
        self.peers.pop(peer_id, None)

    def get(self, peer_id: str) -> InMemoryOverlayTransport | None:
        return self.peers.get(peer_id)


@dataclass
class InMemoryOverlayTransport:
    """Direct in-process overlay; models successful NAT hole-punch / direct path."""

    local_peer_id: str
    hub: InMemoryOverlayHub
    backend_name: str = BACKEND
    _receiver: Callable[[str, bytes], Awaitable[None]] | None = field(
        default=None, init=False, repr=False
    )
    _connected: set[str] = field(default_factory=set, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _path_types: dict[str, PathType] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.local_peer_id.strip():
            raise ValueError("local_peer_id cannot be empty")
        self.hub.register(self)

    def register_receiver(self, receiver: Callable[[str, bytes], Awaitable[None]]) -> None:
        self._receiver = receiver

    async def connect(self, peer: OverlayPeer) -> None:
        self._ensure_open()
        if peer.peer_id == self.local_peer_id:
            raise OverlayUnavailable("cannot connect overlay to self")
        remote = self.hub.get(peer.peer_id)
        if remote is None or remote._closed:
            record_overlay_join(result="failure", backend=self.backend_name)
            raise OverlayUnavailable(f"overlay peer {peer.peer_id} not reachable")
        self._connected.add(peer.peer_id)
        self._path_types[peer.peer_id] = "direct"
        remote._connected.add(self.local_peer_id)
        remote._path_types[self.local_peer_id] = "direct"
        record_overlay_join(result="success", backend=self.backend_name)

    async def send(self, peer_id: str, payload: bytes) -> None:
        self._ensure_open()
        if peer_id not in self._connected:
            raise OverlayUnavailable(f"overlay peer {peer_id} is not connected")
        remote = self.hub.get(peer_id)
        if remote is None or remote._closed or remote._receiver is None:
            record_overlay_path(path_type="unknown", backend=self.backend_name)
            raise OverlayUnavailable(f"overlay peer {peer_id} has no receiver")
        path: PathType = self._path_types.get(peer_id, "direct")
        record_overlay_path(path_type=path, backend=self.backend_name)
        record_overlay_bytes(path_type=path, backend=self.backend_name, nbytes=len(payload))
        await remote._receiver(self.local_peer_id, payload)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for peer_id in list(self._connected):
            remote = self.hub.get(peer_id)
            if remote is not None:
                remote._connected.discard(self.local_peer_id)
                remote._path_types.pop(self.local_peer_id, None)
        self._connected.clear()
        self._path_types.clear()
        self.hub.unregister(self.local_peer_id)

    def path_type(self, peer_id: str | None = None) -> PathType:
        if peer_id is None:
            if not self._path_types:
                return "unknown"
            # Prefer reporting direct when any connected peer is direct.
            if any(value == "direct" for value in self._path_types.values()):
                return "direct"
            if any(value == "relay" for value in self._path_types.values()):
                return "relay"
            return "unknown"
        return self._path_types.get(peer_id, "unknown")

    def force_relay_path(self, peer_id: str) -> None:
        """Test helper: mark a connected peer as relay for metrics/assertions."""
        if peer_id not in self._connected:
            raise OverlayUnavailable(f"overlay peer {peer_id} is not connected")
        self._path_types[peer_id] = "relay"

    def _ensure_open(self) -> None:
        if self._closed:
            raise OverlayClosedError("overlay transport is closed")
