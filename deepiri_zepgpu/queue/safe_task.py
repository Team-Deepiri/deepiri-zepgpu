"""Bounded, non-executable payload handling for persisted worker tasks."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any

MAX_TASK_ARGUMENT_BYTES = 64 * 1024
MAX_TASK_RESULT_BYTES = 1024 * 1024


class UnsafeTaskPayloadError(ValueError):
    """A task attempted to cross the worker boundary using an unsafe payload."""


_OPERATIONS: Mapping[str, Callable[..., Any]] = MappingProxyType(
    {
        "math.sqrt": math.sqrt,
    }
)


def allowed_operation_names() -> tuple[str, ...]:
    """Return the stable public operation allowlist."""
    return tuple(_OPERATIONS)


def validate_operation(func_name: str | None, serialized_func: str | bytes | None = None) -> str:
    """Validate an allowlisted operation and reject executable-object payloads."""
    if serialized_func:
        raise UnsafeTaskPayloadError(
            "Serialized Python callables are no longer accepted; use an allowlisted operation"
        )
    if func_name not in _OPERATIONS:
        allowed = ", ".join(allowed_operation_names())
        raise UnsafeTaskPayloadError(f"Unsupported task operation; allowed operations: {allowed}")
    return func_name


def resolve_operation(func_name: str) -> Callable[..., Any]:
    """Resolve a previously validated name without a payload-directed import."""
    validate_operation(func_name)
    return _OPERATIONS[func_name]


def _reject_constant(value: str) -> None:
    raise UnsafeTaskPayloadError(f"Invalid JSON constant: {value}")


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UnsafeTaskPayloadError("Duplicate JSON object field")
        result[key] = value
    return result


def _encode_json(value: Any, *, maximum: int, label: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise UnsafeTaskPayloadError(f"{label} must contain JSON primitives only") from exc
    if len(encoded) > maximum:
        raise UnsafeTaskPayloadError(f"{label} exceeds the {maximum}-byte limit")
    return encoded


def _decode_json(data: bytes, *, maximum: int, label: str) -> Any:
    if len(data) > maximum:
        raise UnsafeTaskPayloadError(f"{label} exceeds the {maximum}-byte limit")
    try:
        text = data.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_object_from_pairs,
            parse_constant=_reject_constant,
        )
    except UnsafeTaskPayloadError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise UnsafeTaskPayloadError(f"{label} is not valid strict JSON") from exc


def encode_task_arguments(
    args: Sequence[Any] | None,
    kwargs: Mapping[str, Any] | None,
) -> tuple[bytes, bytes]:
    """Encode primitive task inputs for database persistence."""
    return (
        _encode_json(list(args or ()), maximum=MAX_TASK_ARGUMENT_BYTES, label="Task arguments"),
        _encode_json(dict(kwargs or {}), maximum=MAX_TASK_ARGUMENT_BYTES, label="Task keywords"),
    )


def decode_task_arguments(
    args: bytes | None,
    kwargs: bytes | None,
) -> tuple[list[Any], dict[str, Any]]:
    """Decode persisted primitive task inputs without object construction hooks."""
    decoded_args = _decode_json(
        args or b"[]", maximum=MAX_TASK_ARGUMENT_BYTES, label="Task arguments"
    )
    decoded_kwargs = _decode_json(
        kwargs or b"{}", maximum=MAX_TASK_ARGUMENT_BYTES, label="Task keywords"
    )
    if not isinstance(decoded_args, list) or not isinstance(decoded_kwargs, dict):
        raise UnsafeTaskPayloadError("Task arguments must be a list and keywords must be an object")
    return decoded_args, decoded_kwargs


def encode_task_result(result: Any) -> bytes:
    """Encode a worker result as bounded JSON primitives."""
    return _encode_json(result, maximum=MAX_TASK_RESULT_BYTES, label="Task result")


def decode_task_result(data: bytes) -> Any:
    """Decode a bounded primitive task result for the API response."""
    return _decode_json(data, maximum=MAX_TASK_RESULT_BYTES, label="Task result")
