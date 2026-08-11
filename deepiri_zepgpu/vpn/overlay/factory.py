"""Factory for overlay transports."""

from __future__ import annotations

from typing import Final

from deepiri_zepgpu.vpn.overlay.base import OverlayTransport, OverlayUnavailable
from deepiri_zepgpu.vpn.overlay.iroh_backend import IrohOverlayTransport
from deepiri_zepgpu.vpn.overlay.memory import InMemoryOverlayHub, InMemoryOverlayTransport
from deepiri_zepgpu.vpn.overlay.tcp import TcpOverlayTransport
from deepiri_zepgpu.vpn.overlay.udp import UdpOverlayTransport

VALID_OVERLAY_BACKENDS: Final = frozenset({"memory", "tcp", "iroh", "quic"})

# Shared hub for in-process memory overlays (tests / same-process workers).
_DEFAULT_MEMORY_HUB = InMemoryOverlayHub()


def default_memory_hub() -> InMemoryOverlayHub:
    return _DEFAULT_MEMORY_HUB


def build_overlay_transport(
    backend: str,
    *,
    local_peer_id: str,
    credential: str | None = None,
    host: str = "127.0.0.1",
    port: int = 0,
    relay_url: str | None = None,
    hub: InMemoryOverlayHub | None = None,
) -> OverlayTransport:
    """Build an overlay transport.

    ``iroh``/``quic`` use HMAC-authenticated UDP dial. ``tcp`` is a LAN/CI
    helper. ``memory`` is in-process tests. WireGuard rooms do not use this.
    """

    mode = str(backend).strip().lower()
    if mode not in VALID_OVERLAY_BACKENDS:
        raise ValueError(
            f"unknown overlay backend {backend!r}; expected one of "
            f"{sorted(VALID_OVERLAY_BACKENDS)}"
        )
    if mode == "memory":
        return InMemoryOverlayTransport(
            local_peer_id=local_peer_id,
            hub=hub or _DEFAULT_MEMORY_HUB,
        )
    if mode == "tcp":
        if not credential:
            raise ValueError("TCP overlay backend requires a credential")
        return TcpOverlayTransport(
            local_peer_id=local_peer_id,
            credential=credential,
            host=host,
            port=port,
        )
    if mode in {"iroh", "quic"}:
        if not credential:
            raise ValueError("iroh/quic overlay backend requires a credential")
        if mode == "quic":
            return UdpOverlayTransport(
                local_peer_id=local_peer_id,
                credential=credential,
                host=host,
                port=port,
            )
        return IrohOverlayTransport(
            local_peer_id=local_peer_id,
            relay_url=relay_url,
            credential=credential,
            host=host,
            port=port,
        )
    raise OverlayUnavailable(f"unhandled overlay backend {mode!r}")
