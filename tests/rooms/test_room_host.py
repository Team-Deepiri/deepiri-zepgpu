"""Tests for room host authorization helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server.routes import rooms


def test_ensure_room_host_allows_matching_host_id() -> None:
    user_id = uuid4()
    room = SimpleNamespace(id=uuid4(), host_id=user_id)

    asyncio.run(rooms._ensure_room_host(room, str(user_id)))


def test_ensure_room_host_rejects_non_host() -> None:
    room = SimpleNamespace(id=uuid4(), host_id=uuid4())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(rooms._ensure_room_host(room, str(uuid4())))

    assert exc_info.value.status_code == 403
