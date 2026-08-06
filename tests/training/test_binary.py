import time
import uuid
from unittest.mock import AsyncMock

import pytest

from deepiri_zepgpu.training.binary import (
    BinaryEnvelope,
    BinaryInbox,
    ChecksumError,
    DuplicateTransferError,
    EnvelopeError,
    ScopeError,
)
from deepiri_zepgpu.training.relay import (
    BinaryRelayStore,
    RedisBinaryRelayStore,
    TransferConflictError,
)


def make_envelope(payload: bytes = b"weights") -> BinaryEnvelope:
    return BinaryEnvelope(
        room_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        worker_id=str(uuid.uuid4()),
        transfer_id=str(uuid.uuid4()),
        round=3,
        payload_type="adapter_delta",
        shape=(2, 4),
        dtype="float16",
        compression="none",
        payload=payload,
    )


def test_binary_envelope_roundtrip_and_scope() -> None:
    original = make_envelope()
    decoded = BinaryEnvelope.decode(
        original.encode(),
        expected_room_id=original.room_id,
        expected_run_id=original.run_id,
        expected_worker_id=original.worker_id,
        expected_round=3,
    )
    assert decoded == original
    with pytest.raises(ScopeError):
        BinaryEnvelope.decode(original.encode(), expected_room_id=str(uuid.uuid4()))


def test_corruption_and_malformed_metadata_are_rejected() -> None:
    encoded = bytearray(make_envelope().encode())
    encoded[-1] ^= 1
    with pytest.raises(ChecksumError):
        BinaryEnvelope.decode(bytes(encoded))
    with pytest.raises(EnvelopeError):
        BinaryEnvelope.decode(b"short")
    with pytest.raises(EnvelopeError):
        BinaryEnvelope.decode(make_envelope().encode() + b"trailing")


def test_relay_idempotency_conflict_completion_and_cleanup() -> None:
    envelope = make_envelope(b"a" * 100)
    encoded = envelope.encode()
    relay = BinaryRelayStore(ttl_seconds=1)
    relay.begin(envelope.transfer_id, envelope.room_id, envelope.run_id, 2)
    relay.begin(envelope.transfer_id, envelope.room_id, envelope.run_id, 2)
    relay.put_chunk(envelope.transfer_id, 0, encoded[:50])
    relay.put_chunk(envelope.transfer_id, 0, encoded[:50])
    with pytest.raises(TransferConflictError):
        relay.put_chunk(envelope.transfer_id, 0, b"different")
    relay.put_chunk(envelope.transfer_id, 1, encoded[50:])
    assert relay.complete(envelope.transfer_id) == envelope
    assert relay.complete(envelope.transfer_id) == envelope

    stale = make_envelope()
    relay.begin(stale.transfer_id, stale.room_id, stale.run_id, 1)
    assert relay.cleanup(now=time.monotonic() + 2) == 2


def test_checksum_reject_on_corrupted_envelope() -> None:
    encoded = bytearray(make_envelope(b"checksum-payload").encode())
    encoded[-1] ^= 0x5A
    with pytest.raises(ChecksumError):
        BinaryEnvelope.decode(bytes(encoded))


@pytest.mark.asyncio
async def test_redis_cleanup_deletes_expired_transfers() -> None:
    """Redis cleanup removes transfers whose created_at exceeds ttl_seconds."""

    transfer_id = str(uuid.uuid4())
    room_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    index_key = f"zepgpu:training:relay:index:{transfer_id}"
    base = f"zepgpu:training:relay:{room_id}:{run_id}:{transfer_id}"
    meta_key = f"{base}:meta"
    client = AsyncMock()

    async def scan_iter(*, match: str | None = None, count: int = 500):
        del count
        if match and match.startswith("zepgpu:training:relay:index"):
            yield index_key
        elif match and match.startswith(base):
            yield meta_key

    client.scan_iter = scan_iter
    client.get = AsyncMock(return_value=f"{room_id}:{run_id}".encode())
    client.hgetall = AsyncMock(
        return_value={
            b"created_at": str(time.time() - 120).encode(),
            b"status": b"uploading",
        }
    )
    client.delete = AsyncMock(return_value=1)
    client.ttl = AsyncMock(return_value=-1)

    store = RedisBinaryRelayStore(
        "redis://unused",
        client=client,
        ttl_seconds=30,
    )
    assert await store.cleanup() >= 1
    assert client.delete.await_count >= 1


def test_cross_room_relay_denied() -> None:
    envelope = make_envelope()
    encoded = envelope.encode()
    relay = BinaryRelayStore()
    relay.begin(envelope.transfer_id, str(uuid.uuid4()), envelope.run_id, 1)
    relay.put_chunk(envelope.transfer_id, 0, encoded)
    with pytest.raises(ScopeError):
        relay.complete(envelope.transfer_id)


def test_direct_inbox_rejects_conflicting_duplicate() -> None:
    original = make_envelope()
    inbox = BinaryInbox(room_id=original.room_id, run_id=original.run_id)
    assert inbox.receive(original.encode()) == original
    assert inbox.receive(original.encode()) is None
    conflict = BinaryEnvelope(
        room_id=original.room_id,
        run_id=original.run_id,
        worker_id=original.worker_id,
        transfer_id=original.transfer_id,
        round=original.round,
        payload_type=original.payload_type,
        shape=original.shape,
        dtype=original.dtype,
        compression=original.compression,
        payload=b"conflict",
    )
    with pytest.raises(DuplicateTransferError):
        inbox.receive(conflict.encode())
    assert inbox.forget(original.transfer_id) is True


def test_relay_enforces_worker_scope_and_chunk_limit() -> None:
    envelope = make_envelope()
    relay = BinaryRelayStore(max_chunk_bytes=32)
    relay.begin(
        envelope.transfer_id,
        envelope.room_id,
        envelope.run_id,
        1,
        worker_id=str(uuid.uuid4()),
    )
    with pytest.raises(EnvelopeError, match="chunk exceeds"):
        relay.put_chunk(envelope.transfer_id, 0, envelope.encode())

    scoped = BinaryRelayStore(max_chunk_bytes=1024)
    scoped.begin(
        envelope.transfer_id,
        envelope.room_id,
        envelope.run_id,
        1,
        worker_id=str(uuid.uuid4()),
    )
    scoped.put_chunk(envelope.transfer_id, 0, envelope.encode())
    with pytest.raises(ScopeError, match="worker"):
        scoped.complete(envelope.transfer_id)


def test_relay_payload_is_claimable_only_by_target_worker() -> None:
    envelope = make_envelope()
    target_worker_id = str(uuid.uuid4())
    relay = BinaryRelayStore(max_chunk_bytes=1024)
    relay.begin(
        envelope.transfer_id,
        envelope.room_id,
        envelope.run_id,
        1,
        target_worker_id=target_worker_id,
    )
    relay.put_chunk(envelope.transfer_id, 0, envelope.encode())
    relay.complete(envelope.transfer_id)
    assert relay.receive(envelope.transfer_id, target_worker_id) == envelope
    with pytest.raises(TransferConflictError, match="target"):
        relay.receive(envelope.transfer_id, str(uuid.uuid4()))


def test_relay_capacity_is_bounded() -> None:
    relay = BinaryRelayStore(max_transfers=1)
    first = make_envelope()
    second = make_envelope()
    relay.begin(first.transfer_id, first.room_id, first.run_id, 1)
    with pytest.raises(EnvelopeError, match="capacity"):
        relay.begin(second.transfer_id, second.room_id, second.run_id, 1)
