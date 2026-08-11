"""Overlay transport protocol (Phase 19.1)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

PathType = Literal["direct", "relay", "unknown"]


class OverlayUnavailable(ConnectionError):
    """Raised when the overlay cannot establish or use a peer path."""


class OverlayClosedError(RuntimeError):
    """Raised when operating on a closed overlay transport."""


@dataclass(frozen=True)
class OverlayPeer:
    """Remote overlay endpoint identity."""

    peer_id: str
    node_id: str | None = None
    host: str | None = None
    port: int | None = None
    relay_hint: str | None = None


class OverlayTransport(Protocol):
    """Direct-first overlay: connect, send, receive, close, path_type."""

    async def connect(self, peer: OverlayPeer) -> None: ...

    async def send(self, peer_id: str, payload: bytes) -> None: ...

    def register_receiver(self, receiver: Callable[[str, bytes], Awaitable[None]]) -> None: ...

    async def close(self) -> None: ...

    def path_type(self, peer_id: str | None = None) -> PathType: ...
