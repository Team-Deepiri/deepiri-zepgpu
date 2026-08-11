"""Persist worker identity without embedding HMAC material in identity.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DATA_PLANE_HMAC_FILE = "data_plane.hmac"
ROOM_MAC_FILE = "room.mac"


def _write_owner_only(path: Path, material: str) -> None:
    """Write ephemeral worker HMAC material with 0o600 (same trust as run.cred)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        # Owner-only ephemeral work-dir HMAC (same trust boundary as run.cred).
        os.write(fd, material.encode("utf-8"))  # codeql[py/clear-text-storage-sensitive-data]
    finally:
        os.close(fd)


def persist_worker_identity(work_dir: Path, identity: dict[str, Any]) -> None:
    """Write public identity.json plus owner-only HMAC sidecars."""
    work_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(identity)
    plane_hmac = payload.pop("data_plane_secret", None)
    room_mac = payload.pop("room_mac_key", None)
    identity_path = work_dir / "identity.json"
    identity_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    identity_path.chmod(0o600)
    if plane_hmac:
        # codeql[py/clear-text-storage-sensitive-data]: owner-only work-dir HMAC, same as run.cred
        _write_owner_only(work_dir / DATA_PLANE_HMAC_FILE, str(plane_hmac))
    if room_mac:
        # codeql[py/clear-text-storage-sensitive-data]: owner-only work-dir MAC key, same as run.cred
        _write_owner_only(work_dir / ROOM_MAC_FILE, str(room_mac))


def hydrate_worker_identity(work_dir: Path, identity: dict[str, Any]) -> dict[str, Any]:
    """Merge sidecar HMAC files back into the in-memory identity dict."""
    hmac_path = work_dir / DATA_PLANE_HMAC_FILE
    if hmac_path.is_file():
        identity["data_plane_secret"] = hmac_path.read_text(encoding="utf-8").strip()
    mac_path = work_dir / ROOM_MAC_FILE
    if mac_path.is_file():
        identity["room_mac_key"] = mac_path.read_text(encoding="utf-8").strip()
    return identity
