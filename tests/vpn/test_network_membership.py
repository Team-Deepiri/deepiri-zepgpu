"""Unit tests for VpnNetworkRepository.user_belongs_to_network."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from deepiri_zepgpu.vpn.repositories import VpnNetworkRepository


@pytest.mark.asyncio
async def test_user_belongs_to_network_true_when_peer_exists() -> None:
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = "peer-id"
    db.execute = AsyncMock(return_value=result)

    repo = VpnNetworkRepository(db)
    assert await repo.user_belongs_to_network("user-1", "room-1") is True
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_belongs_to_network_false_when_no_peer() -> None:
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    repo = VpnNetworkRepository(db)
    assert await repo.user_belongs_to_network("user-1", "room-1") is False
    db.execute.assert_awaited_once()
