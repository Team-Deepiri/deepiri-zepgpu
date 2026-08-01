"""Phase 12 provider token, identity, and trust tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from deepiri_zepgpu.api.server import provider_auth
from deepiri_zepgpu.api.server.provider_auth import (
    redact_secrets,
    redact_token_text,
    verify_provider_credentials,
)
from deepiri_zepgpu.api.server.routes import rooms
from deepiri_zepgpu.node_agent.config import (
    NodeAgentConfig,
    clear_agent_identity,
    load_agent_identity,
    save_agent_identity,
    validate_coordinator_url,
)
from deepiri_zepgpu.rooms.mappers import build_invite_join_command
from deepiri_zepgpu.rooms.models import RoomJoinRequest, RoomNodeHeartbeatRequest


def test_redact_token_text_strips_bearer_and_fields() -> None:
    text = "Authorization: Bearer super-secret-token-value auth_token=also-secret-value"
    redacted = redact_token_text(text)
    assert "super-secret-token-value" not in redacted
    assert "also-secret-value" not in redacted
    assert "***REDACTED***" in redacted


def test_redact_secrets_nested_dict() -> None:
    payload = {
        "auth_token": "secret-token-here",
        "nested": {"provider_token": "another-secret-token"},
        "ok": "visible",
    }
    redacted = redact_secrets(payload)
    assert redacted["auth_token"] == "***REDACTED***"
    assert redacted["nested"]["provider_token"] == "***REDACTED***"
    assert redacted["ok"] == "visible"


def test_https_enforcement_rejects_remote_http() -> None:
    with pytest.raises(ValueError, match="Non-HTTPS"):
        validate_coordinator_url("http://example.com:8000")


def test_https_enforcement_allows_localhost_http() -> None:
    assert validate_coordinator_url("http://localhost:8000") == "http://localhost:8000"
    assert validate_coordinator_url("https://coord.example") == "https://coord.example"


def test_invite_join_command_one_liner() -> None:
    cmd = build_invite_join_command("ABC12345", "https://coord.example/")
    assert cmd == "zepgpu-node join --invite ABC12345 --coordinator https://coord.example"


def test_agent_identity_persist_and_redact(tmp_path: Path) -> None:
    path = tmp_path / "agent.json"
    config = NodeAgentConfig(
        api_base_url="https://coord.example",
        room_id=str(uuid4()),
        peer_id=str(uuid4()),
        auth_token="super-secret-provider-token",
        node_name="gpu-box",
        provider_mode="dialout",
    )
    save_agent_identity(config, path=path)
    raw = path.read_text(encoding="utf-8")
    assert "super-secret-provider-token" not in raw
    assert "auth_token_encrypted" in raw
    loaded = load_agent_identity(path)
    assert loaded.auth_token == "super-secret-provider-token"
    assert "super-secret-provider-token" not in repr(config)
    assert clear_agent_identity(path) is True
    assert not path.exists()
    assert not (tmp_path / "agent.key").exists()


@pytest.mark.asyncio
async def test_verify_provider_rejects_expired_token() -> None:
    peer_id = str(uuid4())
    peer = SimpleNamespace(
        id=peer_id,
        vpn_network_id=str(uuid4()),
        revoked_at=None,
        token_revoked_at=None,
        token_expires_at=datetime.now(UTC) - timedelta(hours=1),
        token_last_used_at=None,
        auth_token_encrypted="enc",
    )

    class FakeRepo:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _peer_id: str) -> object:
            return peer

        async def get_auth_token(self, _peer: object) -> str:
            return "valid-token"

    with (
        patch.object(provider_auth, "PeerRepository", FakeRepo),
        pytest.raises(HTTPException) as exc,
    ):
        await verify_provider_credentials(
            peer_id=peer_id,
            authorization="Bearer valid-token",
            db=MagicMock(),
        )
    assert exc.value.status_code == 401
    assert "expired" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_verify_provider_rejects_revoked_membership() -> None:
    peer_id = str(uuid4())
    peer = SimpleNamespace(
        id=peer_id,
        vpn_network_id=str(uuid4()),
        revoked_at=datetime.now(UTC),
        token_revoked_at=None,
        token_expires_at=datetime.now(UTC) + timedelta(days=1),
        token_last_used_at=None,
    )

    class FakeRepo:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _peer_id: str) -> object:
            return peer

        async def get_auth_token(self, _peer: object) -> str:
            return "valid-token"

    with (
        patch.object(provider_auth, "PeerRepository", FakeRepo),
        pytest.raises(HTTPException) as exc,
    ):
        await verify_provider_credentials(
            peer_id=peer_id,
            authorization="Bearer valid-token",
            db=MagicMock(),
        )
    assert exc.value.status_code == 403
    assert "revoked" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_verify_provider_cross_room_denial() -> None:
    peer_id = str(uuid4())
    room_a = str(uuid4())
    room_b = str(uuid4())
    peer = SimpleNamespace(
        id=peer_id,
        vpn_network_id=room_a,
        revoked_at=None,
        token_revoked_at=None,
        token_expires_at=datetime.now(UTC) + timedelta(days=1),
        token_last_used_at=None,
    )

    class FakeRepo:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _peer_id: str) -> object:
            return peer

        async def get_auth_token(self, _peer: object) -> str:
            return "valid-token"

    with (
        patch.object(provider_auth, "PeerRepository", FakeRepo),
        pytest.raises(HTTPException) as exc,
    ):
        await verify_provider_credentials(
            peer_id=peer_id,
            authorization="Bearer valid-token",
            db=MagicMock(),
            room_id=room_b,
        )
    assert exc.value.status_code == 403
    assert "not valid for this room" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_verify_provider_rejects_rotated_token() -> None:
    """After rotation, the previous plaintext token must fail compare_digest."""
    peer_id = str(uuid4())
    peer = SimpleNamespace(
        id=peer_id,
        vpn_network_id=str(uuid4()),
        revoked_at=None,
        token_revoked_at=None,
        token_expires_at=datetime.now(UTC) + timedelta(days=1),
        token_last_used_at=None,
        token_rotated_at=datetime.now(UTC),
    )

    class FakeRepo:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _peer_id: str) -> object:
            return peer

        async def get_auth_token(self, _peer: object) -> str:
            return "new-rotated-token"

    with (
        patch.object(provider_auth, "PeerRepository", FakeRepo),
        pytest.raises(HTTPException) as exc,
    ):
        await verify_provider_credentials(
            peer_id=peer_id,
            authorization="Bearer old-token-value",
            db=MagicMock(),
        )
    assert exc.value.status_code == 401
    assert "Invalid provider credentials" in str(exc.value.detail)


def test_room_heartbeat_uses_provider_token(monkeypatch: pytest.MonkeyPatch) -> None:
    room_id = uuid4()
    peer_id = uuid4()
    peer = SimpleNamespace(
        id=peer_id,
        vpn_network_id=room_id,
        user_id=uuid4(),
        user=SimpleNamespace(username="provider"),
        vpn_ip="10.8.0.2",
        online_status=rooms.PeerOnlineStatus.OFFLINE,
        is_gpu_host=False,
        last_seen=datetime.now(UTC),
        gpu_shares=[],
        agent_version=None,
        node_name=None,
        provider_mode=None,
        revoked_at=None,
    )

    verify = AsyncMock(return_value=peer)
    monkeypatch.setattr(rooms, "verify_provider_credentials", verify)

    class FakePeerRepository:
        last_instance = None

        def __init__(self, _db: object) -> None:
            FakePeerRepository.last_instance = self

        async def heartbeat(self, **kwargs):
            peer.online_status = rooms.PeerOnlineStatus.ONLINE
            peer.is_gpu_host = bool(kwargs.get("mark_gpu_host"))
            return peer

        async def get_by_id(self, _peer_id: str):
            return peer

    class FakeGpuShareRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def upsert(self, **_kwargs):
            return None

        async def list_by_peer(self, _peer_id: str):
            return []

    monkeypatch.setattr(rooms, "PeerRepository", FakePeerRepository)
    monkeypatch.setattr(rooms, "GpuShareRepository", FakeGpuShareRepository)
    monkeypatch.setattr(rooms, "emit_room_event", AsyncMock())

    response = asyncio.run(
        rooms.room_node_heartbeat(
            room_id=str(room_id),
            peer_id=str(peer_id),
            data=RoomNodeHeartbeatRequest(
                is_online=True,
                agent_version="0.1.0",
                node_name="box-1",
                provider_mode="dialout",
            ),
            authorization="Bearer provider-token",
            db=SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock()),
        )
    )

    verify.assert_awaited_once()
    assert verify.await_args.kwargs["room_id"] == str(room_id)
    assert response.is_online is True
    assert peer.agent_version == "0.1.0"
    assert peer.node_name == "box-1"


def test_join_room_issues_provider_token(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = uuid4()
    room_id = uuid4()
    invite = SimpleNamespace(
        id=uuid4(),
        code="ABC123",
        vpn_network_id=room_id,
        is_revoked=False,
        used_count=0,
        max_uses=3,
        expires_at=None,
    )
    room = SimpleNamespace(
        id=room_id,
        name="Room",
        is_active=True,
        host_id=uuid4(),
        cidr="10.8.0.0/24",
        created_at=datetime.now(UTC),
        updated_at=None,
    )
    created_peer = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        vpn_network_id=room_id,
        user=SimpleNamespace(username="provider"),
        online_status=SimpleNamespace(value="offline"),
        created_at=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        node_name=None,
        provider_mode=None,
        token_expires_at=datetime.now(UTC) + timedelta(days=90),
        wireguard_public_key="pub",
        private_key_encrypted="enc",
    )

    class FakeInviteRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_code(self, _code: str):
            return invite

        async def use(self, _invite):
            invite.used_count += 1

    class FakeNetworkRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _room_id: str):
            return room

    class FakePeerRepository:
        def __init__(self, _db: object) -> None:
            self.db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

        async def get_by_network(self, _room_id: str):
            return []

        async def create(self, **kwargs):
            return created_peer

        async def get_by_id(self, _peer_id: str):
            return created_peer

    monkeypatch.setattr(rooms, "VpnInviteRepository", FakeInviteRepository)
    monkeypatch.setattr(rooms, "VpnNetworkRepository", FakeNetworkRepository)
    monkeypatch.setattr(rooms, "PeerRepository", FakePeerRepository)
    monkeypatch.setattr(rooms, "generate_keypair", lambda: ("priv", "pub"))
    monkeypatch.setattr(rooms, "encrypt_value", lambda v: f"enc-{v}")
    monkeypatch.setattr(rooms, "allocate_vpn_ip", lambda *_a, **_k: "10.8.0.2")
    monkeypatch.setattr(rooms, "issue_provider_token", AsyncMock(return_value="issued-token"))
    monkeypatch.setattr(rooms.manager, "grant_room_membership", AsyncMock())
    monkeypatch.setattr(rooms, "emit_room_event", AsyncMock())

    response = asyncio.run(
        rooms.join_room(
            data=RoomJoinRequest(invite_code="ABC123", node_name="box"),
            user=SimpleNamespace(id=user_id),
            db=SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock()),
        )
    )

    assert response.auth_token == "issued-token"
    assert response.member.id == created_peer.id
    assert "issued-token" not in json.dumps(
        {k: v for k, v in response.model_dump(mode="json").items() if k != "auth_token"}
    )


def test_revoke_room_provider_eager_loads_gpu_shares(  # noqa: C901
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revoke must not touch the dynamic gpu_shares relationship (async MissingGreenlet)."""
    host_id = uuid4()
    room_id = uuid4()
    peer_id = uuid4()
    room = SimpleNamespace(id=room_id, host_id=host_id, is_active=True)
    peer = SimpleNamespace(
        id=peer_id,
        user_id=uuid4(),
        vpn_network_id=room_id,
        revoked_at=None,
        user=SimpleNamespace(username="provider"),
        online_status=SimpleNamespace(value="offline"),
        last_seen=datetime.now(UTC),
        is_gpu_host=True,
        vpn_ip="10.8.0.2",
        node_name="box",
        agent_version="0.1.0",
        provider_mode="dialout",
        health_state="healthy",
        health_reason=None,
        last_claim_at=None,
        recent_failures=0,
        capabilities_json=None,
        path_type=None,
        path_class=None,
        coordinator_rtt_ms=None,
        path_measured_at=None,
        path_measurement_kind=None,
        gpu_shares=object(),  # would raise if iterated
    )

    class FakeNetworkRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _room_id: str):
            return room

        async def get_peer(self, *_args, **_kwargs):
            return peer

    class FakePeerRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id(self, _peer_id: str):
            return peer

        async def revoke_provider(self, p):
            p.revoked_at = datetime.now(UTC)
            return p

    class FakeGpuShareRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def deactivate_peer_gpus(self, _peer_id: str) -> int:
            return 0

        async def list_by_peer(self, _peer_id: str):
            return []

    class FakeTaskRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def list_active_for_peer(self, peer_id: str):
            return []

    monkeypatch.setattr(rooms, "VpnNetworkRepository", FakeNetworkRepository)
    monkeypatch.setattr(rooms, "PeerRepository", FakePeerRepository)
    monkeypatch.setattr(rooms, "GpuShareRepository", FakeGpuShareRepository)
    monkeypatch.setattr(rooms, "NodeTaskRepository", FakeTaskRepository)
    monkeypatch.setattr(rooms, "emit_room_event", AsyncMock())
    monkeypatch.setattr(rooms, "_ensure_room_member", AsyncMock(return_value=room))
    monkeypatch.setattr(rooms, "_ensure_room_host", AsyncMock())

    response = asyncio.run(
        rooms.revoke_room_provider(
            room_id=str(room_id),
            peer_id=str(peer_id),
            user=SimpleNamespace(id=host_id),
            db=SimpleNamespace(get=AsyncMock(return_value=None)),
        )
    )
    assert response.peer_id == peer_id
    assert response.failed_assignments == 0
    assert peer.revoked_at is not None
