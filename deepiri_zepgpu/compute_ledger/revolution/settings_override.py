"""Temporarily override ledger settings; always restore afterward."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from deepiri_zepgpu.config import settings


@contextmanager
def ledger_settings(**overrides: Any) -> Iterator[None]:
    """Patch ``settings.ledger`` fields for the duration of the block."""
    ledger = settings.ledger
    saved: dict[str, Any] = {}
    try:
        for key, value in overrides.items():
            if not hasattr(ledger, key):
                raise AttributeError(f"LedgerSettings has no attribute {key!r}")
            saved[key] = getattr(ledger, key)
            setattr(ledger, key, value)
        yield
    finally:
        for key, value in saved.items():
            setattr(ledger, key, value)
