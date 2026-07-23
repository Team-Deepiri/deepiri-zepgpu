"""UUID helpers for ORM inserts against Postgres UUID columns."""

from __future__ import annotations

from uuid import UUID, uuid4


def as_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def new_uuid() -> UUID:
    return uuid4()


def uuid_str(value: str | UUID | None) -> str | None:
    if value is None:
        return None
    return str(value)
