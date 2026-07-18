"""End-to-end tests for room task dispatch (opt-in)."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.e2e

E2E_ENABLED = os.getenv("E2E_ROOMS_BACKEND") == "1"


@pytest.mark.skipif(not E2E_ENABLED, reason="Set E2E_ROOMS_BACKEND=1 with Docker Compose running")
def test_room_auto_dispatch_happy_path_placeholder() -> None:
    """Placeholder e2e scenario documented in Phase 4 plan.

    Full flow requires live stack:
    1. Create room and join client with simulated GPU heartbeat
    2. POST /api/v1/tasks with dispatch_mode=room_auto
    3. Assert assigned status and assignment record
    """
    assert E2E_ENABLED
