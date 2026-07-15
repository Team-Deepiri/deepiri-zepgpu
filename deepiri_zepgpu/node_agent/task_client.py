"""HTTP client for node-agent task lifecycle polling."""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx


class NodeTaskClient:
    """Client used by node agents to poll and update assigned tasks."""

    def __init__(
        self,
        *,
        base_url: str,
        room_id: str,
        peer_id: str,
        token: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.room_id = room_id
        self.peer_id = peer_id
        self.token = token
        self.timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(timeout=self.timeout_seconds)

    async def __aenter__(self) -> NodeTaskClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    async def poll_pending(self, *, limit: int = 1) -> list[dict[str, Any]]:
        response = await self._client.get(
            f"{self.base_url}/api/v1/node-tasks/rooms/"
            f"{self.room_id}/nodes/{self.peer_id}/tasks/pending",
            params={"limit": limit},
            headers=self._headers(),
        )
        response.raise_for_status()
        return list(response.json())

    async def accept(self, assignment_id: str) -> dict[str, Any]:
        return await self._post_lifecycle(assignment_id, "accept", {})

    async def start(self, assignment_id: str) -> dict[str, Any]:
        return await self._post_lifecycle(assignment_id, "start", {})

    async def complete(
        self,
        assignment_id: str,
        *,
        result_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._post_lifecycle(
            assignment_id,
            "complete",
            {"result_metadata": result_metadata},
        )

    async def fail(self, assignment_id: str, *, error: str) -> dict[str, Any]:
        return await self._post_lifecycle(
            assignment_id,
            "fail",
            {"error": error},
        )

    async def log(
        self,
        assignment_id: str,
        *,
        event_type: str = "node_task_log",
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._client.post(
            f"{self.base_url}/api/v1/node-tasks/{assignment_id}/logs",
            params={"peer_id": self.peer_id},
            json={
                "event_type": event_type,
                "message": message,
                "payload": payload or {},
            },
            headers=self._headers(),
        )
        response.raise_for_status()
        return dict(response.json())

    async def _post_lifecycle(
        self,
        assignment_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._client.post(
            f"{self.base_url}/api/v1/node-tasks/{assignment_id}/{action}",
            params={"peer_id": self.peer_id},
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        return dict(response.json())
