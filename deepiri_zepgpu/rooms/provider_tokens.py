"""Room-scoped provider token issuance helpers (non-API layer).

Repositories and API routes share this module so the VPN repository layer
never imports ``deepiri_zepgpu.api.server``.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.models.vpn_models import Peer


class ProviderRevokedError(ValueError):
    """Raised when issuing credentials for a revoked provider membership/token."""


def provider_token_ttl() -> timedelta:
    days = max(1, int(settings.vpn.provider_token_expire_days))
    return timedelta(days=days)


async def issue_provider_token(
    peer_repo: object,
    peer: Peer,
    *,
    rotate: bool = False,
    provider_mode: str | None = None,
) -> str:
    """Create or rotate a room-scoped provider token for ``peer``.

    ``peer_repo`` is a ``PeerRepository`` (duck-typed to avoid circular imports).
    """

    if (
        getattr(peer, "revoked_at", None) is not None
        or getattr(peer, "token_revoked_at", None) is not None
    ):
        raise ProviderRevokedError("Cannot issue credentials for a revoked provider")

    now = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    await peer_repo.set_auth_token(peer, token)  # type: ignore[attr-defined]
    refreshed = await peer_repo.get_by_id(str(peer.id))  # type: ignore[attr-defined]
    if refreshed is None:
        raise LookupError("Peer not found after token issue")

    refreshed.token_expires_at = now + provider_token_ttl()
    refreshed.token_revoked_at = None
    if rotate:
        refreshed.token_rotated_at = now
    if provider_mode:
        refreshed.provider_mode = provider_mode
    elif refreshed.provider_mode is None:
        refreshed.provider_mode = settings.vpn.default_provider_mode
    await peer_repo.db.commit()  # type: ignore[attr-defined]
    await peer_repo.db.refresh(refreshed)  # type: ignore[attr-defined]
    return token
