"""HTTP client for peer nodes calling the ZepGPU relay VPN API."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from deepiri_zepgpu.vpn.config import vpn_settings


def relay_api_base() -> str:
    return vpn_settings.relay_api_url.rstrip("/")


def relay_vpn_path(suffix: str) -> str:
    """Full URL for /api/v1/vpn/... endpoints on the relay."""
    s = suffix if suffix.startswith("/") else f"/{suffix}"
    return f"{relay_api_base()}/api/v1/vpn{s}"


class RelayVpnClient:
    """Authenticated client for relay VPN routes."""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self._base = (base_url or relay_api_base()).rstrip("/")
        self._token = token

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def post_heartbeat(self, payload: dict[str, Any]) -> httpx.Response:
        url = f"{self._base}/api/v1/vpn/peers/heartbeat"
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(url, json=payload, headers=self._headers())
