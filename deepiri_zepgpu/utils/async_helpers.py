"""Async utilities and helpers."""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


async def run_in_executor(
    func: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Run a blocking function in an executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        functools.partial(func, *args, **kwargs),
    )


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    **kwargs: Any,
) -> Any:
    """Retry an async function with exponential backoff."""
    last_exception = None
    current_delay = delay

    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            if attempt < max_attempts - 1:
                await asyncio.sleep(current_delay)
                current_delay *= backoff

    raise last_exception


async def wait_for(
    coro: Any,
    timeout: Optional[float] = None,
    default: Any = None,
) -> Any:
    """Wait for coroutine with timeout, returning default on timeout."""
    try:
        if timeout:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro
    except asyncio.TimeoutError:
        return default


async def gather_with_concurrency(
    max_concurrent: int,
    *coros: Any,
) -> list[Any]:
    """Gather coroutines with limited concurrency."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_coro(coro: Any) -> Any:
        async with semaphore:
            return await coro

    return await asyncio.gather(*[bounded_coro(c) for c in coros])


class AsyncBatchProcessor:
    """Process items in batches asynchronously."""

    def __init__(
        self,
        batch_size: int = 10,
        max_concurrent: int = 4,
        delay_between_batches: float = 0.1,
    ):
        self._batch_size = batch_size
        self._max_concurrent = max_concurrent
        self._delay = delay_between_batches

    async def process(
        self,
        items: list[Any],
        processor: Callable[[Any], Any],
    ) -> list[Any]:
        """Process items in batches."""
        results = []

        for i in range(0, len(items), self._batch_size):
            batch = items[i:i + self._batch_size]

            batch_results = await gather_with_concurrency(
                self._max_concurrent,
                *[processor(item) for item in batch],
            )
            results.extend(batch_results)

            if i + self._batch_size < len(items):
                await asyncio.sleep(self._delay)

        return results


class AsyncEventBus:
    """Simple async event bus."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}

    def subscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        """Subscribe to an event."""
        if event not in self._subscribers:
            self._subscribers[event] = []
        self._subscribers[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable[[Any], None]) -> None:
        """Unsubscribe from an event."""
        if event in self._subscribers:
            self._subscribers[event].remove(handler)

    async def publish(self, event: str, data: Any = None) -> None:
        """Publish an event."""
        handlers = self._subscribers.get(event, [])
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                await handler(data)
            else:
                handler(data)


class AsyncCache:
    """Simple async cache with TTL."""

    def __init__(self, ttl_seconds: float = 60.0):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl_seconds

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if key in self._cache:
            value, expiry = self._cache[key]
            import time
            if time.time() < expiry:
                return value
            del self._cache[key]
        return None

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set value in cache."""
        import time
        expiry = time.time() + (ttl or self._ttl)
        self._cache[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        """Delete value from cache."""
        self._cache.pop(key, None)

    async def clear(self) -> None:
        """Clear all cache."""
        self._cache.clear()

    async def cleanup(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        import time
        now = time.time()
        expired = [k for k, (_, expiry) in self._cache.items() if now >= expiry]
        for key in expired:
            del self._cache[key]
        return len(expired)
