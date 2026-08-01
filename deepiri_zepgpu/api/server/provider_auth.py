"""Room-scoped provider token verification and redaction helpers.

Human JWTs are used only for invite join. After join, heartbeat / claim /
logs / complete / fail authenticate with the peer's room-scoped provider
token (``Peer.auth_token_encrypted``).
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_db_session
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.models.vpn_models import Peer
from deepiri_zepgpu.vpn.repositories import PeerRepository

_REDACTED = "***REDACTED***"
# Bearer tokens and similar secrets that must never appear in logs/errors/UI.
_TOKEN_PATTERN = re.compile(
    r"(bearer\s+)([A-Za-z0-9_\-\.=+/]{12,})"
    r"|(\"?(?:auth_token|provider_token|access_token|token)\"?\s*[:=]\s*[\"']?)"
    r"([A-Za-z0-9_\-\.=+/]{12,})",
    re.IGNORECASE,
)


def redact_secrets(value: Any) -> Any:
    """Recursively redact credential-looking values from nested structures."""

    if value is None:
        return None
    if isinstance(value, str):
        return redact_token_text(value)
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            key_str = str(key).lower()
            if key_str in {
                "auth_token",
                "provider_token",
                "access_token",
                "token",
                "password",
                "authorization",
            }:
                redacted[key] = _REDACTED
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def redact_token_text(text: str) -> str:
    """Redact bearer tokens and credential fields from free-form text."""

    def _replace(match: re.Match[str]) -> str:
        if match.group(1):
            return f"{match.group(1)}{_REDACTED}"
        return f"{match.group(3)}{_REDACTED}"

    return _TOKEN_PATTERN.sub(_replace, text)


def _parse_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token


def provider_token_ttl() -> timedelta:
    days = max(1, int(settings.vpn.provider_token_expire_days))
    return timedelta(days=days)


async def issue_provider_token(
    peer_repo: PeerRepository,
    peer: Peer,
    *,
    rotate: bool = False,
    provider_mode: str | None = None,
) -> str:
    """Create or rotate a room-scoped provider token for ``peer``."""

    now = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    await peer_repo.set_auth_token(peer, token)
    # Refresh after commit so subsequent attribute writes persist.
    refreshed = await peer_repo.get_by_id(str(peer.id))
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Peer not found")

    refreshed.token_expires_at = now + provider_token_ttl()
    refreshed.token_revoked_at = None
    if rotate:
        refreshed.token_rotated_at = now
    if provider_mode:
        refreshed.provider_mode = provider_mode
    elif refreshed.provider_mode is None:
        refreshed.provider_mode = settings.vpn.default_provider_mode
    await peer_repo.db.commit()
    await peer_repo.db.refresh(refreshed)
    return token


async def verify_provider_credentials(
    *,
    peer_id: str,
    authorization: str | None,
    db: AsyncSession,
    room_id: str | None = None,
    touch_last_used: bool = True,
) -> Peer:
    """Verify a room-scoped provider bearer token for ``peer_id``.

    Enforces expiry, token revocation, membership revoke, and optional
    room scoping (cross-room denial).
    """

    provided_token = _parse_bearer(authorization)
    peer_repo = PeerRepository(db)
    peer = await peer_repo.get_by_id(peer_id)
    if peer is None:
        raise HTTPException(status_code=404, detail="Peer not found")

    if room_id is not None and str(peer.vpn_network_id) != str(room_id):
        raise HTTPException(
            status_code=403, detail="Provider credentials are not valid for this room"
        )

    if peer.revoked_at is not None:
        raise HTTPException(status_code=403, detail="Provider has been revoked")

    if peer.token_revoked_at is not None:
        raise HTTPException(status_code=401, detail="Provider token has been revoked")

    if peer.token_expires_at is not None:
        expires = peer.token_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires:
            raise HTTPException(status_code=401, detail="Provider token has expired")

    stored_token = await peer_repo.get_auth_token(peer)
    if not stored_token or not secrets.compare_digest(stored_token, provided_token):
        raise HTTPException(status_code=401, detail="Invalid provider credentials")

    if touch_last_used:
        peer.token_last_used_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(peer)

    return peer


async def get_verified_provider(
    peer_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> Peer:
    """FastAPI dependency: verify provider token for ``peer_id`` (query/path)."""

    return await verify_provider_credentials(
        peer_id=peer_id,
        authorization=authorization,
        db=db,
    )


async def get_verified_room_provider(
    room_id: str,
    peer_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> Peer:
    """FastAPI dependency: verify provider token scoped to ``room_id``."""

    return await verify_provider_credentials(
        peer_id=peer_id,
        authorization=authorization,
        db=db,
        room_id=room_id,
    )


# Backwards-compatible alias used by node-task routes.
get_verified_peer = get_verified_provider
