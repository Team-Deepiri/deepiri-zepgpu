"""WebSocket-based monitoring dashboard."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from datetime import datetime
from typing import Any, Callable, Optional

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False


class DashboardEvent:
    """Dashboard event types."""
    TASK_SUBMITTED = "task_submitted"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    GPU_UTILIZATION = "gpu_utilization"
    SYSTEM_METRICS = "system_metrics"
    QUEUE_UPDATE = "queue_update"
    ALERT = "alert"


class MonitoringDashboard:
    """Real-time monitoring dashboard via WebSocket."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        metrics_collector: Optional[Any] = None,
    ):
        self._host = host
        self._port = port
        self._collector = metrics_collector
        self._clients: set[Any] = set()
        self._server_task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = threading.Lock()

    async def start(self) -> None:
        """Start the dashboard server."""
        if not WEBSOCKETS_AVAILABLE:
            raise RuntimeError("websockets library not available")

        self._running = True
        self._server_task = asyncio.create_task(self._run_server())

    async def stop(self) -> None:
        """Stop the dashboard server."""
        self._running = False
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

    async def _run_server(self) -> None:
        """Run WebSocket server."""
        async with websockets.serve(self._handle_client, self._host, self._port):
            while self._running:
                await asyncio.sleep(1)

    async def _handle_client(self, websocket: Any, path: str) -> None:
        """Handle client connection."""
        with self._lock:
            self._clients.add(websocket)

        try:
            await websocket.send(json.dumps({
                "type": "connected",
                "timestamp": datetime.utcnow().isoformat(),
                "message": "Connected to DeepIRI GPU Monitor",
            }))

            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_client_message(websocket, data)
                except json.JSONDecodeError:
                    pass

        except Exception:
            pass
        finally:
            with self._lock:
                self._clients.discard(websocket)

    async def _handle_client_message(self, websocket: Any, data: dict[str, Any]) -> None:
        """Handle incoming client message."""
        command = data.get("command")

        if command == "subscribe":
            event_types = data.get("events", [])
            await websocket.send(json.dumps({
                "type": "subscribed",
                "events": event_types,
            }))

        elif command == "get_status":
            status = self._get_system_status()
            await websocket.send(json.dumps({
                "type": "status",
                "data": status,
            }))

        elif command == "get_metrics":
            if self._collector:
                summary = self._collector.get_summary()
                await websocket.send(json.dumps({
                    "type": "metrics",
                    "data": summary,
                }))

    def _get_system_status(self) -> dict[str, Any]:
        """Get current system status."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "connected_clients": len(self._clients),
        }

    async def broadcast_event(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Broadcast event to all connected clients."""
        message = json.dumps({
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
        })

        with self._lock:
            clients = list(self._clients)

        disconnected = []
        for client in clients:
            try:
                await client.send(message)
            except Exception:
                disconnected.append(client)

        with self._lock:
            for client in disconnected:
                self._clients.discard(client)

    async def broadcast_task_update(self, task_id: str, status: str, **kwargs: Any) -> None:
        """Broadcast task status update."""
        event_type = {
            "submitted": DashboardEvent.TASK_SUBMITTED,
            "started": DashboardEvent.TASK_STARTED,
            "completed": DashboardEvent.TASK_COMPLETED,
            "failed": DashboardEvent.TASK_FAILED,
        }.get(status, DashboardEvent.QUEUE_UPDATE)

        await self.broadcast_event(event_type, {
            "task_id": task_id,
            "status": status,
            **kwargs,
        })

    async def broadcast_gpu_metrics(self, metrics: dict[str, Any]) -> None:
        """Broadcast GPU metrics update."""
        await self.broadcast_event(DashboardEvent.GPU_UTILIZATION, metrics)

    async def broadcast_system_metrics(self, metrics: dict[str, Any]) -> None:
        """Broadcast system metrics update."""
        await self.broadcast_event(DashboardEvent.SYSTEM_METRICS, metrics)

    async def broadcast_alert(self, alert_type: str, message: str, **kwargs: Any) -> None:
        """Broadcast alert."""
        await self.broadcast_event(DashboardEvent.ALERT, {
            "alert_type": alert_type,
            "message": message,
            **kwargs,
        })


class PrometheusExporter:
    """Export metrics to Prometheus."""

    def __init__(self):
        self._metrics: dict[str, float] = {}
        self._lock = threading.Lock()

    def set_gauge(self, name: str, value: float, labels: Optional[dict[str, str]] = None) -> None:
        """Set a gauge metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._metrics[key] = value

    def increment_counter(self, name: str, value: float = 1.0, labels: Optional[dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        with self._lock:
            key = self._make_key(name, labels)
            self._metrics[key] = self._metrics.get(key, 0) + value

    def record_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Record a histogram value."""
        hist_key = self._make_key(f"{name}_sum", labels)
        count_key = self._make_key(f"{name}_count", labels)

        with self._lock:
            self._metrics[hist_key] = self._metrics.get(hist_key, 0) + value
            self._metrics[count_key] = self._metrics.get(count_key, 0) + 1

    def _make_key(self, name: str, labels: Optional[dict[str, str]] = None) -> str:
        """Create metric key."""
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def get_metrics(self) -> str:
        """Get metrics in Prometheus format."""
        with self._lock:
            lines = []
            for key, value in sorted(self._metrics.items()):
                lines.append(f"{key} {value}")
            return "\n".join(lines)
