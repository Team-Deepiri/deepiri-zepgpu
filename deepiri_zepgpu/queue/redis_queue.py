"""Redis task queue integration."""

from __future__ import annotations

import json
from typing import Any, Optional

import redis.asyncio as redis

from deepiri_zepgpu.config import settings


class RedisQueue:
    """Redis-based task queue."""

    TASK_QUEUE = "deepiri:tasks:queue"
    TASK_RESULTS = "deepiri:tasks:results"
    TASK_LOCKS = "deepiri:tasks:locks"
    GPU_DEVICES = "deepiri:gpu:devices"
    SESSION_DATA = "deepiri:session"

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = redis.from_url(
            settings.redis.url,
            encoding="utf-8",
            decode_responses=True,
        )
        self._pubsub = self._redis.pubsub()

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    async def enqueue_task(self, task_id: str, task_data: dict[str, Any]) -> None:
        """Add task to queue."""
        priority = task_data.get("priority", 2)
        queue_key = f"{self.TASK_QUEUE}:{priority}"
        
        await self._redis.rpush(queue_key, json.dumps({
            "task_id": task_id,
            **task_data,
        }))

    async def dequeue_task(self, timeout: int = 0) -> Optional[dict[str, Any]]:
        """Get task from queue."""
        for priority in range(5, 0, -1):
            queue_key = f"{self.TASK_QUEUE}:{priority}"
            result = await self._redis.lpop(queue_key)
            
            if result:
                return json.loads(result)
        
        if timeout > 0:
            for priority in range(5, 0, -1):
                queue_key = f"{self.TASK_QUEUE}:{priority}"
                result = await self._redis.blpop(queue_key, timeout=timeout)
                if result:
                    return json.loads(result[1])
        
        return None

    async def set_task_result(
        self,
        task_id: str,
        result: dict[str, Any],
        ttl: int = 86400,
    ) -> None:
        """Store task result."""
        key = f"{self.TASK_RESULTS}:{task_id}"
        await self._redis.setex(key, ttl, json.dumps(result))

    async def get_task_result(self, task_id: str) -> Optional[dict[str, Any]]:
        """Get task result."""
        key = f"{self.TASK_RESULTS}:{task_id}"
        result = await self._redis.get(key)
        return json.loads(result) if result else None

    async def delete_task_result(self, task_id: str) -> None:
        """Delete task result."""
        key = f"{self.TASK_RESULTS}:{task_id}"
        await self._redis.delete(key)

    async def acquire_lock(
        self,
        lock_id: str,
        ttl: int = 60,
    ) -> bool:
        """Acquire a distributed lock."""
        key = f"{self.TASK_LOCKS}:{lock_id}"
        return await self._redis.set(key, "1", nx=True, ex=ttl)

    async def release_lock(self, lock_id: str) -> None:
        """Release a distributed lock."""
        key = f"{self.TASK_LOCKS}:{lock_id}"
        await self._redis.delete(key)

    async def set_gpu_status(self, device_id: int, status: dict[str, Any]) -> None:
        """Set GPU device status."""
        key = f"{self.GPU_DEVICES}:{device_id}"
        await self._redis.hset(key, mapping={
            "status": json.dumps(status),
        })
        await self._redis.expire(key, 300)

    async def get_gpu_status(self, device_id: int) -> Optional[dict[str, Any]]:
        """Get GPU device status."""
        key = f"{self.GPU_DEVICES}:{device_id}"
        status = await self._redis.hget(key, "status")
        return json.loads(status) if status else None

    async def get_queue_length(self) -> int:
        """Get total queue length."""
        total = 0
        for priority in range(1, 6):
            queue_key = f"{self.TASK_QUEUE}:{priority}"
            length = await self._redis.llen(queue_key)
            total += length
        return total

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Publish message to channel."""
        await self._redis.publish(channel, json.dumps(message))

    async def subscribe(self, channel: str) -> None:
        """Subscribe to channel."""
        await self._pubsub.subscribe(channel)

    async def get_message(self) -> Optional[dict[str, Any]]:
        """Get message from subscribed channels."""
        message = await self._pubsub.get_message(ignore_subscribe_messages=True)
        if message and message.get("type") == "message":
            return json.loads(message["data"])
        return None

    async def set_session(self, session_id: str, data: dict[str, Any], ttl: int = 3600) -> None:
        """Store session data."""
        key = f"{self.SESSION_DATA}:{session_id}"
        await self._redis.setex(key, ttl, json.dumps(data))

    async def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """Get session data."""
        key = f"{self.SESSION_DATA}:{session_id}"
        data = await self._redis.get(key)
        return json.loads(data) if data else None

    async def delete_session(self, session_id: str) -> None:
        """Delete session data."""
        key = f"{self.SESSION_DATA}:{session_id}"
        await self._redis.delete(key)

    async def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False


queue = RedisQueue()
