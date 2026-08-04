"""ZepGPU API server package."""

from __future__ import annotations

from typing import Any

__all__ = ["app"]


def __getattr__(name: str) -> Any:
    """Load the FastAPI application lazily to avoid package import cycles."""
    if name == "app":
        from deepiri_zepgpu.api.server.main import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
