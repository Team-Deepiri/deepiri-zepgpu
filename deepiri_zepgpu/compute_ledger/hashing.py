"""Canonical hashing for ledger transactions and blocks."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Serialize to deterministic UTF-8 JSON (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_hex(data: bytes | str) -> str:
    """Return lowercase hex SHA-256 digest."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_payload(obj: Any) -> str:
    """Hash a JSON-serializable object via canonical encoding."""
    return sha256_hex(canonical_json(obj))
