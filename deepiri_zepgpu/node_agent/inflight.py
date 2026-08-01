"""Local in-flight assignment state under ~/.zepgpu/."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepiri_zepgpu.node_agent.config import DEFAULT_AGENT_DIR, default_agent_path

DEFAULT_INFLIGHT_PATH = DEFAULT_AGENT_DIR / "inflight.json"


def default_inflight_path() -> Path:
    override = os.environ.get("ZEPGPU_AGENT_INFLIGHT")
    if override:
        return Path(override).expanduser()
    # Keep inflight next to agent.json when identity path is customized.
    agent = default_agent_path()
    return agent.parent / "inflight.json"


def load_inflight(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path).expanduser() if path else default_inflight_path()
    if not config_path.exists():
        return {"assignments": {}, "updated_at": None}
    try:
        with config_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"assignments": {}, "updated_at": None}
    if not isinstance(payload, dict):
        return {"assignments": {}, "updated_at": None}
    assignments = payload.get("assignments")
    if not isinstance(assignments, dict):
        assignments = {}
    return {"assignments": assignments, "updated_at": payload.get("updated_at")}


def save_inflight(state: dict[str, Any], path: str | Path | None = None) -> Path | None:
    """Persist in-flight state. Returns path on success, None if unwritable."""
    config_path = Path(path).expanduser() if path else default_inflight_path()
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    payload = {
        "assignments": state.get("assignments") or {},
        "updated_at": datetime.now(UTC).isoformat(),
    }
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(config_path.parent), prefix=".inflight-", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, config_path)
        tmp_name = None
        return config_path
    except OSError:
        return None
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def list_inflight_ids(path: str | Path | None = None) -> list[str]:
    state = load_inflight(path)
    return sorted(str(key) for key in (state.get("assignments") or {}))


def upsert_inflight(
    assignment_id: str,
    *,
    status: str,
    task_id: str | None = None,
    claim_generation: int | None = None,
    lease_expires_at: str | None = None,
    path: str | Path | None = None,
) -> None:
    state = load_inflight(path)
    assignments = dict(state.get("assignments") or {})
    existing = dict(assignments.get(assignment_id) or {})
    existing.update(
        {
            "assignment_id": assignment_id,
            "status": status,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    if task_id is not None:
        existing["task_id"] = task_id
    if claim_generation is not None:
        existing["claim_generation"] = claim_generation
    if lease_expires_at is not None:
        existing["lease_expires_at"] = lease_expires_at
    assignments[assignment_id] = existing
    save_inflight({"assignments": assignments}, path=path)


def remove_inflight(assignment_id: str, path: str | Path | None = None) -> None:
    state = load_inflight(path)
    assignments = dict(state.get("assignments") or {})
    if assignment_id in assignments:
        del assignments[assignment_id]
        save_inflight({"assignments": assignments}, path=path)


def clear_inflight(path: str | Path | None = None) -> None:
    save_inflight({"assignments": {}}, path=path)
