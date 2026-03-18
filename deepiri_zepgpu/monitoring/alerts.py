"""Alert system for task failures and SLA breaches."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from deepiri_zepgpu.monitoring.logger import get_logger


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertType(Enum):
    """Alert types."""
    TASK_FAILED = "task_failed"
    TASK_TIMEOUT = "task_timeout"
    GPU_ERROR = "gpu_error"
    GPU_OVERTEMP = "gpu_overtemp"
    GPU_MEMORY_LOW = "gpu_memory_low"
    QUEUE_BACKLOG = "queue_backlog"
    SLA_BREACH = "sla_breach"
    RESOURCE_QUOTA_EXCEEDED = "resource_quota_exceeded"


@dataclass
class Alert:
    """Alert representation."""
    alert_type: AlertType
    severity: AlertSeverity
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    task_id: Optional[str] = None
    device_id: Optional[int] = None
    user_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False


class AlertHandler:
    """Base class for alert handlers."""

    def handle(self, alert: Alert) -> None:
        """Handle an alert."""
        raise NotImplementedError


class LoggingAlertHandler(AlertHandler):
    """Handler that logs alerts."""

    def __init__(self):
        self._logger = get_logger()

    def handle(self, alert: Alert) -> None:
        """Log the alert."""
        level = {
            AlertSeverity.INFO: "info",
            AlertSeverity.WARNING: "warning",
            AlertSeverity.ERROR: "error",
            AlertSeverity.CRITICAL: "critical",
        }[alert.severity]

        log_method = getattr(self._logger, level)
        log_method(
            alert.message,
            alert_type=alert.alert_type.value,
            task_id=alert.task_id,
            device_id=alert.device_id,
            user_id=alert.user_id,
        )


class WebhookAlertHandler(AlertHandler):
    """Handler that sends alerts to webhooks."""

    def __init__(self, webhook_url: str):
        self._webhook_url = webhook_url

    async def handle(self, alert: Alert) -> None:
        """Send alert to webhook."""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    self._webhook_url,
                    json={
                        "alert_type": alert.alert_type.value,
                        "severity": alert.severity.value,
                        "message": alert.message,
                        "timestamp": alert.timestamp.isoformat(),
                        "task_id": alert.task_id,
                        "device_id": alert.device_id,
                        "metadata": alert.metadata,
                    },
                )
        except Exception as e:
            print(f"Failed to send webhook alert: {e}")


class AlertManager:
    """Manages alerts and notification handlers."""

    def __init__(self):
        self._handlers: list[AlertHandler] = [LoggingAlertHandler()]
        self._alert_history: list[Alert] = []
        self._callbacks: dict[AlertType, list[Callable[[Alert], None]]] = {}
        self._lock = threading.Lock()
        self._max_history = 1000

    def add_handler(self, handler: AlertHandler) -> None:
        """Add an alert handler."""
        with self._lock:
            self._handlers.append(handler)

    def register_callback(
        self,
        alert_type: AlertType,
        callback: Callable[[Alert], None],
    ) -> None:
        """Register a callback for specific alert type."""
        with self._lock:
            if alert_type not in self._callbacks:
                self._callbacks[alert_type] = []
            self._callbacks[alert_type].append(callback)

    async def raise_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        message: str,
        **kwargs: Any,
    ) -> Alert:
        """Raise a new alert."""
        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            message=message,
            **kwargs,
        )

        with self._lock:
            self._alert_history.append(alert)
            if len(self._alert_history) > self._max_history:
                self._alert_history.pop(0)

        for handler in self._handlers:
            try:
                if asyncio.iscoroutinefunction(handler.handle):
                    await handler.handle(alert)
                else:
                    handler.handle(alert)
            except Exception as e:
                print(f"Alert handler error: {e}")

        with self._lock:
            callbacks = self._callbacks.get(alert_type, [])
        for callback in callbacks:
            try:
                callback(alert)
            except Exception as e:
                print(f"Alert callback error: {e}")

        return alert

    async def alert_task_failed(
        self,
        task_id: str,
        error: str,
        user_id: Optional[str] = None,
    ) -> Alert:
        """Raise task failed alert."""
        return await self.raise_alert(
            alert_type=AlertType.TASK_FAILED,
            severity=AlertSeverity.ERROR,
            message=f"Task {task_id} failed: {error}",
            task_id=task_id,
            user_id=user_id,
            metadata={"error": error},
        )

    async def alert_task_timeout(
        self,
        task_id: str,
        timeout_seconds: int,
        user_id: Optional[str] = None,
    ) -> Alert:
        """Raise task timeout alert."""
        return await self.raise_alert(
            alert_type=AlertType.TASK_TIMEOUT,
            severity=AlertSeverity.WARNING,
            message=f"Task {task_id} timed out after {timeout_seconds}s",
            task_id=task_id,
            user_id=user_id,
            metadata={"timeout_seconds": timeout_seconds},
        )

    async def alert_gpu_error(
        self,
        device_id: int,
        error: str,
    ) -> Alert:
        """Raise GPU error alert."""
        return await self.raise_alert(
            alert_type=AlertType.GPU_ERROR,
            severity=AlertSeverity.CRITICAL,
            message=f"GPU {device_id} error: {error}",
            device_id=device_id,
            metadata={"error": error},
        )

    async def alert_gpu_overtemp(
        self,
        device_id: int,
        temperature: float,
    ) -> Alert:
        """Raise GPU over-temperature alert."""
        return await self.raise_alert(
            alert_type=AlertType.GPU_OVERTEMP,
            severity=AlertSeverity.WARNING,
            message=f"GPU {device_id} over temperature: {temperature}°C",
            device_id=device_id,
            metadata={"temperature": temperature},
        )

    async def alert_queue_backlog(
        self,
        queue_length: int,
        threshold: int,
    ) -> Alert:
        """Raise queue backlog alert."""
        return await self.raise_alert(
            alert_type=AlertType.QUEUE_BACKLOG,
            severity=AlertSeverity.WARNING,
            message=f"Task queue backlog: {queue_length} tasks (threshold: {threshold})",
            metadata={"queue_length": queue_length, "threshold": threshold},
        )

    def get_alerts(
        self,
        alert_type: Optional[AlertType] = None,
        severity: Optional[AlertSeverity] = None,
        limit: int = 100,
    ) -> list[Alert]:
        """Get alert history."""
        with self._lock:
            alerts = list(self._alert_history)

        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        return sorted(alerts, key=lambda a: a.timestamp, reverse=True)[:limit]

    def acknowledge_alert(self, timestamp: datetime) -> bool:
        """Acknowledge an alert."""
        with self._lock:
            for alert in self._alert_history:
                if alert.timestamp == timestamp:
                    alert.acknowledged = True
                    return True
        return False
