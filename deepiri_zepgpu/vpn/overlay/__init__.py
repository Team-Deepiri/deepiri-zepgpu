"""Phase 19 overlay networking: direct-first path with relay fallback.

Overlay is a room transport **separate from WireGuard**. WireGuard remains UDP
L3. Overlay backends are pluggable: ``memory`` (tests), ``tcp`` (LAN/CI helper),
``iroh``/``quic`` (UDP dial), ``tcp`` (LAN/CI helper).
"""

from __future__ import annotations

from deepiri_zepgpu.vpn.overlay.adapter import OverlayDirectAdapter
from deepiri_zepgpu.vpn.overlay.base import (
    OverlayClosedError,
    OverlayPeer,
    OverlayTransport,
    OverlayUnavailable,
)
from deepiri_zepgpu.vpn.overlay.factory import (
    VALID_OVERLAY_BACKENDS,
    build_overlay_transport,
)
from deepiri_zepgpu.vpn.overlay.iroh_backend import iroh_available, iroh_dial_wired
from deepiri_zepgpu.vpn.overlay.memory import InMemoryOverlayTransport
from deepiri_zepgpu.vpn.overlay.metrics import (
    record_overlay_bytes,
    record_overlay_join,
    record_overlay_path,
)

__all__ = [
    "VALID_OVERLAY_BACKENDS",
    "InMemoryOverlayTransport",
    "OverlayClosedError",
    "OverlayDirectAdapter",
    "OverlayPeer",
    "OverlayTransport",
    "OverlayUnavailable",
    "build_overlay_transport",
    "iroh_available",
    "iroh_dial_wired",
    "record_overlay_bytes",
    "record_overlay_join",
    "record_overlay_path",
]
