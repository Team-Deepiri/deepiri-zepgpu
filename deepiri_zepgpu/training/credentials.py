"""Short-lived worker run credentials signed by the coordinator."""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
import uuid
from dataclasses import dataclass

_VERSION = 2
_BODY = struct.Struct("!B16s16s16s16s16sq")


@dataclass(frozen=True, slots=True)
class RunCredential:
    room_id: str
    run_id: str
    worker_id: str
    peer_id: str
    credential_id: str
    expires_at: int


def credential_id_hash(credential_id: str) -> str:
    return hashlib.sha256(uuid.UUID(credential_id).bytes).hexdigest()


def _hkdf_sha256(*, ikm: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 HKDF-SHA256 with a fixed application salt (Python 3.11 compatible)."""

    salt = b"zepgpu-hkdf-v1"
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    previous = b""
    counter = 1
    while len(okm) < length:
        previous = hmac.new(prk, previous + info + bytes([counter]), hashlib.sha256).digest()
        okm += previous
        counter += 1
    return okm[:length]


def issue_data_plane_secret(run_id: str, secret: bytes) -> str:
    """Deterministic run-scoped HMAC key shared by all workers on a run."""

    return _hkdf_sha256(ikm=secret, info=f"zepgpu-data-plane:{run_id}".encode()).hex()


def issue_room_mac_key(room_id: str, secret: bytes) -> str:
    """Deterministic room-scoped MAC key for outer-update integrity."""

    return _hkdf_sha256(ikm=secret, info=f"zepgpu-room-mac:{room_id}".encode()).hex()


def issue_run_credential(credential: RunCredential, secret: bytes) -> str:
    body = _BODY.pack(
        _VERSION,
        uuid.UUID(credential.room_id).bytes,
        uuid.UUID(credential.run_id).bytes,
        uuid.UUID(credential.worker_id).bytes,
        uuid.UUID(credential.peer_id).bytes,
        uuid.UUID(credential.credential_id).bytes,
        credential.expires_at,
    )
    signature = hmac.new(secret, body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + signature).decode("ascii")


def verify_run_credential(token: str, secret: bytes, now: int | None = None) -> RunCredential:
    try:
        raw = base64.b64decode(token.encode("ascii"), altchars=b"-_", validate=True)
    except Exception as exc:
        raise ValueError("malformed run credential") from exc
    if len(raw) != _BODY.size + 32:
        raise ValueError("malformed run credential")
    body, provided = raw[: _BODY.size], raw[_BODY.size :]
    expected = hmac.new(secret, body, hashlib.sha256).digest()
    if not hmac.compare_digest(provided, expected):
        raise ValueError("invalid run credential")
    version, room, run, worker, peer, credential_id, expires_at = _BODY.unpack(body)
    if version != _VERSION:
        raise ValueError("unsupported run credential version")
    if expires_at <= (int(time.time()) if now is None else now):
        raise ValueError("expired run credential")
    return RunCredential(
        room_id=str(uuid.UUID(bytes=room)),
        run_id=str(uuid.UUID(bytes=run)),
        worker_id=str(uuid.UUID(bytes=worker)),
        peer_id=str(uuid.UUID(bytes=peer)),
        credential_id=str(uuid.UUID(bytes=credential_id)),
        expires_at=expires_at,
    )
