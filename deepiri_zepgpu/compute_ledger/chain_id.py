"""Chain ID helpers for global vs per-VPN-network ledger isolation."""

from __future__ import annotations

from deepiri_zepgpu.config import settings


def chain_id_for_network(network_id: str | None = None) -> str:
    """Return ledger chain id.

    - No network → global chain (`settings.ledger.chain_id`)
    - With network → `{base}:vpn:{network_id}`
    """
    base = settings.ledger.chain_id
    if not network_id:
        return base
    return f"{base}:vpn:{network_id}"


def parse_network_id(chain_id: str) -> str | None:
    """Extract VPN network id from a scoped chain id, if present."""
    marker = ":vpn:"
    if marker not in chain_id:
        return None
    return chain_id.split(marker, 1)[1] or None
