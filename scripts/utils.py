"""Shared utilities for local development scripts."""

from __future__ import annotations

import os
import subprocess


def auth_headers(token: str) -> dict[str, str]:
    """Build a bearer auth header for local API scripts."""
    return {"Authorization": f"Bearer {token}"}


def elevate_to_researcher(username: str, *, db_container: str = "zepgpu-db") -> None:
    """Promote a local Compose user to researcher (task submit requires it)."""

    sql = f"UPDATE users SET role = 'researcher' WHERE username = '{username}'"
    try:
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                db_container,
                "psql",
                "-U",
                "zepgpu",
                "-d",
                "zepgpu",
                "-c",
                sql,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return
    except (OSError, subprocess.CalledProcessError) as exc:
        db_url = os.environ.get("DATABASE_SYNC_URL") or os.environ.get("ZEPGPU_POSTGRES_URL")
        if not db_url:
            raise RuntimeError(
                "cannot elevate to researcher: docker zepgpu-db unavailable and "
                "DATABASE_SYNC_URL unset (task create requires researcher role)"
            ) from exc
        subprocess.run(
            ["psql", db_url, "-c", sql],
            check=True,
            capture_output=True,
            text=True,
        )
