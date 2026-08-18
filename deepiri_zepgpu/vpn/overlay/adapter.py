"""Adapt OverlayTransport to the training DirectChannel protocol."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from deepiri_zepgpu.training.transport import DirectUnavailable
from deepiri_zepgpu.vpn.overlay.base import OverlayClosedError, OverlayTransport, OverlayUnavailable


@dataclass
class OverlayDirectAdapter:
    """Map worker_id sends onto overlay peer_id sends for TransferManager."""

    overlay: OverlayTransport
    worker_to_peer: dict[str, str] = field(default_factory=dict)
    _receivers: dict[str, Callable[[bytes], Awaitable[None]]] = field(
        default_factory=dict, init=False, repr=False
    )
    _dispatch_installed: bool = field(default=False, init=False, repr=False)

    def _ensure_dispatch(self) -> None:
        if self._dispatch_installed:
            return

        async def _dispatch(source_peer_id: str, payload: bytes) -> None:
            _ = source_peer_id
            # In-process / single-worker adapters typically have one receiver.
            for receiver in list(self._receivers.values()):
                await receiver(payload)

        self.overlay.register_receiver(_dispatch)
        self._dispatch_installed = True

    def register(self, worker_id: str, receiver: Callable[[bytes], Awaitable[None]]) -> None:
        self._ensure_dispatch()
        self._receivers[worker_id] = receiver

    async def send(self, target_worker_id: str, encoded: bytes) -> None:
        peer_id = self.worker_to_peer.get(target_worker_id, target_worker_id)
        try:
            await self.overlay.send(peer_id, encoded)
        except (OverlayUnavailable, OverlayClosedError) as exc:
            raise DirectUnavailable(str(exc)) from exc

    def path_type(self, worker_id: str | None = None) -> str:
        peer_id = None
        if worker_id is not None:
            peer_id = self.worker_to_peer.get(worker_id, worker_id)
        return self.overlay.path_type(peer_id)
