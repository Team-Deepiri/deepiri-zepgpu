"""Bounded relay stores for tests and shared production deployments."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, cast

from redis.asyncio import Redis

from deepiri_zepgpu.training.binary import MAX_PAYLOAD_BYTES, BinaryEnvelope, EnvelopeError


class TransferConflictError(EnvelopeError):
    pass


@dataclass(slots=True)
class _Transfer:
    room_id: str
    run_id: str
    worker_id: str | None
    target_worker_id: str | None
    total_chunks: int
    round_number: int | None
    created_at: float
    received_bytes: int = 0
    chunks: dict[int, bytes] = field(default_factory=dict)
    fingerprints: dict[int, bytes] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _CompletedTransfer:
    envelope: BinaryEnvelope
    target_worker_id: str | None
    completed_at: float


class BinaryRelayStore:
    def __init__(
        self,
        *,
        max_transfer_bytes: int = MAX_PAYLOAD_BYTES + 128 * 1024,
        max_chunk_bytes: int = 8 * 1024 * 1024,
        max_transfers: int = 128,
        ttl_seconds: float = 300,
    ) -> None:
        if max_transfer_bytes < 1 or max_chunk_bytes < 1 or max_transfers < 1 or ttl_seconds <= 0:
            raise ValueError("relay limits must be positive")
        self.max_transfer_bytes = max_transfer_bytes
        self.max_chunk_bytes = max_chunk_bytes
        self.max_transfers = max_transfers
        self.ttl_seconds = ttl_seconds
        self._transfers: dict[str, _Transfer] = {}
        self._completed: dict[str, _CompletedTransfer] = {}

    def begin(
        self,
        transfer_id: str,
        room_id: str,
        run_id: str,
        total_chunks: int,
        *,
        worker_id: str | None = None,
        target_worker_id: str | None = None,
        round_number: int | None = None,
    ) -> None:
        if total_chunks < 1 or total_chunks > 65536:
            raise EnvelopeError("invalid chunk count")
        completed = self._completed.get(transfer_id)
        if completed:
            envelope = completed.envelope
            if (
                envelope.room_id,
                envelope.run_id,
                envelope.worker_id,
                completed.target_worker_id,
                envelope.round,
            ) != (
                room_id,
                run_id,
                worker_id or envelope.worker_id,
                target_worker_id,
                round_number if round_number is not None else envelope.round,
            ):
                raise TransferConflictError("conflicting completed transfer")
            raise TransferConflictError("transfer is already completed")
        existing = self._transfers.get(transfer_id)
        if existing:
            if (
                existing.room_id,
                existing.run_id,
                existing.worker_id,
                existing.target_worker_id,
                existing.total_chunks,
                existing.round_number,
            ) != (
                room_id,
                run_id,
                worker_id,
                target_worker_id,
                total_chunks,
                round_number,
            ):
                raise TransferConflictError("conflicting duplicate transfer")
            return
        self.cleanup()
        if len(self._transfers) + len(self._completed) >= self.max_transfers:
            raise EnvelopeError("relay transfer capacity reached")
        self._transfers[transfer_id] = _Transfer(
            room_id=room_id,
            run_id=run_id,
            worker_id=worker_id,
            target_worker_id=target_worker_id,
            total_chunks=total_chunks,
            round_number=round_number,
            created_at=time.monotonic(),
        )

    def put_chunk(self, transfer_id: str, index: int, chunk: bytes) -> None:
        transfer = self._transfers.get(transfer_id)
        if not transfer:
            raise EnvelopeError("unknown transfer")
        if index < 0 or index >= transfer.total_chunks:
            raise EnvelopeError("chunk index out of range")
        if len(chunk) > self.max_chunk_bytes:
            raise EnvelopeError("chunk exceeds size limit")
        fingerprint = hashlib.sha256(chunk).digest()
        if index in transfer.chunks:
            if transfer.fingerprints[index] != fingerprint:
                raise TransferConflictError("conflicting duplicate chunk")
            return
        if transfer.received_bytes + len(chunk) > self.max_transfer_bytes:
            raise EnvelopeError("transfer exceeds size limit")
        transfer.chunks[index] = bytes(chunk)
        transfer.fingerprints[index] = fingerprint
        transfer.received_bytes += len(chunk)

    def complete(self, transfer_id: str) -> BinaryEnvelope:
        completed = self._completed.get(transfer_id)
        if completed:
            return completed.envelope
        transfer = self._transfers.get(transfer_id)
        if not transfer:
            raise EnvelopeError("unknown transfer")
        if len(transfer.chunks) != transfer.total_chunks:
            raise EnvelopeError("transfer is incomplete")
        encoded = b"".join(transfer.chunks[index] for index in range(transfer.total_chunks))
        envelope = BinaryEnvelope.decode(
            encoded,
            expected_room_id=transfer.room_id,
            expected_run_id=transfer.run_id,
            expected_worker_id=transfer.worker_id,
            expected_round=transfer.round_number,
        )
        del self._transfers[transfer_id]
        self._completed[transfer_id] = _CompletedTransfer(
            envelope=envelope,
            target_worker_id=transfer.target_worker_id,
            completed_at=time.monotonic(),
        )
        return envelope

    def receive(self, transfer_id: str, target_worker_id: str) -> BinaryEnvelope:
        completed = self._completed.get(transfer_id)
        if completed is None:
            raise EnvelopeError("transfer is not completed")
        if (
            completed.target_worker_id is not None
            and completed.target_worker_id != target_worker_id
        ):
            raise TransferConflictError("transfer belongs to another target worker")
        return completed.envelope

    def scope(self, transfer_id: str) -> tuple[str, str, str | None]:
        transfer = self._transfers.get(transfer_id)
        if transfer:
            return transfer.room_id, transfer.run_id, transfer.worker_id
        completed = self._completed.get(transfer_id)
        if completed:
            envelope = completed.envelope
            return envelope.room_id, envelope.run_id, envelope.worker_id
        raise EnvelopeError("unknown transfer")

    def target(self, transfer_id: str) -> str | None:
        transfer = self._transfers.get(transfer_id)
        if transfer:
            return transfer.target_worker_id
        completed = self._completed.get(transfer_id)
        if completed:
            return completed.target_worker_id
        raise EnvelopeError("unknown transfer")

    def cleanup(self, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        expired = [
            transfer_id
            for transfer_id, transfer in self._transfers.items()
            if current - transfer.created_at >= self.ttl_seconds
        ]
        for transfer_id in expired:
            del self._transfers[transfer_id]
        completed_expired = [
            transfer_id
            for transfer_id, transfer in self._completed.items()
            if current - transfer.completed_at >= self.ttl_seconds
        ]
        for transfer_id in completed_expired:
            del self._completed[transfer_id]
        return len(expired) + len(completed_expired)

    def abort(self, transfer_id: str) -> bool:
        pending = self._transfers.pop(transfer_id, None)
        completed = self._completed.pop(transfer_id, None)
        return pending is not None or completed is not None


class RedisBinaryRelayStore:
    def __init__(
        self,
        url: str,
        *,
        max_transfer_bytes: int = 64 * 1024 * 1024,
        max_chunk_bytes: int = 4 * 1024 * 1024,
        ttl_seconds: int = 300,
        client: Redis | None = None,
    ) -> None:
        if max_transfer_bytes < 1 or max_chunk_bytes < 1 or ttl_seconds < 1:
            raise ValueError("relay limits must be positive")
        self.max_transfer_bytes = max_transfer_bytes
        self.max_chunk_bytes = max_chunk_bytes
        self.ttl_seconds = ttl_seconds
        self._redis: Redis = client or Redis.from_url(url, decode_responses=False)

    async def close(self) -> None:
        await self._redis.aclose()

    async def _get(self, key: str) -> bytes | None:
        response = cast(Awaitable[Any], self._redis.get(key))
        return cast(bytes | None, await response)

    async def _hget(self, key: str, field: str) -> bytes | None:
        response = cast(Awaitable[Any], self._redis.hget(key, field))
        return cast(bytes | None, await response)

    async def _hgetall(self, key: str) -> dict[bytes, bytes]:
        response = cast(Awaitable[Any], self._redis.hgetall(key))
        return cast(dict[bytes, bytes], await response)

    async def _mget(self, keys: list[str]) -> list[bytes | None]:
        return cast(list[bytes | None], await self._redis.mget(keys))

    @staticmethod
    def _index_key(transfer_id: str) -> str:
        return f"zepgpu:training:relay:index:{transfer_id}"

    @staticmethod
    def _base(room_id: str, run_id: str, transfer_id: str) -> str:
        return f"zepgpu:training:relay:{room_id}:{run_id}:{transfer_id}"

    async def _lookup(self, transfer_id: str) -> tuple[str, str, str]:
        value = await self._get(self._index_key(transfer_id))
        if not value:
            raise EnvelopeError("unknown transfer")
        decoded = value.decode("ascii") if isinstance(value, bytes) else str(value)
        room_id, run_id = decoded.split(":", 1)
        return room_id, run_id, self._base(room_id, run_id, transfer_id)

    async def begin(
        self,
        transfer_id: str,
        room_id: str,
        run_id: str,
        total_chunks: int,
        *,
        worker_id: str | None = None,
        target_worker_id: str | None = None,
        round_number: int | None = None,
    ) -> None:
        if total_chunks < 1 or total_chunks > 65536:
            raise EnvelopeError("invalid chunk count")
        index_key = self._index_key(transfer_id)
        base = self._base(room_id, run_id, transfer_id)
        async with self._redis.lock(
            f"zepgpu:training:relay:lock:{transfer_id}", timeout=10, blocking_timeout=5
        ):
            existing_scope = await self._get(index_key)
            expected_scope = f"{room_id}:{run_id}".encode()
            if existing_scope and existing_scope != expected_scope:
                raise TransferConflictError("conflicting duplicate transfer")
            existing = await self._hgetall(f"{base}:meta")
            if existing.get(b"status") == b"completed":
                raise TransferConflictError("transfer is already completed")
            metadata = {
                b"room_id": room_id.encode(),
                b"run_id": run_id.encode(),
                b"worker_id": (worker_id or "").encode(),
                b"target_worker_id": (target_worker_id or "").encode(),
                b"total_chunks": str(total_chunks).encode(),
                b"received_bytes": b"0",
                b"status": b"uploading",
                b"round": str(round_number if round_number is not None else -1).encode(),
            }
            if existing:
                comparable = {
                    key: existing.get(key, b"") for key in metadata if key != b"received_bytes"
                }
                expected = {
                    key: value for key, value in metadata.items() if key != b"received_bytes"
                }
                if comparable != expected:
                    raise TransferConflictError("conflicting duplicate transfer")
                return
            pipeline = self._redis.pipeline(transaction=True)
            pipeline.set(index_key, expected_scope, ex=self.ttl_seconds, nx=True)
            pipeline.hset(f"{base}:meta", mapping=metadata)
            pipeline.expire(f"{base}:meta", self.ttl_seconds)
            await pipeline.execute()

    async def put_chunk(self, transfer_id: str, index: int, chunk: bytes) -> None:
        room_id, run_id, base = await self._lookup(transfer_id)
        del room_id, run_id
        meta_key = f"{base}:meta"
        async with self._redis.lock(f"{base}:lock", timeout=10, blocking_timeout=5):
            meta = await self._hgetall(meta_key)
            if not meta or meta.get(b"status") != b"uploading":
                raise EnvelopeError("transfer is not accepting chunks")
            total_chunks = int(meta[b"total_chunks"])
            if index < 0 or index >= total_chunks:
                raise EnvelopeError("chunk index out of range")
            if len(chunk) > self.max_chunk_bytes:
                raise EnvelopeError("chunk exceeds size limit")
            chunk_key = f"{base}:chunk:{index}"
            existing = await self._get(chunk_key)
            if existing is not None:
                if hashlib.sha256(existing).digest() != hashlib.sha256(chunk).digest():
                    raise TransferConflictError("conflicting duplicate chunk")
                return
            received = int(meta.get(b"received_bytes", b"0"))
            if received + len(chunk) > self.max_transfer_bytes:
                raise EnvelopeError("transfer exceeds size limit")
            pipeline = self._redis.pipeline(transaction=True)
            pipeline.set(chunk_key, bytes(chunk), ex=self.ttl_seconds, nx=True)
            pipeline.hincrby(meta_key, "received_bytes", len(chunk))
            pipeline.expire(meta_key, self.ttl_seconds)
            pipeline.expire(self._index_key(transfer_id), self.ttl_seconds)
            await pipeline.execute()

    async def complete(self, transfer_id: str) -> BinaryEnvelope:
        room_id, run_id, base = await self._lookup(transfer_id)
        meta_key = f"{base}:meta"
        async with self._redis.lock(f"{base}:lock", timeout=30, blocking_timeout=5):
            meta = await self._hgetall(meta_key)
            if not meta:
                raise EnvelopeError("unknown transfer")
            if meta.get(b"status") == b"completed":
                encoded = await self._get(f"{base}:payload")
                if encoded is None:
                    raise EnvelopeError("completed transfer payload expired")
                return BinaryEnvelope.decode(
                    encoded, expected_room_id=room_id, expected_run_id=run_id
                )
            total_chunks = int(meta[b"total_chunks"])
            chunks = await self._mget([f"{base}:chunk:{index}" for index in range(total_chunks)])
            if any(chunk is None for chunk in chunks):
                raise EnvelopeError("transfer is incomplete")
            encoded = b"".join(chunk for chunk in chunks if chunk is not None)
            if len(encoded) > self.max_transfer_bytes:
                raise EnvelopeError("transfer exceeds size limit")
            worker_id = meta.get(b"worker_id", b"").decode() or None
            envelope = BinaryEnvelope.decode(
                encoded,
                expected_room_id=room_id,
                expected_run_id=run_id,
                expected_worker_id=worker_id,
                expected_round=(
                    int(meta[b"round"]) if int(meta.get(b"round", b"-1")) >= 0 else None
                ),
                max_payload_bytes=self.max_transfer_bytes,
            )
            pipeline = self._redis.pipeline(transaction=True)
            pipeline.set(f"{base}:payload", encoded, ex=self.ttl_seconds)
            pipeline.hset(meta_key, "status", "completed")
            pipeline.expire(meta_key, self.ttl_seconds)
            await pipeline.execute()
            return envelope

    async def receive(self, transfer_id: str, target_worker_id: str) -> BinaryEnvelope:
        room_id, run_id, base = await self._lookup(transfer_id)
        meta = await self._hgetall(f"{base}:meta")
        if not meta or meta.get(b"status") != b"completed":
            raise EnvelopeError("transfer is not completed")
        expected_target = meta.get(b"target_worker_id", b"").decode()
        if expected_target and expected_target != target_worker_id:
            raise TransferConflictError("transfer belongs to another target worker")
        encoded = await self._get(f"{base}:payload")
        if encoded is None:
            raise EnvelopeError("completed transfer payload expired")
        return BinaryEnvelope.decode(encoded, expected_room_id=room_id, expected_run_id=run_id)

    async def scope(self, transfer_id: str) -> tuple[str, str, str | None]:
        room_id, run_id, base = await self._lookup(transfer_id)
        worker_id = await self._hget(f"{base}:meta", "worker_id")
        decoded = worker_id.decode() if worker_id else None
        return room_id, run_id, decoded or None

    async def target(self, transfer_id: str) -> str | None:
        _, _, base = await self._lookup(transfer_id)
        target = await self._hget(f"{base}:meta", "target_worker_id")
        decoded = target.decode() if target else None
        return decoded or None

    async def inspect(self, transfer_id: str) -> dict[str, Any]:
        room_id, run_id, base = await self._lookup(transfer_id)
        meta = await self._hgetall(f"{base}:meta")
        return {
            "room_id": room_id,
            "run_id": run_id,
            "status": meta.get(b"status", b"unknown").decode(),
            "received_bytes": int(meta.get(b"received_bytes", b"0")),
            "total_chunks": int(meta.get(b"total_chunks", b"0")),
        }

    async def cleanup(self, now: float | None = None) -> int:
        del now
        return 0

    async def abort(self, transfer_id: str) -> bool:
        try:
            _, _, base = await self._lookup(transfer_id)
        except EnvelopeError:
            return False
        keys = [key async for key in self._redis.scan_iter(match=f"{base}:*", count=1000)]
        if keys:
            await self._redis.delete(*keys)
        await self._redis.delete(self._index_key(transfer_id))
        return True
