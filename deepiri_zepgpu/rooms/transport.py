"""Room transport mode helpers (WireGuard / dial-out / overlay)."""

from __future__ import annotations

from typing import Final

TRANSPORT_WIREGUARD: Final = "wireguard"
TRANSPORT_DIALOUT: Final = "dialout"
TRANSPORT_OVERLAY: Final = "overlay"

VALID_TRANSPORT_MODES: Final = frozenset(
    {TRANSPORT_WIREGUARD, TRANSPORT_DIALOUT, TRANSPORT_OVERLAY}
)

# Overlay remains experimental until Phase 19.
EXPERIMENTAL_TRANSPORT_MODES: Final = frozenset({TRANSPORT_OVERLAY})

# Legacy pickle TaskRouter is WireGuard-only.
LEGACY_PICKLE_ALLOWED_TRANSPORTS: Final = frozenset({TRANSPORT_WIREGUARD})

DEFAULT_EXISTING_TRANSPORT_MODE: Final = TRANSPORT_WIREGUARD
DEFAULT_NEW_CLOUD_TRANSPORT_MODE: Final = TRANSPORT_DIALOUT


class InvalidTransportModeError(ValueError):
    """Raised when a transport mode string is not recognized."""


def normalize_transport_mode(value: str | None, *, default: str | None = None) -> str:
    """Normalize and validate a transport mode string."""

    if value is None or (isinstance(value, str) and not value.strip()):
        if default is None:
            raise InvalidTransportModeError("transport_mode is required")
        value = default

    mode = str(value).strip().lower()
    if mode not in VALID_TRANSPORT_MODES:
        raise InvalidTransportModeError(
            f"Invalid transport_mode {value!r}; expected one of " f"{sorted(VALID_TRANSPORT_MODES)}"
        )
    return mode


def is_experimental_transport(mode: str) -> bool:
    return normalize_transport_mode(mode) in EXPERIMENTAL_TRANSPORT_MODES


def requires_wireguard_udp(mode: str) -> bool:
    """Return True when providers typically need inbound UDP 51820."""

    return normalize_transport_mode(mode) == TRANSPORT_WIREGUARD


def allows_legacy_pickle_router(mode: str | None) -> bool:
    if mode is None:
        return False
    try:
        return normalize_transport_mode(mode) in LEGACY_PICKLE_ALLOWED_TRANSPORTS
    except InvalidTransportModeError:
        return False


def resolve_default_transport_mode(configured: str | None = None) -> str:
    """Coordinator default for newly created cloud rooms."""

    from deepiri_zepgpu.config import settings

    raw = configured if configured is not None else settings.vpn.default_transport_mode
    return normalize_transport_mode(raw, default=DEFAULT_NEW_CLOUD_TRANSPORT_MODE)
