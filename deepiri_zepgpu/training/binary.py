"""Versioned binary training envelope with strict integrity checks."""

from __future__ import annotations

import hashlib
import struct
import time
import uuid
from dataclasses import dataclass, field

MAGIC = b"ZEPTRN01"
VERSION = 1
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
_HEADER = struct.Struct("!8sB16s16s16s16sQqQ32sHHHHHH")
_DIMENSION = struct.Struct("!q")


class EnvelopeError(ValueError):
    pass


class ChecksumError(EnvelopeError):
    pass


class ScopeError(EnvelopeError):
    pass


class DuplicateTransferError(EnvelopeError):
    pass


def _uuid_bytes(value: str, field_name: str) -> bytes:
    try:
        return uuid.UUID(value).bytes
    except ValueError as exc:
        raise EnvelopeError(f"invalid {field_name}") from exc


def _validated_header(data: bytes, max_payload_bytes: int) -> tuple:
    if len(data) < _HEADER.size:
        raise EnvelopeError("truncated envelope header")
    header = _HEADER.unpack_from(data)
    if header[0] != MAGIC or header[1] != VERSION:
        raise EnvelopeError("invalid magic or unsupported version")
    payload_length = header[8]
    timestamp_ns = header[7]
    shape_count, shape_length = header[13], header[14]
    if payload_length > max_payload_bytes:
        raise EnvelopeError("payload exceeds size limit")
    if timestamp_ns <= 0:
        raise EnvelopeError("invalid timestamp")
    if shape_count > 32 or shape_length != shape_count * _DIMENSION.size:
        raise EnvelopeError("malformed shape metadata")
    metadata_length = sum(header[index] for index in (10, 11, 12, 14, 15))
    if metadata_length > MAX_METADATA_BYTES:
        raise EnvelopeError("metadata exceeds size limit")
    if len(data) != _HEADER.size + metadata_length + payload_length:
        raise EnvelopeError("envelope length mismatch")
    return header


def _decode_body(data: bytes, header: tuple) -> tuple[str, str, str, tuple[int, ...], bytes, bytes]:
    payload_type_length, dtype_length, compression_length = header[10:13]
    shape_length, extensions_length = header[14:16]
    cursor = _HEADER.size
    lengths = (payload_type_length, dtype_length, compression_length)
    encoded_strings: list[bytes] = []
    for length in lengths:
        encoded_strings.append(data[cursor : cursor + length])
        cursor += length
    try:
        payload_type, dtype, compression = (item.decode("utf-8") for item in encoded_strings)
    except UnicodeDecodeError as exc:
        raise EnvelopeError("metadata is not valid UTF-8") from exc
    if not payload_type or not dtype or not compression:
        raise EnvelopeError("payload type, dtype, and compression are required")
    shape_bytes = data[cursor : cursor + shape_length]
    cursor += shape_length
    shape = tuple(
        _DIMENSION.unpack_from(shape_bytes, offset)[0]
        for offset in range(0, shape_length, _DIMENSION.size)
    )
    if any(dimension < 0 for dimension in shape):
        raise EnvelopeError("invalid tensor shape")
    extensions = data[cursor : cursor + extensions_length]
    cursor += extensions_length
    payload = data[cursor:]
    if hashlib.sha256(payload).digest() != header[9]:
        raise ChecksumError("payload checksum mismatch")
    return payload_type, dtype, compression, shape, extensions, payload


def _verify_scope(envelope: BinaryEnvelope, expected: tuple[object | None, ...]) -> None:
    actual = (envelope.room_id, envelope.run_id, envelope.worker_id, envelope.round)
    names = ("room", "run", "worker", "round")
    for name, expected_value, actual_value in zip(names, expected, actual, strict=True):
        if expected_value is not None and str(expected_value) != str(actual_value):
            raise ScopeError(f"{name} scope mismatch")


@dataclass(frozen=True, slots=True)
class BinaryEnvelope:
    room_id: str
    run_id: str
    worker_id: str
    transfer_id: str
    round: int
    payload_type: str
    shape: tuple[int, ...]
    dtype: str
    compression: str
    payload: bytes
    timestamp_ns: int = field(default_factory=time.time_ns)
    extensions: bytes = b""
    version: int = VERSION

    def encode(self, max_payload_bytes: int = MAX_PAYLOAD_BYTES) -> bytes:
        if self.version != VERSION:
            raise EnvelopeError(f"unsupported envelope version {self.version}")
        if self.round < 0:
            raise EnvelopeError("round cannot be negative")
        if len(self.payload) > max_payload_bytes:
            raise EnvelopeError("payload exceeds size limit")
        if not self.payload_type or not self.dtype or not self.compression:
            raise EnvelopeError("payload type, dtype, and compression are required")
        if len(self.shape) > 32 or any(dimension < 0 for dimension in self.shape):
            raise EnvelopeError("invalid tensor shape")
        fields = [
            self.payload_type.encode("utf-8"),
            self.dtype.encode("utf-8"),
            self.compression.encode("utf-8"),
            b"".join(_DIMENSION.pack(dimension) for dimension in self.shape),
            self.extensions,
        ]
        if sum(map(len, fields)) > MAX_METADATA_BYTES or any(len(item) > 65535 for item in fields):
            raise EnvelopeError("metadata exceeds size limit")
        checksum = hashlib.sha256(self.payload).digest()
        header = _HEADER.pack(
            MAGIC,
            self.version,
            _uuid_bytes(self.room_id, "room_id"),
            _uuid_bytes(self.run_id, "run_id"),
            _uuid_bytes(self.worker_id, "worker_id"),
            _uuid_bytes(self.transfer_id, "transfer_id"),
            self.round,
            self.timestamp_ns,
            len(self.payload),
            checksum,
            len(fields[0]),
            len(fields[1]),
            len(fields[2]),
            len(self.shape),
            len(fields[3]),
            len(fields[4]),
        )
        return header + b"".join(fields) + self.payload

    @classmethod
    def decode(
        cls,
        data: bytes,
        *,
        expected_room_id: str | None = None,
        expected_run_id: str | None = None,
        expected_worker_id: str | None = None,
        expected_round: int | None = None,
        max_payload_bytes: int = MAX_PAYLOAD_BYTES,
    ) -> BinaryEnvelope:
        unpacked = _validated_header(data, max_payload_bytes)
        (
            magic,
            version,
            room_bytes,
            run_bytes,
            worker_bytes,
            transfer_bytes,
            round_number,
            timestamp_ns,
            payload_length,
            checksum,
            payload_type_length,
            dtype_length,
            compression_length,
            shape_count,
            shape_length,
            extensions_length,
        ) = unpacked
        payload_type, dtype, compression, shape, extensions, payload = _decode_body(data, unpacked)
        envelope = cls(
            room_id=str(uuid.UUID(bytes=room_bytes)),
            run_id=str(uuid.UUID(bytes=run_bytes)),
            worker_id=str(uuid.UUID(bytes=worker_bytes)),
            transfer_id=str(uuid.UUID(bytes=transfer_bytes)),
            round=round_number,
            payload_type=payload_type,
            shape=shape,
            dtype=dtype,
            compression=compression,
            payload=payload,
            timestamp_ns=timestamp_ns,
            extensions=extensions,
            version=version,
        )
        _verify_scope(
            envelope,
            (expected_room_id, expected_run_id, expected_worker_id, expected_round),
        )
        return envelope


class BinaryInbox:
    """Validating receiver with idempotent transfer-ID handling."""

    def __init__(self, *, room_id: str, run_id: str, worker_id: str | None = None) -> None:
        self.room_id = room_id
        self.run_id = run_id
        self.worker_id = worker_id
        self._fingerprints: dict[str, bytes] = {}

    def receive(
        self, encoded: bytes, *, expected_round: int | None = None
    ) -> BinaryEnvelope | None:
        envelope = BinaryEnvelope.decode(
            encoded,
            expected_room_id=self.room_id,
            expected_run_id=self.run_id,
            expected_worker_id=self.worker_id,
            expected_round=expected_round,
        )
        fingerprint = hashlib.sha256(encoded).digest()
        previous = self._fingerprints.get(envelope.transfer_id)
        if previous is not None:
            if previous != fingerprint:
                raise DuplicateTransferError("conflicting duplicate transfer")
            return None
        self._fingerprints[envelope.transfer_id] = fingerprint
        return envelope

    def forget(self, transfer_id: str) -> bool:
        return self._fingerprints.pop(transfer_id, None) is not None
