"""Provider-authenticated WSS client for assignment push with reconnect."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


def _http_to_ws(base_url: str) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, parsed.path, "", "", ""))


class ProviderAssignmentSocket:
    """Connect to /api/v1/ws/provider with backoff + jitter reconnect."""

    def __init__(
        self,
        *,
        base_url: str,
        room_id: str,
        peer_id: str,
        token: str,
        on_message: MessageHandler,
        min_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.room_id = room_id
        self.peer_id = peer_id
        self.token = token
        self.on_message = on_message
        self.min_backoff_seconds = min_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._running = False
        self._ws: Any = None
        self._task: asyncio.Task[None] | None = None
        self._consecutive_failures = 0

    def _ws_url(self) -> str:
        root = _http_to_ws(self.base_url)
        query = urlencode(
            {
                "token": self.token,
                "peer_id": self.peer_id,
                "room_id": self.room_id,
            }
        )
        return f"{root}/api/v1/ws/provider?{query}"

    def _backoff(self) -> float:
        base = min(
            self.max_backoff_seconds,
            self.min_backoff_seconds * (2 ** min(self._consecutive_failures, 6)),
        )
        jitter = random.uniform(0, base * 0.25)
        return float(base + jitter)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._connect_once()
                self._consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                self._consecutive_failures += 1
                delay = self._backoff()
                logger.warning(
                    "Provider WSS disconnected; reconnecting in %.2fs (failures=%s)",
                    delay,
                    self._consecutive_failures,
                )
                with contextlib.suppress(Exception):
                    await self.on_message({"type": "reconnecting", "delay_seconds": delay})
                await asyncio.sleep(delay)

    async def _connect_once(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "websockets package required for provider WSS; HTTPS poll fallback still works"
            ) from exc

        url = self._ws_url()
        logger.info("Connecting provider WSS for peer %s", self.peer_id)
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
            self._ws = ws
            async for raw in ws:
                if not self._running:
                    break
                try:
                    import json

                    message = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    logger.exception("Invalid provider WSS payload")
                    continue
                if isinstance(message, dict):
                    await self.on_message(message)
        self._ws = None
