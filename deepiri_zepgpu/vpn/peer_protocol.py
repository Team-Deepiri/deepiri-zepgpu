"""Strict, non-executable messages for the legacy WireGuard peer endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypeAlias, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROTOCOL_VERSION = 1
MAX_ENCODED_MESSAGE_SIZE = 64 * 1024
MAX_AUTH_TOKEN_LENGTH = 256
MAX_GPU_DEVICE_ID = 255
MAX_GPU_MEMORY_MB = 1024 * 1024
MAX_TIMEOUT_SECONDS = 24 * 60 * 60
MESSAGE_MAX_AGE_SECONDS = 5 * 60
MESSAGE_FUTURE_SKEW_SECONDS = 30
MAX_JSON_NESTING_DEPTH = 100

_UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-" r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ProtocolError(ValueError):
    """A peer message failed bounded decoding, validation, or integrity checks."""

    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class StrictMessage(BaseModel):
    """Base schema that rejects coercion and undeclared fields."""

    model_config = ConfigDict(extra="forbid", strict=True)


class NoopPayload(StrictMessage):
    """Primitive input for the only safe operation supported by this endpoint."""

    message: str = Field(default="remote noop completed", min_length=1, max_length=256)


class NoopResult(StrictMessage):
    """Primitive result from the fixed no-op handler."""

    status: Literal["ok"] = "ok"
    message: str = Field(min_length=1, max_length=256)


class ExecuteTaskMessage(StrictMessage):
    """Authenticated request for a fixed, allowlisted peer operation."""

    version: Literal[1]
    kind: Literal["task.execute"]
    message_id: str = Field(pattern=_UUID_PATTERN)
    room_id: str = Field(pattern=_UUID_PATTERN)
    sender_peer_id: str = Field(pattern=_UUID_PATTERN)
    recipient_peer_id: str = Field(pattern=_UUID_PATTERN)
    task_id: str = Field(pattern=_UUID_PATTERN)
    issued_at: int = Field(ge=0)
    operation: Literal["noop"]
    gpu_device_id: int = Field(ge=0, le=MAX_GPU_DEVICE_ID)
    gpu_memory_mb: int = Field(ge=0, le=MAX_GPU_MEMORY_MB)
    timeout_seconds: int = Field(ge=1, le=MAX_TIMEOUT_SECONDS)
    payload: NoopPayload
    integrity: str = Field(min_length=64, max_length=64, pattern=_SHA256_PATTERN)


class TaskResultMessage(StrictMessage):
    """Authenticated primitive-only result returned by a peer."""

    version: Literal[1]
    kind: Literal["task.result"]
    message_id: str = Field(pattern=_UUID_PATTERN)
    request_message_id: str = Field(pattern=_UUID_PATTERN)
    room_id: str = Field(pattern=_UUID_PATTERN)
    sender_peer_id: str = Field(pattern=_UUID_PATTERN)
    recipient_peer_id: str = Field(pattern=_UUID_PATTERN)
    task_id: str = Field(pattern=_UUID_PATTERN)
    success: bool
    result: NoopResult | None = None
    error: str | None = Field(default=None, max_length=2048)
    execution_time: float = Field(ge=0.0, le=MAX_TIMEOUT_SECONDS)
    result_digest: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    attestation_signature: str | None = Field(default=None, max_length=512)
    ledger_public_key: str | None = Field(default=None, max_length=512)
    integrity: str = Field(min_length=64, max_length=64, pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_outcome(self) -> TaskResultMessage:
        if self.success and (self.result is None or self.error is not None):
            raise ValueError("successful results require result and forbid error")
        if not self.success and (self.result is not None or not self.error):
            raise ValueError("failed results require error and forbid result")
        return self


PeerMessage: TypeAlias = ExecuteTaskMessage | TaskResultMessage
_MESSAGE_MODELS: dict[str, type[ExecuteTaskMessage] | type[TaskResultMessage]] = {
    "task.execute": ExecuteTaskMessage,
    "task.result": TaskResultMessage,
}


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    """Encode a primitive mapping deterministically for HMAC and transport."""
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError("Message contains non-JSON values") from exc


def validate_protocol_secret(secret: str) -> bytes:
    """Validate a bounded peer token and return its UTF-8 key bytes."""
    if not isinstance(secret, str):
        raise ValueError("Peer protocol token must be text")
    encoded = secret.encode("utf-8")
    if len(encoded) < 32 or len(encoded) > MAX_AUTH_TOKEN_LENGTH:
        raise ValueError("Peer protocol token must contain 32 to 256 UTF-8 bytes")
    return encoded


def normalize_uuid(value: str, field_name: str) -> str:
    """Return a canonical UUID string for trusted configuration/builders."""
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a UUID") from exc


def _unsigned_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop("integrity", None)
    return unsigned


def calculate_integrity(payload: Mapping[str, Any], secret: str) -> str:
    """Bind every declared field to the authenticated sender token."""
    key = validate_protocol_secret(secret)
    return hmac.new(key, canonical_json(_unsigned_payload(payload)), hashlib.sha256).hexdigest()


def _sign_payload(payload: dict[str, Any], secret: str) -> dict[str, Any]:
    payload["integrity"] = calculate_integrity(payload, secret)
    return payload


def create_execute_message(
    *,
    secret: str,
    message_id: str,
    room_id: str,
    sender_peer_id: str,
    recipient_peer_id: str,
    task_id: str,
    issued_at: int,
    gpu_device_id: int,
    gpu_memory_mb: int,
    timeout_seconds: int,
    message: str = "remote noop completed",
) -> ExecuteTaskMessage:
    """Build and authenticate a safe fixed-operation request."""
    payload = {
        "version": PROTOCOL_VERSION,
        "kind": "task.execute",
        "message_id": normalize_uuid(message_id, "message_id"),
        "room_id": normalize_uuid(room_id, "room_id"),
        "sender_peer_id": normalize_uuid(sender_peer_id, "sender_peer_id"),
        "recipient_peer_id": normalize_uuid(recipient_peer_id, "recipient_peer_id"),
        "task_id": normalize_uuid(task_id, "task_id"),
        "issued_at": issued_at,
        "operation": "noop",
        "gpu_device_id": gpu_device_id,
        "gpu_memory_mb": gpu_memory_mb,
        "timeout_seconds": timeout_seconds,
        "payload": {"message": message},
    }
    return ExecuteTaskMessage.model_validate(_sign_payload(payload, secret))


def create_result_message(
    *,
    secret: str,
    message_id: str,
    request_message_id: str,
    room_id: str,
    sender_peer_id: str,
    recipient_peer_id: str,
    task_id: str,
    success: bool,
    result: NoopResult | None,
    error: str | None,
    execution_time: float,
    result_digest: str | None = None,
    attestation_signature: str | None = None,
    ledger_public_key: str | None = None,
) -> TaskResultMessage:
    """Build and authenticate a strict primitive result."""
    payload = {
        "version": PROTOCOL_VERSION,
        "kind": "task.result",
        "message_id": normalize_uuid(message_id, "message_id"),
        "request_message_id": normalize_uuid(request_message_id, "request_message_id"),
        "room_id": normalize_uuid(room_id, "room_id"),
        "sender_peer_id": normalize_uuid(sender_peer_id, "sender_peer_id"),
        "recipient_peer_id": normalize_uuid(recipient_peer_id, "recipient_peer_id"),
        "task_id": normalize_uuid(task_id, "task_id"),
        "success": success,
        "result": result.model_dump(mode="json") if result is not None else None,
        "error": error,
        "execution_time": execution_time,
        "result_digest": result_digest,
        "attestation_signature": attestation_signature,
        "ledger_public_key": ledger_public_key,
    }
    return TaskResultMessage.model_validate(_sign_payload(payload, secret))


def encode_message(message: PeerMessage) -> bytes:
    """Encode a validated message and enforce the transport ceiling."""
    encoded = canonical_json(message.model_dump(mode="json"))
    if len(encoded) > MAX_ENCODED_MESSAGE_SIZE:
        raise ProtocolError("Encoded message exceeds the maximum size", status_code=413)
    return encoded


def _reject_constant(value: str) -> None:
    raise ProtocolError(f"Invalid JSON constant: {value}")


def _object_from_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("Duplicate JSON object field")
        result[key] = value
    return result


def _decode_utf8(raw: bytes) -> str:
    if not isinstance(raw, bytes):
        raise ProtocolError("Peer message must be bytes")
    if not raw:
        raise ProtocolError("Peer message is empty")
    if len(raw) > MAX_ENCODED_MESSAGE_SIZE:
        raise ProtocolError("Encoded message exceeds the maximum size", status_code=413)

    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolError("Peer message is not valid UTF-8") from exc
    return text


def _validate_json_nesting(text: str) -> None:
    """Reject excessively nested JSON before invoking the platform decoder."""
    depth = 0
    in_string = False
    escaped = False

    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
            continue

        depth = _advance_json_depth(character, depth=depth)
        if depth < 0:
            return


def _parse_json_object(text: str) -> dict[str, Any]:
    _validate_json_nesting(text)

    decoder = json.JSONDecoder(
        object_pairs_hook=_object_from_pairs,
        parse_constant=_reject_constant,
    )
    try:
        payload, end = decoder.raw_decode(text)
    except ProtocolError:
        raise
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ProtocolError("Peer message is malformed JSON") from exc
    if end != len(text):
        raise ProtocolError("Trailing bytes are not permitted")
    if not isinstance(payload, dict):
        raise ProtocolError("Peer message must be a JSON object")
    return payload


def _select_message_model(
    payload: Mapping[str, Any],
    expected_kind: Literal["task.execute", "task.result"] | None,
) -> type[ExecuteTaskMessage] | type[TaskResultMessage]:
    version = payload.get("version")
    if version != PROTOCOL_VERSION or isinstance(version, bool):
        raise ProtocolError("Unsupported peer protocol version")
    kind = payload.get("kind")
    if not isinstance(kind, str):
        raise ProtocolError("Peer message kind must be a string")
    if kind not in _MESSAGE_MODELS:
        raise ProtocolError("Unknown peer message kind")
    if expected_kind is not None and kind != expected_kind:
        raise ProtocolError("Unexpected peer message kind")
    return _MESSAGE_MODELS[cast(str, kind)]


def _validate_message(
    payload: Mapping[str, Any],
    model: type[ExecuteTaskMessage] | type[TaskResultMessage],
    secret: str,
) -> PeerMessage:
    try:
        message = model.model_validate(payload)
    except ValidationError as exc:
        raise ProtocolError("Peer message schema validation failed") from exc

    expected_integrity = calculate_integrity(payload, secret)
    if not hmac.compare_digest(message.integrity, expected_integrity):
        raise ProtocolError("Peer message integrity check failed", status_code=401)
    return message


def decode_message(
    raw: bytes,
    *,
    secret: str,
    expected_kind: Literal["task.execute", "task.result"] | None = None,
) -> PeerMessage:
    """Decode one complete strict-JSON message with no executable hooks."""
    payload = _parse_json_object(_decode_utf8(raw))
    model = _select_message_model(payload, expected_kind)
    return _validate_message(payload, model, secret)


def _advance_json_depth(character: str, *, depth: int) -> int:
    if character in "[{":
        depth += 1
        if depth > MAX_JSON_NESTING_DEPTH:
            raise ProtocolError("Peer message exceeds the maximum JSON nesting depth")
    elif character in "]}":
        depth -= 1
    return depth
