"""Two-worker WAN LoRA synchronization orchestrator."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

import numpy as np

from deepiri_zepgpu.training.binary import BinaryEnvelope, BinaryInbox
from deepiri_zepgpu.training.compression.base import (
    CompressedUpdate,
    CompressorState,
    UpdateCompressor,
    get_compressor,
)
from deepiri_zepgpu.training.config import CompressionConfig, OverlapMode
from deepiri_zepgpu.training.transport import TransferManager, TransferMetric

OverlapWork = Callable[[], Awaitable[None] | None]


class SyncError(RuntimeError):
    pass


class ShapeMismatchError(SyncError):
    pass


class TransferIdBus(Protocol):
    async def publish(self, round_number: int, worker_id: str, transfer_id: str) -> None: ...

    async def wait(self, round_number: int, worker_id: str, *, timeout_seconds: float) -> str: ...


def deterministic_transfer_id(run_id: str, round_number: int, worker_id: str) -> str:
    """Stable transfer UUID shared by independent worker processes for one round."""
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"zepgpu-transfer:{run_id}:{round_number}:{worker_id}")
    )


@dataclass
class DeterministicTransferIdBus:
    """Cross-process transfer-id locator derived from run/round/worker (no shared memory)."""

    run_id: str

    async def publish(self, round_number: int, worker_id: str, transfer_id: str) -> None:
        expected = deterministic_transfer_id(self.run_id, round_number, worker_id)
        if transfer_id != expected:
            raise SyncError(
                f"transfer id mismatch for worker {worker_id} round {round_number}: "
                f"got {transfer_id}, expected {expected}"
            )

    async def wait(self, round_number: int, worker_id: str, *, timeout_seconds: float) -> str:
        _ = timeout_seconds
        return deterministic_transfer_id(self.run_id, round_number, worker_id)


@dataclass
class InMemoryTransferIdBus:
    """Announce transfer IDs so peers can download relay payloads without OOB injection."""

    _values: dict[tuple[int, str], str] = field(default_factory=dict)
    _events: dict[tuple[int, str], asyncio.Event] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def publish(self, round_number: int, worker_id: str, transfer_id: str) -> None:
        key = (round_number, worker_id)
        async with self._lock:
            self._values[key] = transfer_id
            event = self._events.setdefault(key, asyncio.Event())
            event.set()

    async def wait(self, round_number: int, worker_id: str, *, timeout_seconds: float) -> str:
        key = (round_number, worker_id)
        async with self._lock:
            if key in self._values:
                return self._values[key]
            event = self._events.setdefault(key, asyncio.Event())
        await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
        async with self._lock:
            if key not in self._values:
                raise SyncError(f"missing transfer id for worker {worker_id} round {round_number}")
            return self._values[key]


@dataclass
class SyncRoundResult:
    round: int
    path: Literal["direct", "relay"]
    blocked_sync_seconds: float
    overlapped_sync_seconds: float
    bytes_sent: int
    bytes_received: int
    uncompressed_bytes: int
    compressed_bytes: int
    compression_ratio: float
    peer_update: dict[str, np.ndarray]
    local_update: dict[str, np.ndarray]
    averaged: dict[str, np.ndarray]
    rtt_ms: float | None = None
    bandwidth_bps: float | None = None
    transfer: TransferMetric | None = None


def _as_numpy_dict(tensors: dict[str, Any]) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    for name, value in tensors.items():
        if hasattr(value, "detach"):
            result[name] = value.detach().cpu().numpy().astype(np.float32, copy=True)
        else:
            result[name] = np.asarray(value, dtype=np.float32)
    return result


def validate_matching_shapes(local: dict[str, np.ndarray], peer: dict[str, np.ndarray]) -> None:
    if set(local) != set(peer):
        raise ShapeMismatchError("adapter delta keys do not match between workers")
    for name in local:
        if local[name].shape != peer[name].shape:
            raise ShapeMismatchError(
                f"shape mismatch for {name}: {local[name].shape} vs {peer[name].shape}"
            )


@dataclass
class SyncOrchestrator:
    """Exchange compressed adapter deltas between two workers for one room/run."""

    room_id: str
    run_id: str
    worker_id: str
    peer_worker_id: str
    transfer_manager: TransferManager
    compressor: UpdateCompressor
    overlap_mode: OverlapMode = OverlapMode.BLOCKING
    peer_wait_timeout_seconds: float = 120.0
    transfer_bus: TransferIdBus | None = None
    transfer_id_factory: Callable[[int], str] | None = None
    state: CompressorState = field(default_factory=CompressorState)
    inbox: BinaryInbox = field(init=False)
    _peer_queue: list[bytes] = field(default_factory=list, init=False, repr=False)
    _peer_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    def __post_init__(self) -> None:
        self.inbox = BinaryInbox(room_id=self.room_id, run_id=self.run_id)

    @classmethod
    def from_compression_config(
        cls,
        *,
        room_id: str,
        run_id: str,
        worker_id: str,
        peer_worker_id: str,
        transfer_manager: TransferManager,
        compression: CompressionConfig,
        overlap_mode: OverlapMode = OverlapMode.BLOCKING,
        peer_wait_timeout_seconds: float = 120.0,
        transfer_bus: TransferIdBus | None = None,
        transfer_id_factory: Callable[[int], str] | None = None,
    ) -> SyncOrchestrator:
        return cls(
            room_id=room_id,
            run_id=run_id,
            worker_id=worker_id,
            peer_worker_id=peer_worker_id,
            transfer_manager=transfer_manager,
            compressor=get_compressor(compression),
            overlap_mode=overlap_mode,
            peer_wait_timeout_seconds=peer_wait_timeout_seconds,
            transfer_bus=transfer_bus,
            transfer_id_factory=transfer_id_factory,
        )

    def envelope_for(self, round_number: int, update: CompressedUpdate) -> BinaryEnvelope:
        transfer_id = (
            self.transfer_id_factory(round_number)
            if self.transfer_id_factory is not None
            else str(uuid.uuid4())
        )
        return BinaryEnvelope(
            room_id=self.room_id,
            run_id=self.run_id,
            worker_id=self.worker_id,
            transfer_id=transfer_id,
            round=round_number,
            payload_type="adapter_delta",
            shape=(len(update.payload),),
            dtype="uint8",
            compression=update.codec,
            payload=update.payload,
        )

    def receive_encoded(
        self, encoded: bytes, *, expected_round: int | None = None
    ) -> BinaryEnvelope | None:
        envelope = self.inbox.receive(encoded, expected_round=expected_round)
        if envelope is None:
            return None
        if envelope.worker_id == self.worker_id:
            return envelope
        if envelope.worker_id != self.peer_worker_id:
            raise SyncError(
                f"envelope from unexpected worker {envelope.worker_id}; "
                f"expected peer {self.peer_worker_id}"
            )
        self._peer_queue.append(encoded)
        self._peer_event.set()
        return envelope

    def _decode_peer(self, encoded: bytes, round_number: int) -> BinaryEnvelope:
        envelope = BinaryEnvelope.decode(
            encoded,
            expected_room_id=self.room_id,
            expected_run_id=self.run_id,
            expected_worker_id=self.peer_worker_id,
            expected_round=round_number,
        )
        if envelope.worker_id == self.worker_id:
            raise SyncError("peer envelope was produced by this worker")
        return envelope

    def _take_peer_envelope(self, round_number: int, peer_encoded: bytes | None) -> BinaryEnvelope:
        if peer_encoded is not None:
            self._peer_queue.clear()
            self._peer_event.clear()
            return self._decode_peer(peer_encoded, round_number)
        if not self._peer_queue:
            raise SyncError("peer update is required for two-worker sync")
        encoded = self._peer_queue.pop(0)
        if not self._peer_queue:
            self._peer_event.clear()
        return self._decode_peer(encoded, round_number)

    async def _wait_peer_envelope(self, round_number: int) -> BinaryEnvelope:
        deadline = time.perf_counter() + self.peer_wait_timeout_seconds
        while not self._peer_queue:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise SyncError(
                    f"timed out waiting for peer {self.peer_worker_id} round {round_number}"
                )
            self._peer_event.clear()
            try:
                await asyncio.wait_for(self._peer_event.wait(), timeout=remaining)
            except TimeoutError as exc:
                raise SyncError(
                    f"timed out waiting for peer {self.peer_worker_id} round {round_number}"
                ) from exc
        return self._take_peer_envelope(round_number, None)

    async def _download_peer_envelope(self, round_number: int) -> BinaryEnvelope:
        if self.transfer_bus is None:
            raise SyncError("transfer bus is required for relay download sync")
        relay = self.transfer_manager.relay
        download = getattr(relay, "download", None)
        if not callable(download):
            raise SyncError("relay channel does not support download()")
        peer_transfer_id = await self.transfer_bus.wait(
            round_number,
            self.peer_worker_id,
            timeout_seconds=self.peer_wait_timeout_seconds,
        )
        envelope = await cast(Callable[..., Awaitable[BinaryEnvelope]], download)(
            peer_transfer_id,
            room_id=self.room_id,
            run_id=self.run_id,
            source_worker_id=self.peer_worker_id,
            round_number=round_number,
            target_worker_id=self.worker_id,
        )
        return envelope

    async def _run_overlap_work(self, overlap_work: OverlapWork | None) -> float:
        if self.overlap_mode != OverlapMode.EAGER or overlap_work is None:
            return 0.0
        started = time.perf_counter()
        result = overlap_work()
        if asyncio.iscoroutine(result):
            await result
        elif asyncio.isfuture(result):
            await cast(Awaitable[None], result)
        return time.perf_counter() - started

    async def sync_round(
        self,
        round_number: int,
        local_deltas: dict[str, Any],
        *,
        peer_encoded: bytes | None = None,
        precompressed: CompressedUpdate | None = None,
        overlap_work: OverlapWork | None = None,
        prefer_relay_download: bool = False,
    ) -> SyncRoundResult:
        local_np = _as_numpy_dict(local_deltas)
        update = precompressed or self.compressor.compress(local_np, self.state)
        envelope = self.envelope_for(round_number, update)

        sync_started = time.perf_counter()
        send_task = asyncio.create_task(self.transfer_manager.send(envelope, self.peer_worker_id))
        overlap_work_seconds = await self._run_overlap_work(overlap_work)
        _relayed, metric = await send_task
        # Announce only after upload succeeds so peers do not download incomplete transfers.
        if self.transfer_bus is not None:
            await self.transfer_bus.publish(round_number, self.worker_id, envelope.transfer_id)

        if peer_encoded is not None:
            peer_envelope = self._take_peer_envelope(round_number, peer_encoded)
        elif metric.path == "direct":
            # Direct send delivered bytes to the peer channel; wait on the local inbox.
            # Do not hit HTTP relay — the peer never uploaded there.
            peer_envelope = await self._wait_peer_envelope(round_number)
        elif prefer_relay_download or (metric.path == "relay" and self.transfer_bus is not None):
            peer_envelope = await self._download_peer_envelope(round_number)
        else:
            peer_envelope = await self._wait_peer_envelope(round_number)

        sync_elapsed = time.perf_counter() - sync_started
        if self.overlap_mode == OverlapMode.EAGER:
            overlapped = min(overlap_work_seconds, sync_elapsed)
            blocked = max(0.0, sync_elapsed - overlapped)
        else:
            overlapped = 0.0
            blocked = sync_elapsed

        if peer_envelope.compression != update.codec:
            raise SyncError(
                f"peer codec {peer_envelope.compression} does not match local {update.codec}"
            )
        peer_update = CompressedUpdate(
            codec=peer_envelope.compression,
            payload=peer_envelope.payload,
            shapes=(),
            dtypes=(),
            names=(),
            uncompressed_bytes=0,
            compressed_bytes=len(peer_envelope.payload),
        )
        peer_np = {
            name: np.asarray(arr, dtype=np.float32)
            for name, arr in self.compressor.decompress(peer_update).items()
        }
        # Average reconstructed (wire) deltas so both workers apply an identical update
        # under lossy compression. Raw local_np is retained for metrics/debug.
        local_hat = {
            name: np.asarray(arr, dtype=np.float32)
            for name, arr in self.compressor.decompress(update).items()
        }
        validate_matching_shapes(local_hat, peer_np)
        averaged = {
            name: ((local_hat[name] + peer_np[name]) * 0.5).astype(np.float32) for name in local_hat
        }
        duration = max(metric.duration_seconds, 1e-9)
        return SyncRoundResult(
            round=round_number,
            path="direct" if metric.path == "direct" else "relay",
            blocked_sync_seconds=blocked,
            overlapped_sync_seconds=overlapped,
            bytes_sent=metric.bytes,
            bytes_received=len(peer_envelope.encode()),
            uncompressed_bytes=update.uncompressed_bytes,
            compressed_bytes=update.compressed_bytes,
            compression_ratio=update.compression_ratio,
            peer_update=peer_np,
            local_update=local_np,
            averaged=averaged,
            bandwidth_bps=metric.bytes / duration,
            transfer=metric,
        )


def average_updates(
    left: dict[str, np.ndarray], right: dict[str, np.ndarray]
) -> dict[str, np.ndarray]:
    validate_matching_shapes(left, right)
    return {name: ((left[name] + right[name]) * 0.5).astype(np.float32) for name in left}
