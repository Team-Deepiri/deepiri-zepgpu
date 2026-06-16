"""Redis task queue integration."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

import redis.asyncio as redis

from deepiri_zepgpu.config import settings

logger = logging.getLogger(__name__)


class RedisQueue:
    """Redis-based task queue."""

    TASK_QUEUE = "deepiri:tasks:queue"
    TASK_RESULTS = "deepiri:tasks:results"
    TASK_LOCKS = "deepiri:tasks:locks"
    GPU_DEVICES = "deepiri:gpu:devices"
    SESSION_DATA = "deepiri:session"

    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None

    async def connect(self, retries: int = 5, delay_seconds: float = 2.0) -> None:
        """Connect to Redis with retry handling for local/container startup."""
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                self._redis = redis.from_url(
                    settings.redis.url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await self._redis.ping()
                self._pubsub = self._redis.pubsub()
                logger.info("Connected to Redis on attempt %s", attempt)
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Redis connection attempt %s/%s failed: %s",
                    attempt,
                    retries,
                    exc,
                )

                if self._redis:
                    await self._redis.close()
                    self._redis = None

                if attempt < retries:
                    await asyncio.sleep(delay_seconds)

        raise RuntimeError(f"Failed to connect to Redis after {retries} attempts") from last_error

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    async def enqueue_task(self, task_id: str, task_data: dict[str, Any]) -> None:
        """Add task to queue."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        priority = task_data.get("priority", 2)
        queue_key = f"{self.TASK_QUEUE}:{priority}"

        await self._redis.rpush(  # type: ignore[misc]
            queue_key,
            json.dumps(
                {
                    "task_id": task_id,
                    **task_data,
                }
            ),
        )

    async def dequeue_task(self, timeout: int = 0) -> dict[str, Any] | None:
        """Get task from queue."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        for priority in range(5, 0, -1):
            queue_key = f"{self.TASK_QUEUE}:{priority}"
            result = await self._redis.lpop(queue_key)  # type: ignore[misc]

            if result:
                return cast(dict[str, Any], json.loads(result))

        if timeout > 0:
            for priority in range(5, 0, -1):
                queue_key = f"{self.TASK_QUEUE}:{priority}"
                result = await self._redis.blpop([queue_key], timeout=timeout)  # type: ignore[misc]
                if result:
                    return cast(dict[str, Any], json.loads(result[1]))

        return None

    async def set_task_result(
        self,
        task_id: str,
        result: dict[str, Any],
        ttl: int = 86400,
    ) -> None:
        """Store task result."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.TASK_RESULTS}:{task_id}"
        await self._redis.setex(key, ttl, json.dumps(result))

    async def get_task_result(self, task_id: str) -> dict[str, Any] | None:
        """Get task result."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.TASK_RESULTS}:{task_id}"
        result = await self._redis.get(key)
        return json.loads(result) if result else None

    async def delete_task_result(self, task_id: str) -> None:
        """Delete task result."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.TASK_RESULTS}:{task_id}"
        await self._redis.delete(key)

    async def acquire_lock(
        self,
        lock_id: str,
        ttl: int = 60,
    ) -> bool:
        """Acquire a distributed lock."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.TASK_LOCKS}:{lock_id}"
        return await self._redis.set(key, "1", nx=True, ex=ttl)  # type: ignore[no-any-return]

    async def release_lock(self, lock_id: str) -> None:
        """Release a distributed lock."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.TASK_LOCKS}:{lock_id}"
        await self._redis.delete(key)

    async def set_gpu_status(self, device_id: int, status: dict[str, Any]) -> None:
        """Set GPU device status."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.GPU_DEVICES}:{device_id}"
        await self._redis.hset(
            key,
            mapping={
                "status": json.dumps(status),
            },
        )  # type: ignore[misc]
        await self._redis.expire(key, 300)

    async def get_gpu_status(self, device_id: int) -> dict[str, Any] | None:
        """Get GPU device status."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.GPU_DEVICES}:{device_id}"
        status = await self._redis.hget(key, "status")  # type: ignore[misc]
        return cast(dict[str, Any], json.loads(status)) if status else None

    async def get_queue_length(self) -> int:
        """Get total queue length."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        total = 0
        for priority in range(1, 6):
            queue_key = f"{self.TASK_QUEUE}:{priority}"
            length = await self._redis.llen(queue_key)  # type: ignore[misc]
            total += length
        return total

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Publish message to channel."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        await self._redis.publish(channel, json.dumps(message))

    async def subscribe(self, channel: str) -> None:
        """Subscribe to channel."""
        if self._pubsub is None:
            raise RuntimeError("Redis pubsub not connected")
        await self._pubsub.subscribe(channel)

    async def get_message(self) -> dict[str, Any] | None:
        """Get message from subscribed channels."""
        if self._pubsub is None:
            raise RuntimeError("Redis pubsub not connected")
        message = await self._pubsub.get_message(ignore_subscribe_messages=True)
        if message and message.get("type") == "message":
            return cast(dict[str, Any], json.loads(message["data"]))
        return None

    async def set_session(self, session_id: str, data: dict[str, Any], ttl: int = 3600) -> None:
        """Store session data."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.SESSION_DATA}:{session_id}"
        await self._redis.setex(key, ttl, json.dumps(data))

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session data."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.SESSION_DATA}:{session_id}"
        data = await self._redis.get(key)
        return json.loads(data) if data else None

    async def delete_session(self, session_id: str) -> None:
        """Delete session data."""
        if self._redis is None:
            raise RuntimeError("Redis not connected")
        key = f"{self.SESSION_DATA}:{session_id}"
        await self._redis.delete(key)

    async def health_check(self) -> bool:
        """Check Redis connection health."""
        if not self._redis:
            return False

        try:
            await self._redis.ping()
            return True
        except Exception:
            return False


queue = RedisQueue()
