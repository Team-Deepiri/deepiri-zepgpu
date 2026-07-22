"""Shared utilities for local development scripts."""

from __future__ import annotations


def auth_headers(token: str) -> dict[str, str]:
    """Build a bearer auth header for local API scripts."""
    return {"Authorization": f"Bearer {token}"}
