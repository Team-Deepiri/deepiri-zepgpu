"""Long-lived training worker lifecycle with outage buffering."""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

import httpx


class WorkerState(str, Enum):
    CREATED = "created"
    AUTHENTICATING = "authenticating"
    READY = "ready"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ABORTED = "aborted"


class WorkerCoordinator(Protocol):
    async def authenticate(
        self, worker_id: str, provider_token: str, run_credential: str | None
    ) -> None: ...

    async def event(self, worker_id: str, event: WorkerEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class WorkerEvent:
    event_id: str
    kind: str
    timestamp: datetime
    payload: dict[str, Any]


class HttpWorkerCoordinator:
    def __init__(
        self,
        *,
        base_url: str,
        run_id: str,
        peer_id: str,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        authorization_getter: Callable[[], str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.run_id = run_id
        self.peer_id = peer_id
        self.client = client or httpx.AsyncClient(timeout=15)
        self.max_retries = max_retries
        self._authorization = ""
        self._authorization_getter = authorization_getter

    def _current_authorization(self) -> str:
        if self._authorization_getter is not None:
            value = self._authorization_getter().strip()
            if value:
                return value
        return self._authorization

    async def authenticate(
        self, worker_id: str, provider_token: str, run_credential: str | None
    ) -> None:
        self._authorization = run_credential or provider_token
        response = await self.client.get(
            f"{self.base_url}/api/v1/training-runs/{self.run_id}/workers/{worker_id}/startup",
            params={"peer_id": self.peer_id},
            headers={"Authorization": f"Bearer {self._current_authorization()}"},
        )
        if response.status_code in {401, 403}:
            raise PermissionError("training worker authentication failed")
        if response.status_code >= 500:
            raise ConnectionError("training coordinator unavailable")
        if response.status_code != 200:
            response.raise_for_status()

    async def event(self, worker_id: str, event: WorkerEvent) -> None:
        url = f"{self.base_url}/api/v1/training-runs/{self.run_id}/workers/{worker_id}/events"
        body = {
            "event_id": event.event_id,
            "kind": event.kind,
            "timestamp": event.timestamp.isoformat(),
            "payload": event.payload,
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.post(
                    url,
                    params={"peer_id": self.peer_id},
                    headers={"Authorization": f"Bearer {self._current_authorization()}"},
                    json=body,
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt == self.max_retries:
                    raise ConnectionError("training coordinator unavailable") from exc
                await asyncio.sleep(0.1 * (2**attempt))
                continue
            if response.status_code in {401, 403}:
                raise PermissionError("training worker authorization failed")
            if response.status_code < 500:
                response.raise_for_status()
                return
            if attempt == self.max_retries:
                raise ConnectionError("training coordinator unavailable")
            await asyncio.sleep(0.1 * (2**attempt))


class PersistentTrainingWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        provider_token: str,
        coordinator: WorkerCoordinator,
        run_credential: str | None = None,
        buffer_limit: int = 1000,
    ) -> None:
        if buffer_limit < 1:
            raise ValueError("buffer_limit must be positive")
        self.worker_id = worker_id
        self.provider_token = provider_token
        self.run_credential = run_credential
        self.coordinator = coordinator
        self.state = WorkerState.CREATED
        self.round = 0
        self.restart_count = 0
        self._buffer: deque[WorkerEvent] = deque(maxlen=buffer_limit)
        self._dropped_event_count = 0
        self._abort = asyncio.Event()
        self._round_done = asyncio.Event()
        self._round_done.set()
        self._operation_task: asyncio.Task[dict[str, Any] | None] | None = None
        self._shutdown_requested = False

    @property
    def buffered_event_count(self) -> int:
        return len(self._buffer)

    @property
    def dropped_event_count(self) -> int:
        return self._dropped_event_count

    async def start(self) -> None:
        if self.state != WorkerState.CREATED:
            raise RuntimeError(f"cannot start worker in {self.state.value}")
        self.state = WorkerState.AUTHENTICATING
        try:
            await self.coordinator.authenticate(
                self.worker_id, self.provider_token, self.run_credential
            )
        except (ConnectionError, TimeoutError):
            self.state = WorkerState.RECONNECTING
            raise
        except Exception:
            self.state = WorkerState.CREATED
            raise
        self._abort.clear()
        self._shutdown_requested = False
        self.state = WorkerState.READY
        if not await self._emit("ready", {"restart_count": self.restart_count}):
            self.state = WorkerState.RECONNECTING

    async def heartbeat(self, progress: dict[str, Any] | None = None) -> None:
        if self.state in {WorkerState.CREATED, WorkerState.STOPPED, WorkerState.ABORTED}:
            raise RuntimeError(f"cannot heartbeat in {self.state.value}")
        delivered = await self._emit(
            "heartbeat",
            {"state": self.state.value, "round": self.round, "progress": progress or {}},
        )
        if not delivered and self.state != WorkerState.RUNNING:
            self.state = WorkerState.RECONNECTING

    async def progress(self, progress: dict[str, Any]) -> None:
        if self.state in {WorkerState.CREATED, WorkerState.STOPPED, WorkerState.ABORTED}:
            raise RuntimeError(f"cannot report progress in {self.state.value}")
        delivered = await self._emit("progress", {"round": self.round, "progress": progress})
        if not delivered and self.state != WorkerState.RUNNING:
            self.state = WorkerState.RECONNECTING

    async def checkpoint(self, operation: Callable[[], Awaitable[None]]) -> None:
        if self.state != WorkerState.READY:
            raise RuntimeError("worker is not ready")
        self.state = WorkerState.RUNNING
        await self._emit("checkpointing", {"round": self.round})
        try:
            await operation()
            await self._emit("checkpoint_completed", {"round": self.round})
        finally:
            self.state = WorkerState.RECONNECTING if self._buffer else WorkerState.READY

    async def log(self, message: str, payload: dict[str, Any] | None = None) -> None:
        if self.state in {WorkerState.CREATED, WorkerState.STOPPED, WorkerState.ABORTED}:
            raise RuntimeError(f"cannot log in {self.state.value}")
        delivered = await self._emit(
            "log", {"message": message, "payload": payload or {}, "round": self.round}
        )
        if not delivered and self.state != WorkerState.RUNNING:
            self.state = WorkerState.RECONNECTING

    async def run_round(
        self, round_number: int, operation: Callable[[], Awaitable[dict[str, Any] | None]]
    ) -> dict[str, Any] | None:
        if self.state != WorkerState.READY:
            raise RuntimeError("worker is not ready")
        if round_number <= self.round:
            raise ValueError("round must increase monotonically")
        self.state = WorkerState.RUNNING
        self._round_done.clear()
        await self._emit("round_started", {"round": round_number})

        async def execute_operation() -> dict[str, Any] | None:
            return await operation()

        self._operation_task = asyncio.create_task(execute_operation())
        try:
            result = await self._operation_task
            if self._abort.is_set():
                self.state = WorkerState.ABORTED
                raise asyncio.CancelledError("worker was aborted")
            self.round = round_number
            if self._shutdown_requested:
                self.state = WorkerState.STOPPING
            else:
                self.state = WorkerState.RECONNECTING if self._buffer else WorkerState.READY
            delivered = await self._emit(
                "round_completed", {"round": round_number, "result": result or {}}
            )
            if not delivered and self.state == WorkerState.READY:
                self.state = WorkerState.RECONNECTING
            return result
        except asyncio.CancelledError:
            self.state = WorkerState.ABORTED if self._abort.is_set() else WorkerState.READY
            raise
        except Exception as exc:
            self.state = WorkerState.RECONNECTING if self._buffer else WorkerState.READY
            delivered = await self._emit(
                "round_failed", {"round": round_number, "error_type": type(exc).__name__}
            )
            if not delivered:
                self.state = WorkerState.RECONNECTING
            raise
        finally:
            self._operation_task = None
            self._round_done.set()

    async def _emit(self, kind: str, payload: dict[str, Any]) -> bool:
        event = WorkerEvent(
            event_id=str(uuid.uuid4()), kind=kind, timestamp=datetime.now(UTC), payload=payload
        )
        if self._buffer:
            self._buffer_event(event)
            return False
        try:
            await self.coordinator.event(self.worker_id, event)
            return True
        except (ConnectionError, TimeoutError):
            self._buffer_event(event)
            return False

    def _buffer_event(self, event: WorkerEvent) -> None:
        terminal_kinds = {"aborted", "shutdown", "completed", "round_failed"}
        if event.kind in terminal_kinds:
            self._buffer.clear()
        elif any(item.kind in terminal_kinds for item in self._buffer):
            return
        if len(self._buffer) == self._buffer.maxlen:
            self._buffer.popleft()
            self._dropped_event_count += 1
        self._buffer.append(event)

    async def reconnect(self, *, max_retries: int = 5) -> None:
        previous_state = self.state
        self.state = WorkerState.RECONNECTING
        for attempt in range(max_retries + 1):
            try:
                await self.coordinator.authenticate(
                    self.worker_id, self.provider_token, self.run_credential
                )
                break
            except (ConnectionError, TimeoutError):
                if attempt == max_retries:
                    raise
                await asyncio.sleep(0.1 * (2**attempt))
        while self._buffer:
            await self.coordinator.event(self.worker_id, self._buffer[0])
            self._buffer.popleft()
        if previous_state in {WorkerState.STOPPED, WorkerState.ABORTED}:
            self.state = previous_state
            return
        self.state = (
            WorkerState.RUNNING if previous_state == WorkerState.RUNNING else WorkerState.READY
        )
        if not await self._emit("reconnected", {"round": self.round}):
            self.state = WorkerState.RECONNECTING

    async def complete(self, payload: dict[str, Any] | None = None) -> None:
        """Mark this worker finished so the run can reach completed when both workers do."""
        if self.state in {WorkerState.STOPPED, WorkerState.ABORTED}:
            return
        if self._operation_task:
            await self._round_done.wait()
        self.state = WorkerState.STOPPING
        await self._emit("completed", {"round": self.round, **(payload or {})})
        self.state = WorkerState.STOPPED

    async def shutdown(self, *, force: bool = False) -> None:
        if force:
            self._abort.set()
            if self._operation_task:
                self._operation_task.cancel()
                await self._round_done.wait()
            self.state = WorkerState.ABORTED
            await self._emit("aborted", {"round": self.round})
            return
        if self.state in {WorkerState.STOPPED, WorkerState.ABORTED}:
            return
        self._shutdown_requested = True
        if self._operation_task:
            await self._round_done.wait()
        self.state = WorkerState.STOPPING
        await self._emit("shutdown", {"round": self.round})
        self.state = WorkerState.STOPPED

    async def restart(self) -> None:
        if self.state != WorkerState.STOPPED:
            raise RuntimeError("only a gracefully stopped worker can restart")
        self.restart_count += 1
        self.state = WorkerState.AUTHENTICATING
        await self.coordinator.authenticate(
            self.worker_id, self.provider_token, self.run_credential
        )
        self.state = WorkerState.READY
        if not await self._emit(
            "reconnected", {"round": self.round, "restart_count": self.restart_count}
        ):
            self.state = WorkerState.RECONNECTING
