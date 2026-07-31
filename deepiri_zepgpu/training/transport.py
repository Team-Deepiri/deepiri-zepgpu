"""Direct-first binary transport with coordinator HTTP relay fallback."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

import httpx

from deepiri_zepgpu.training.binary import BinaryEnvelope, EnvelopeError
from deepiri_zepgpu.training.relay import BinaryRelayStore


class DirectChannel(Protocol):
    async def send(self, target_worker_id: str, encoded: bytes) -> None: ...


class RelayChannel(Protocol):
    async def transfer(
        self, envelope: BinaryEnvelope, target_worker_id: str
    ) -> BinaryEnvelope | None: ...


class DirectUnavailable(ConnectionError):
    pass


class RelayAuthorizationError(PermissionError):
    pass


class InMemoryDirectChannel:
    def __init__(self) -> None:
        self.receivers: dict[str, Callable[[bytes], Awaitable[None]]] = {}

    def register(self, worker_id: str, receiver: Callable[[bytes], Awaitable[None]]) -> None:
        self.receivers[worker_id] = receiver

    async def send(self, target_worker_id: str, encoded: bytes) -> None:
        receiver = self.receivers.get(target_worker_id)
        if not receiver:
            raise DirectUnavailable(f"worker {target_worker_id} is not directly reachable")
        await receiver(encoded)


class PcclDirectChannel:
    """Phase 16 adapter boundary for a future asynchronous PCCL sender.

    ``sender`` must be an async callable accepting the assigned target worker ID and the
    unmodified ``BinaryEnvelope.encode()`` bytes. The envelope carries the room, run,
    source-worker, round, checksum, and payload metadata; the target argument supplies the
    destination-worker scope. A concrete sender must authorize and validate all of those scopes
    before delivery and must raise authorization or envelope errors rather than translating them
    into connectivity failures.

    The sender owns its network timeout and should raise ``TimeoutError`` when it expires, or
    ``DirectUnavailable`` when the direct path cannot be established. Only those two failures are
    retried and may fall back to the coordinator relay. Other failures propagate without fallback.
    Direct delivery acknowledgement, if the eventual PCCL protocol requires one, is the sender's
    responsibility before this coroutine returns; there is no separate Phase 16 PCCL ack API.

    ``TransferManager`` records path, byte, duration, and retry metrics, while a concrete sender is
    responsible for any PCCL-specific metrics. The callable must remain non-blocking/async; any
    blocking PCCL binding must manage its own thread boundary. Phase 16 does not bundle or claim a
    PCCL networking implementation.
    """

    def __init__(self, sender: Callable[[str, bytes], Awaitable[None]] | None = None) -> None:
        self.sender = sender

    async def send(self, target_worker_id: str, encoded: bytes) -> None:
        if self.sender is None:
            raise DirectUnavailable("PCCL direct channel is not configured")
        await self.sender(target_worker_id, encoded)


class InMemoryRelayChannel:
    def __init__(self, store: BinaryRelayStore, chunk_size: int) -> None:
        self.store = store
        self.chunk_size = chunk_size

    async def transfer(
        self, envelope: BinaryEnvelope, target_worker_id: str
    ) -> BinaryEnvelope | None:
        encoded = envelope.encode()
        total_chunks = math.ceil(len(encoded) / self.chunk_size)
        self.store.begin(
            envelope.transfer_id,
            envelope.room_id,
            envelope.run_id,
            total_chunks,
            worker_id=envelope.worker_id,
            target_worker_id=target_worker_id,
            round_number=envelope.round,
        )
        for index in range(total_chunks):
            start = index * self.chunk_size
            self.store.put_chunk(
                envelope.transfer_id, index, encoded[start : start + self.chunk_size]
            )
        self.store.complete(envelope.transfer_id)
        return self.store.receive(envelope.transfer_id, target_worker_id)


class HttpRelayChannel:
    def __init__(
        self,
        *,
        base_url: str,
        peer_id: str,
        credential: str,
        chunk_size: int = 1024 * 1024,
        max_payload_bytes: int = 64 * 1024 * 1024,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.peer_id = peer_id
        self.credential = credential
        self.chunk_size = chunk_size
        self.max_payload_bytes = max_payload_bytes
        self.max_retries = max_retries
        self.client = client or httpx.AsyncClient(timeout=30)

    def _url(self, transfer_id: str, suffix: str) -> str:
        return f"{self.base_url}/api/v1/training-runs/relay/{transfer_id}{suffix}?peer_id={self.peer_id}"

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        request_headers = dict(headers or {})
        request_headers["Authorization"] = f"Bearer {self.credential}"
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.request(
                    method, url, headers=request_headers, content=content
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt == self.max_retries:
                    raise ConnectionError("coordinator relay unavailable") from exc
                await asyncio.sleep(0.1 * (2**attempt))
                continue
            if response.status_code in {401, 403}:
                raise RelayAuthorizationError(response.text)
            if response.status_code < 500 or attempt == self.max_retries:
                response.raise_for_status()
                return response
            await asyncio.sleep(0.1 * (2**attempt))
        raise RuntimeError("unreachable relay retry state")

    async def transfer(
        self, envelope: BinaryEnvelope, target_worker_id: str
    ) -> BinaryEnvelope | None:
        encoded = envelope.encode(max_payload_bytes=self.max_payload_bytes)
        total_chunks = math.ceil(len(encoded) / self.chunk_size)
        common = {"ZepGPU-Room-ID": envelope.room_id}
        try:
            await self._request(
                "POST",
                self._url(envelope.transfer_id, "/begin"),
                headers={
                    **common,
                    "ZepGPU-Run-ID": envelope.run_id,
                    "ZepGPU-Target-Worker-ID": target_worker_id,
                    "ZepGPU-Total-Chunks": str(total_chunks),
                    "ZepGPU-Round": str(envelope.round),
                },
            )
            for index in range(total_chunks):
                start = index * self.chunk_size
                await self._request(
                    "PUT",
                    self._url(envelope.transfer_id, f"/chunks/{index}"),
                    headers=common,
                    content=encoded[start : start + self.chunk_size],
                )
            await self._request(
                "POST", self._url(envelope.transfer_id, "/complete"), headers=common
            )
            await self._request("GET", self._url(envelope.transfer_id, ""), headers=common)
            return None
        except Exception:
            with suppress(Exception):
                await self._request("DELETE", self._url(envelope.transfer_id, ""), headers=common)
            raise

    async def download(
        self,
        transfer_id: str,
        *,
        room_id: str,
        run_id: str,
        source_worker_id: str,
        round_number: int,
    ) -> BinaryEnvelope:
        headers = {"ZepGPU-Room-ID": room_id}
        response = await self._request("GET", self._url(transfer_id, "/payload"), headers=headers)
        envelope = BinaryEnvelope.decode(
            response.content,
            expected_room_id=room_id,
            expected_run_id=run_id,
            expected_worker_id=source_worker_id,
            expected_round=round_number,
            max_payload_bytes=self.max_payload_bytes,
        )
        await self._request("POST", self._url(transfer_id, "/ack"), headers=headers)
        return envelope


@dataclass(frozen=True, slots=True)
class TransferMetric:
    transfer_id: str
    path: str
    bytes: int
    duration_seconds: float
    retries: int


class TransferManager:
    def __init__(
        self,
        *,
        direct: DirectChannel,
        relay: RelayChannel | BinaryRelayStore,
        chunk_size: int = 1024 * 1024,
        max_retries: int = 2,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.direct = direct
        self.relay = (
            InMemoryRelayChannel(relay, chunk_size)
            if isinstance(relay, BinaryRelayStore)
            else relay
        )
        self.max_retries = max_retries

    async def send(
        self, envelope: BinaryEnvelope, target_worker_id: str
    ) -> tuple[BinaryEnvelope | None, TransferMetric]:
        encoded = envelope.encode()
        started = time.perf_counter()
        retries = 0
        for attempt in range(self.max_retries + 1):
            try:
                await self.direct.send(target_worker_id, encoded)
                return None, TransferMetric(
                    envelope.transfer_id,
                    "direct",
                    len(encoded),
                    time.perf_counter() - started,
                    retries,
                )
            except (DirectUnavailable, TimeoutError):
                if attempt < self.max_retries:
                    retries += 1
                    await asyncio.sleep(0.1 * (2**attempt))
        received = await self.relay.transfer(envelope, target_worker_id)
        if received is not None and received != envelope:
            raise EnvelopeError("relay returned a mismatched envelope")
        return received, TransferMetric(
            envelope.transfer_id, "relay", len(encoded), time.perf_counter() - started, retries
        )
