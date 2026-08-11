"""Select training direct channels from room transport_mode (Phase 19 / WG).

- ``dialout``: no direct channel (PCCL stub) → TransferManager uses HTTP relay
- ``wireguard``: ``LanDirectChannel`` bound on ``vpn_ip`` (TCP sockets *inside*
  the WireGuard **UDP** tunnel). Overlay TCP is never selected for WG rooms.
- ``overlay``: ``OverlayDirectAdapter``; backend is pluggable (``tcp`` LAN/CI
  helper, ``memory`` tests, ``iroh`` when dial is wired).

Peers discover endpoints via a shared endpoint directory and/or identity
``peer_data_plane``. When the peer is unreachable, TransferManager falls back to relay.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from deepiri_zepgpu.training.lan import LanDirectChannel
from deepiri_zepgpu.training.transport import DirectUnavailable, PcclDirectChannel


@dataclass(frozen=True)
class DataPlaneEndpoint:
    host: str
    port: int
    kind: str = "lan"  # lan | overlay | vpn

    def to_dict(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port, "kind": self.kind}

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> DataPlaneEndpoint | None:
        if not payload:
            return None
        host = str(payload.get("host") or "").strip()
        port = int(payload.get("port") or 0)
        if not host or port < 1:
            return None
        return cls(host=host, port=port, kind=str(payload.get("kind") or "lan"))


@dataclass
class WorkerDataPlane:
    """Started direct channel plus optional peer attach / cleanup."""

    channel: Any
    transport_mode: str
    local_endpoint: DataPlaneEndpoint | None
    needs_peer: bool
    peer_endpoint: DataPlaneEndpoint | None = None
    _overlay: Any = None
    _lan: LanDirectChannel | None = None
    _stopped: bool = False

    async def connect_peer(self, peer_worker_id: str, endpoint: DataPlaneEndpoint) -> None:
        if not self.needs_peer:
            return
        self.peer_endpoint = endpoint
        if self._lan is not None:
            self._lan.set_peer(peer_worker_id, endpoint.host, endpoint.port)
            return
        if self._overlay is not None:
            from deepiri_zepgpu.vpn.overlay.base import OverlayPeer

            # Overlay adapter maps worker_id → peer_id; use worker_id as overlay peer id.
            await self._overlay.connect(
                OverlayPeer(peer_id=peer_worker_id, host=endpoint.host, port=endpoint.port)
            )
            return
        raise DirectUnavailable("no direct channel available to attach peer")

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        if self._lan is not None:
            await self._lan.stop()
        if self._overlay is not None:
            await self._overlay.close()


def normalize_worker_transport_mode(value: str | None) -> str:
    mode = str(value or "dialout").strip().lower()
    if mode in {"wg", "wireguard"}:
        return "wireguard"
    if mode in {"overlay", "p2p"}:
        return "overlay"
    if mode in {"dialout", "dial-out", "cloudflare"}:
        return "dialout"
    return mode


def select_direct_backend(transport_mode: str, *, force_relay: bool = False) -> str:
    """Return backend token used by tests: none | lan | overlay."""

    if force_relay:
        return "none"
    mode = normalize_worker_transport_mode(transport_mode)
    if mode == "wireguard":
        return "lan"
    if mode == "overlay":
        return "overlay"
    return "none"


async def build_worker_data_plane(
    *,
    transport_mode: str,
    credential: str,
    worker_id: str,
    peer_id: str,
    peer_worker_id: str,
    listen_host: str = "127.0.0.1",
    listen_port: int = 0,
    peer_endpoint: DataPlaneEndpoint | None = None,
    overlay_backend: str = "iroh",
    force_relay: bool = False,
) -> WorkerDataPlane:
    """Build and start the direct half of TransferManager for a process worker."""

    _ = peer_id  # reserved for future overlay peer-id mapping
    mode = normalize_worker_transport_mode(transport_mode)
    backend = select_direct_backend(mode, force_relay=force_relay)

    if backend == "none":
        return WorkerDataPlane(
            channel=PcclDirectChannel(sender=None),
            transport_mode=mode,
            local_endpoint=None,
            needs_peer=False,
            peer_endpoint=peer_endpoint,
        )

    if backend == "lan":
        lan = LanDirectChannel(credential=credential, host=listen_host, port=listen_port)
        bound = await lan.start()
        kind = "vpn" if mode == "wireguard" else "lan"
        endpoint = DataPlaneEndpoint(host=_advertise_host(listen_host), port=bound, kind=kind)
        plane = WorkerDataPlane(
            channel=lan,
            transport_mode=mode,
            local_endpoint=endpoint,
            needs_peer=True,
            peer_endpoint=peer_endpoint,
            _lan=lan,
        )
        if peer_endpoint is not None:
            await plane.connect_peer(peer_worker_id, peer_endpoint)
        return plane

    # overlay
    from deepiri_zepgpu.vpn.overlay import OverlayDirectAdapter, build_overlay_transport

    overlay = build_overlay_transport(
        overlay_backend,
        local_peer_id=worker_id,
        credential=credential,
        host=listen_host,
        port=listen_port,
    )
    bound_port: int | None = None
    if hasattr(overlay, "start"):
        bound_port = int(await overlay.start())
    adapter = OverlayDirectAdapter(
        overlay=overlay,
        worker_to_peer={peer_worker_id: peer_worker_id},
    )
    overlay_endpoint: DataPlaneEndpoint | None = None
    if bound_port is not None:
        overlay_endpoint = DataPlaneEndpoint(
            host=_advertise_host(listen_host), port=bound_port, kind="overlay"
        )
    plane = WorkerDataPlane(
        channel=adapter,
        transport_mode=mode,
        local_endpoint=overlay_endpoint,
        needs_peer=overlay_backend != "memory",
        peer_endpoint=peer_endpoint,
        _overlay=overlay,
    )
    if peer_endpoint is not None and plane.needs_peer:
        await plane.connect_peer(peer_worker_id, peer_endpoint)
    return plane


def publish_endpoint(
    endpoint_dir: Path,
    worker_id: str,
    endpoint: DataPlaneEndpoint | None,
) -> Path | None:
    endpoint_dir.mkdir(parents=True, exist_ok=True)
    if endpoint is None:
        return None
    path = endpoint_dir / f"{worker_id}.json"
    path.write_text(json.dumps(endpoint.to_dict()) + "\n", encoding="utf-8")
    return path


async def wait_for_peer_endpoint(
    endpoint_dir: Path,
    peer_worker_id: str,
    *,
    timeout_seconds: float = 60.0,
    poll_interval: float = 0.1,
) -> DataPlaneEndpoint:
    path = endpoint_dir / f"{peer_worker_id}.json"
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                await asyncio.sleep(poll_interval)
                continue
            endpoint = DataPlaneEndpoint.from_dict(payload if isinstance(payload, dict) else None)
            if endpoint is not None:
                return endpoint
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"timed out waiting for peer data-plane endpoint at {path}")


def _advertise_host(listen_host: str) -> str:
    host = str(listen_host or "").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return host


async def wait_for_peer_endpoint_http(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    run_id: str,
    worker_id: str,
    peer_worker_id: str,
    peer_id: str,
    credential: str,
    timeout_seconds: float = 60.0,
    poll_interval: float = 0.2,
) -> DataPlaneEndpoint:
    """Pull the peer's published data-plane endpoint from the coordinator."""

    url = (
        f"{base_url.rstrip('/')}/api/v1/training-runs/{run_id}/workers/{worker_id}"
        f"/peers/{peer_worker_id}/data-plane"
    )
    headers = {"Authorization": f"Bearer {credential}"}
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        response = await client.get(url, params={"peer_id": peer_id}, headers=headers)
        if response.status_code < 400:
            body = response.json()
            endpoint = DataPlaneEndpoint.from_dict(body if isinstance(body, dict) else None)
            if endpoint is not None:
                return endpoint
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"timed out waiting for peer data-plane endpoint via {url}")


async def ensure_peer_connected(
    plane: WorkerDataPlane,
    *,
    peer_worker_id: str,
    endpoint_dir: Path | None,
    identity_peer: DataPlaneEndpoint | None,
    timeout_seconds: float = 60.0,
    http_client: httpx.AsyncClient | None = None,
    base_url: str | None = None,
    run_id: str | None = None,
    worker_id: str | None = None,
    peer_id: str | None = None,
    credential: str | None = None,
) -> DataPlaneEndpoint | None:
    """Attach peer endpoint when the selected backend needs one."""

    if not plane.needs_peer:
        return None
    endpoint = identity_peer or plane.peer_endpoint
    if endpoint is None and endpoint_dir is not None:
        try:
            endpoint = await wait_for_peer_endpoint(
                endpoint_dir, peer_worker_id, timeout_seconds=min(2.0, timeout_seconds)
            )
        except TimeoutError:
            endpoint = None
    if (
        endpoint is None
        and http_client is not None
        and base_url
        and run_id
        and worker_id
        and peer_id
        and credential
    ):
        endpoint = await wait_for_peer_endpoint_http(
            http_client,
            base_url=base_url,
            run_id=run_id,
            worker_id=worker_id,
            peer_worker_id=peer_worker_id,
            peer_id=peer_id,
            credential=credential,
            timeout_seconds=timeout_seconds,
        )
    if endpoint is None:
        raise DirectUnavailable("peer data-plane endpoint unknown; will rely on relay fallback")
    await plane.connect_peer(peer_worker_id, endpoint)
    return endpoint
