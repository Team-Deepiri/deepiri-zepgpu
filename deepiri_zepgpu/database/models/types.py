"""Shared SQLAlchemy column helpers."""

from __future__ import annotations

from enum import Enum as PyEnum
from typing import TypeVar

from sqlalchemy import Enum

E = TypeVar("E", bound=PyEnum)


def str_enum(enum_cls: type[E], **kwargs: object) -> Enum:
    """VARCHAR-backed enum matching Alembic String(50) columns (not Postgres ENUM types)."""
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda members: [m.value for m in members],
        **kwargs,
    )
