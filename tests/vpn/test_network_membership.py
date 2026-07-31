"""Unit tests for VpnNetworkRepository.user_belongs_to_network."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

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
    statement = str(db.execute.await_args.args[0])
    assert "vpn_peers.user_id" in statement
    assert "vpn_peers.vpn_network_id" in statement
    assert "LIMIT" in statement


@pytest.mark.asyncio
async def test_user_belongs_to_network_false_when_no_peer() -> None:
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    repo = VpnNetworkRepository(db)
    assert await repo.user_belongs_to_network("user-1", "room-1") is False
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_persists_host_id() -> None:
    host_id = str(uuid4())
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    with patch("deepiri_zepgpu.vpn.repositories.VpnNetwork") as network_cls:
        network_instance = MagicMock()
        network_cls.return_value = network_instance
        repo = VpnNetworkRepository(db)
        result = await repo.create(name="Room", host_id=host_id)

    network_cls.assert_called_once()
    assert network_cls.call_args.kwargs["host_id"] == host_id
    assert result is network_instance
    db.add.assert_called_once_with(network_instance)
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(network_instance)
