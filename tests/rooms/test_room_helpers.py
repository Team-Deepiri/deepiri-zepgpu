"""Tests for room route helper functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server.routes.rooms import _expires_at_to_days


def test_expires_at_to_days_defaults_to_seven_days() -> None:
    assert _expires_at_to_days(None) == 7


def test_expires_at_to_days_rounds_future_expiration_up() -> None:
    expires_at = datetime.now(UTC) + timedelta(hours=25)

    assert _expires_at_to_days(expires_at) == 2


def test_expires_at_to_days_rejects_past_expiration() -> None:
    expires_at = datetime.now(UTC) - timedelta(minutes=1)

    with pytest.raises(HTTPException) as exc_info:
        _expires_at_to_days(expires_at)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invite expiration must be in the future"
