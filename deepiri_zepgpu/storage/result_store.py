"""Result storage manager with async support."""

from __future__ import annotations

import base64
import pickle
from typing import Any, Optional

from deepiri_zepgpu.config import settings


class ResultStore:
    """Manages task result storage (Redis cache + S3)."""

    SMALL_RESULT_THRESHOLD = 1024 * 1024
    LARGE_RESULT_THRESHOLD = 100 * 1024 * 1024

    def __init__(self):
        self._initialized = False
        self._redis_client = None
        self._s3_client = None

    async def initialize(self) -> None:
        """Initialize storage backends."""
        from deepiri_zepgpu.storage.s3_client import storage
        storage.connect()
        self._s3_client = storage
        
        from deepiri_zepgpu.queue.redis_queue import RedisQueue
        self._redis_client = RedisQueue()
        await self._redis_client.connect()
        
        self._initialized = True

    async def store_result(
        self,
        task_id: str,
        result: bytes,
        store_in_s3: bool = True,
    ) -> tuple[str, Optional[str], int]:
        """Store task result.

        Returns:
            Tuple of (storage_type, storage_ref, size_bytes)
            storage_type: 'redis', 's3', or 'inline'
            storage_ref: Key/URL for retrieval, or None
            size_bytes: Size of stored result
        """
        size_bytes = len(result)

        if size_bytes <= self.SMALL_RESULT_THRESHOLD:
            await self._redis_client.set_task_result(task_id, {
                "result": result.hex(),
                "size": size_bytes,
            })
            return "redis", task_id, size_bytes

        elif store_in_s3 and size_bytes <= self.LARGE_RESULT_THRESHOLD:
            storage_key = self._s3_client.upload_result(task_id, result)
            return "s3", storage_key, size_bytes

        else:
            return "inline", base64.b64encode(result).decode(), size_bytes

    async def retrieve_result(
        self,
        task_id: str,
        storage_type: str,
        storage_ref: Optional[str] = None,
    ) -> Optional[bytes]:
        """Retrieve task result."""
        if storage_type == "redis":
            result_data = await self._redis_client.get_task_result(task_id)
            if result_data:
                serialized_hex = result_data.get("result", "")
                return bytes.fromhex(serialized_hex)
            return None

        elif storage_type == "s3":
            data = self._s3_client.download_result(task_id)
            return data

        elif storage_type == "inline":
            if storage_ref:
                return base64.b64decode(storage_ref)
            return None

        return None

    async def delete_result(
        self,
        task_id: str,
        storage_type: str,
    ) -> None:
        """Delete stored result."""
        if storage_type == "redis":
            await self._redis_client.delete_task_result(task_id)
        elif storage_type == "s3":
            self._s3_client.delete_result(task_id)

    async def get_presigned_url(self, task_id: str, expiry: Optional[int] = None) -> Optional[str]:
        """Get presigned URL for result download."""
        return self._s3_client.generate_presigned_url(task_id, expiry)

    async def result_exists(self, task_id: str) -> bool:
        """Check if result exists."""
        if self._redis_client:
            redis_result = await self._redis_client.get_task_result(task_id)
            if redis_result:
                return True
        if self._s3_client and self._s3_client.result_exists(task_id):
            return True
        return False

    async def get_result_size(self, task_id: str) -> Optional[int]:
        """Get result size."""
        if self._redis_client:
            redis_result = await self._redis_client.get_task_result(task_id)
            if redis_result:
                return redis_result.get("size")

        if self._s3_client:
            s3_size = self._s3_client.get_result_size(task_id)
            if s3_size:
                return s3_size

        return None

    async def cleanup_old_results(self, days: int = 7) -> int:
        """Clean up old results."""
        return 0


result_store = ResultStore()
