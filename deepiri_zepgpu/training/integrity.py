"""Phase 19.3 neutral outer-update format with integrity (MAC + replay protection)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UpdateIntegrityError(ValueError):
    """Raised when an outer update fails validation or authenticity checks."""


class NeutralOuterUpdate(BaseModel):
    """Framework-neutral outer/adapter update metadata + tensor payload refs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    model_revision: str
    parameter_names: list[str] = Field(min_length=1)
    shapes: list[list[int]] = Field(min_length=1)
    dtype: str
    quantization: str = "none"
    round: int = Field(ge=0)
    worker_id: str
    run_id: str
    room_id: str
    payload_sha256: str
    created_at_ns: int = Field(default_factory=time.time_ns)

    def model_post_init(self, __context: Any) -> None:
        if len(self.parameter_names) != len(self.shapes):
            raise ValueError("parameter_names and shapes length mismatch")
        if len(self.payload_sha256) != 64:
            raise ValueError("payload_sha256 must be a 64-char hex digest")


def payload_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_update_bytes(update: NeutralOuterUpdate) -> bytes:
    """Stable byte encoding for MAC (exclude nothing — full model dump sorted)."""
    return json.dumps(update.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sign_update(update: NeutralOuterUpdate, *, room_mac_key: str) -> str:
    if not room_mac_key.strip():
        raise ValueError("room_mac_key cannot be empty")
    digest = hmac.new(
        room_mac_key.encode("utf-8"),
        canonical_update_bytes(update),
        hashlib.sha256,
    ).hexdigest()
    return digest


def verify_update_mac(update: NeutralOuterUpdate, *, room_mac_key: str, mac_hex: str) -> None:
    expected = sign_update(update, room_mac_key=room_mac_key)
    if not hmac.compare_digest(expected, mac_hex):
        raise UpdateIntegrityError("outer update MAC verification failed")


def verify_payload_checksum(update: NeutralOuterUpdate, payload: bytes) -> None:
    if payload_digest(payload) != update.payload_sha256:
        raise UpdateIntegrityError("outer update payload checksum mismatch")


@dataclass
class ReplayGuard:
    """Reject replayed (run_id, round, worker_id) triples; identical retries allowed."""

    _seen: dict[tuple[str, int, str], str] = field(default_factory=dict)

    def check(self, update: NeutralOuterUpdate, *, mac_hex: str) -> None:
        key = (update.run_id, update.round, update.worker_id)
        previous = self._seen.get(key)
        if previous is None:
            self._seen[key] = mac_hex
            return
        if not hmac.compare_digest(previous, mac_hex):
            raise UpdateIntegrityError(
                f"conflicting replay for run={update.run_id} round={update.round} "
                f"worker={update.worker_id}"
            )
        # Identical MAC + same key: idempotent duplicate, allowed.

    def forget_run(self, run_id: str) -> int:
        keys = [key for key in self._seen if key[0] == run_id]
        for key in keys:
            del self._seen[key]
        return len(keys)


def accept_outer_update(
    update: NeutralOuterUpdate,
    payload: bytes,
    *,
    room_mac_key: str,
    mac_hex: str,
    replay_guard: ReplayGuard,
    expected_quantization: str | None = None,
) -> NeutralOuterUpdate:
    """Validate checksum, MAC, replay, and homogeneous quantization."""
    if len(update.parameter_names) != len(update.shapes):
        raise UpdateIntegrityError("parameter_names/shapes mismatch")
    if expected_quantization is not None and update.quantization != expected_quantization:
        raise UpdateIntegrityError("heterogeneous quantization rejected")
    verify_payload_checksum(update, payload)
    verify_update_mac(update, room_mac_key=room_mac_key, mac_hex=mac_hex)
    replay_guard.check(update, mac_hex=mac_hex)
    return update


def envelope_to_neutral(envelope: Any, *, room_id: str, run_id: str) -> NeutralOuterUpdate:
    """Map a BinaryEnvelope onto NeutralOuterUpdate for live MAC checks."""
    shape = list(getattr(envelope, "shape", ()) or [len(envelope.payload)])
    return NeutralOuterUpdate(
        model_revision="live-outer",
        parameter_names=["payload"],
        shapes=[shape if shape else [len(envelope.payload)]],
        dtype=str(getattr(envelope, "dtype", "u8") or "u8"),
        round=int(envelope.round),
        worker_id=str(envelope.worker_id),
        run_id=str(run_id),
        room_id=str(room_id),
        payload_sha256=payload_digest(envelope.payload),
    )


def accept_live_outer_envelope(
    envelope: Any,
    *,
    room_id: str,
    run_id: str,
    room_mac_key: str,
    replay_guard: ReplayGuard,
) -> NeutralOuterUpdate:
    """Verify MAC stored in envelope.extensions (`nbytes|mac=<hex>`)."""
    raw = bytes(getattr(envelope, "extensions", b"") or b"")
    text = raw.decode("ascii", errors="replace")
    mac_hex = ""
    if "|mac=" in text:
        mac_hex = text.split("|mac=", 1)[1].strip()
    update = envelope_to_neutral(envelope, room_id=room_id, run_id=run_id)
    return accept_outer_update(
        update,
        envelope.payload,
        room_mac_key=room_mac_key,
        mac_hex=mac_hex,
        replay_guard=replay_guard,
    )


def sign_live_outer_extensions(
    *, uncompressed_bytes: int, update: NeutralOuterUpdate, room_mac_key: str
) -> bytes:
    mac = sign_update(update, room_mac_key=room_mac_key)
    return f"{uncompressed_bytes}|mac={mac}".encode("ascii")


class FileReplayGuard(ReplayGuard):
    """JSON-backed replay guard so coordinator restart keeps seen triples."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}
            if isinstance(raw, dict):
                for key, mac_hex in raw.items():
                    parts = str(key).split("|")
                    if len(parts) == 3:
                        self._seen[(parts[0], int(parts[1]), parts[2])] = str(mac_hex)

    def check(self, update: NeutralOuterUpdate, *, mac_hex: str) -> None:
        super().check(update, mac_hex=mac_hex)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            f"{run_id}|{round_number}|{worker_id}": digest
            for (run_id, round_number, worker_id), digest in self._seen.items()
        }
        self.path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
