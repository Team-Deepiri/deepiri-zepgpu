"""Time utilities for simulation and task scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


class SimulationClock:
    """Virtual clock for time-controllable simulations."""

    def __init__(self, start_time: Optional[datetime] = None):
        self._current_time = start_time or datetime.utcnow()
        self._offset = timedelta(0)
        self._speed = 1.0
        self._paused = False
        self._start_real = datetime.utcnow()

    def now(self) -> datetime:
        """Get current simulation time."""
        if self._paused:
            return self._current_time
        elapsed = datetime.utcnow() - self._start_real
        return self._current_time + (elapsed * self._speed)

    def set_time(self, time: datetime) -> None:
        """Set simulation time."""
        self._current_time = time
        self._start_real = datetime.utcnow()

    def advance(self, delta: timedelta) -> None:
        """Advance simulation time by delta."""
        self._current_time += delta

    def set_speed(self, speed: float) -> None:
        """Set simulation speed multiplier."""
        self._speed = max(0.0, speed)
        self._start_real = datetime.utcnow()

    def pause(self) -> None:
        """Pause simulation time."""
        self._paused = True

    def resume(self) -> None:
        """Resume simulation time."""
        self._paused = False
        self._start_real = datetime.utcnow()

    def reset(self, start_time: Optional[datetime] = None) -> None:
        """Reset clock to start time."""
        self._current_time = start_time or datetime.utcnow()
        self._start_real = datetime.utcnow()
        self._paused = False


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string."""
    if seconds < 1:
        return f"{seconds*1000:.1f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def parse_duration(duration_str: str) -> float:
    """Parse duration string to seconds."""
    units = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800,
    }

    duration_str = duration_str.strip().lower()
    if not duration_str:
        return 0

    for unit, multiplier in units.items():
        if duration_str.endswith(unit):
            value = duration_str[:-1].strip()
            try:
                return float(value) * multiplier
            except ValueError:
                return 0

    try:
        return float(duration_str)
    except ValueError:
        return 0


def timestamp_to_iso(timestamp: float) -> str:
    """Convert Unix timestamp to ISO format string."""
    return datetime.fromtimestamp(timestamp).isoformat()


def iso_to_timestamp(iso_str: str) -> float:
    """Convert ISO format string to Unix timestamp."""
    return datetime.fromisoformat(iso_str).timestamp()


def get_time_buckets(
    start: datetime,
    end: datetime,
    bucket_size: timedelta,
) -> list[tuple[datetime, datetime]]:
    """Generate time buckets between start and end."""
    buckets = []
    current = start
    while current < end:
        bucket_end = min(current + bucket_size, end)
        buckets.append((current, bucket_end))
        current = bucket_end
    return buckets


class RateLimiter:
    """Rate limiter for task submissions."""

    def __init__(self, max_per_second: float, burst: int = 1):
        self._max_per_second = max_per_second
        self._burst = burst
        self._tokens = float(burst)
        self._last_update = datetime.utcnow()

    def allow(self) -> bool:
        """Check if request is allowed under rate limit."""
        now = datetime.utcnow()
        elapsed = (now - self._last_update).total_seconds()
        self._tokens = min(
            self._burst,
            self._tokens + (elapsed * self._max_per_second)
        )
        self._last_update = now

        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False

    def wait_time(self) -> float:
        """Get wait time in seconds before next request allowed."""
        if self._tokens >= 1:
            return 0
        return (1 - self._tokens) / self._max_per_second
