"""Optional iroh overlay backend (QUIC/UDP — intended overlay, not a TCP lock-in).

Native ``iroh`` Python bindings still lack a stable connect/send API. Production
dial is therefore HMAC-authenticated UDP (``UdpOverlayTransport``), which is the
wired overlay path. If the iroh package later exposes stream send, wrap it here
without changing ``OverlayTransport``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from deepiri_zepgpu.vpn.overlay.base import (
    OverlayClosedError,
    OverlayPeer,
    OverlayUnavailable,
    PathType,
)
from deepiri_zepgpu.vpn.overlay.udp import UdpOverlayTransport

BACKEND = "iroh"


def iroh_available() -> bool:
    try:
        import iroh  # noqa: F401
    except ImportError:
        return False
    return True


def iroh_dial_wired() -> bool:
    """True: overlay UDP/QUIC dial is implemented (native iroh optional)."""

    return True


@dataclass
class IrohOverlayTransport:
    """Production overlay dial: UDP datagrams; native iroh used when API exists."""

    local_peer_id: str
    relay_url: str | None = None
    credential: str = ""
    host: str = "127.0.0.1"
    port: int = 0
    backend_name: str = BACKEND
    _inner: UdpOverlayTransport | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.local_peer_id.strip():
            raise ValueError("local_peer_id cannot be empty")
        if not self.credential.strip():
            # Overlay HMAC still required even when native iroh is absent.
            raise OverlayUnavailable(
                "iroh/quic overlay requires a data-plane credential; "
                "pass credential= to build_overlay_transport"
            )
        self._inner = UdpOverlayTransport(
            local_peer_id=self.local_peer_id,
            credential=self.credential,
            host=self.host,
            port=self.port,
            backend_name=self.backend_name,
        )

    def register_receiver(self, receiver: Callable[[str, bytes], Awaitable[None]]) -> None:
        assert self._inner is not None
        self._inner.register_receiver(receiver)

    async def start(self) -> int:
        assert self._inner is not None
        return await self._inner.start()

    @property
    def bound_port(self) -> int | None:
        return None if self._inner is None else self._inner.bound_port

    async def connect(self, peer: OverlayPeer) -> None:
        self._ensure_open()
        assert self._inner is not None
        await self._inner.connect(peer)

    async def send(self, peer_id: str, payload: bytes) -> None:
        self._ensure_open()
        assert self._inner is not None
        await self._inner.send(peer_id, payload)

    async def close(self) -> None:
        self._closed = True
        if self._inner is not None:
            await self._inner.close()

    def path_type(self, peer_id: str | None = None) -> PathType:
        if self._inner is None:
            return "unknown"
        return self._inner.path_type(peer_id)

    def _ensure_open(self) -> None:
        if self._closed:
            raise OverlayClosedError("overlay transport is closed")
