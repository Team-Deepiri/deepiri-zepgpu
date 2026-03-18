"""Structured logging with context support."""

from __future__ import annotations

import json
import logging
import sys
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Optional

try:
    import structlog
    STRUCTLOG_AVAILABLE = True
except ImportError:
    STRUCTLOG_AVAILABLE = False


class LogLevel(Enum):
    """Log levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class StructuredLogger:
    """Structured logging with JSON output support."""

    def __init__(
        self,
        name: str = "deepiri",
        level: LogLevel = LogLevel.INFO,
        json_output: bool = False,
        log_file: Optional[str] = None,
    ):
        self._name = name
        self._level = level
        self._json_output = json_output
        self._log_file = log_file
        self._context: dict[str, Any] = {}
        self._lock = threading.Lock()

        if STRUCTLOG_AVAILABLE and json_output:
            structlog.configure(
                processors=[
                    structlog.stdlib.filter_by_level,
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer(),
                ],
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                cache_logger_on_first_use=True,
            )

        self._logger = logging.getLogger(name)
        self._setup_handler()

    def _setup_handler(self) -> None:
        """Setup logging handlers."""
        self._logger.setLevel(getattr(logging, self._level.value.upper()))

        if not self._logger.handlers:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, self._level.value.upper()))
            self._logger.addHandler(console_handler)

        if self._log_file:
            file_handler = logging.FileHandler(self._log_file)
            file_handler.setLevel(getattr(logging, self._level.value.upper()))
            self._logger.addHandler(file_handler)

    def set_context(self, **kwargs: Any) -> None:
        """Set logging context."""
        with self._lock:
            self._context.update(kwargs)

    def clear_context(self) -> None:
        """Clear logging context."""
        with self._lock:
            self._context.clear()

    def _format_message(self, level: str, message: str, **kwargs: Any) -> str:
        """Format log message."""
        with self._lock:
            ctx = dict(self._context)
        ctx.update(kwargs)

        if self._json_output:
            return json.dumps({
                "timestamp": datetime.utcnow().isoformat(),
                "level": level,
                "logger": self._name,
                "message": message,
                **ctx,
            })
        else:
            ctx_str = " ".join(f"{k}={v}" for k, v in ctx.items())
            return f"[{self._name}] {level.upper()}: {message} {ctx_str}".strip()

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self._logger.debug(self._format_message("debug", message, **kwargs))

    def info(self, message: str, **kwargs: Any) -> None:
        """Log info message."""
        self._logger.info(self._format_message("info", message, **kwargs))

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self._logger.warning(self._format_message("warning", message, **kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self._logger.error(self._format_message("error", message, **kwargs))

    def critical(self, message: str, **kwargs: Any) -> None:
        """Log critical message."""
        self._logger.critical(self._format_message("critical", message, **kwargs))

    def log_task_event(
        self,
        task_id: str,
        event: str,
        **kwargs: Any,
    ) -> None:
        """Log task-specific event."""
        self.info(
            f"Task event: {event}",
            task_id=task_id,
            event=event,
            **kwargs,
        )

    def log_gpu_event(
        self,
        device_id: int,
        event: str,
        **kwargs: Any,
    ) -> None:
        """Log GPU-specific event."""
        self.info(
            f"GPU event: {event}",
            device_id=device_id,
            event=event,
            **kwargs,
        )


_default_logger: Optional[StructuredLogger] = None


def get_logger(name: str = "deepiri") -> StructuredLogger:
    """Get or create the default logger."""
    global _default_logger
    if _default_logger is None:
        _default_logger = StructuredLogger(name=name)
    return _default_logger


def configure_logger(
    level: LogLevel = LogLevel.INFO,
    json_output: bool = False,
    log_file: Optional[str] = None,
) -> StructuredLogger:
    """Configure the default logger."""
    global _default_logger
    _default_logger = StructuredLogger(
        name="deepiri",
        level=level,
        json_output=json_output,
        log_file=log_file,
    )
    return _default_logger
