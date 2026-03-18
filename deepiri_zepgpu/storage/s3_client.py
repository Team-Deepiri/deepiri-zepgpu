"""S3/MinIO storage client for large results."""

from __future__ import annotations

import io
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from deepiri_zepgpu.config import settings


class StorageClient:
    """S3/MinIO storage client for large task results."""

    def __init__(self):
        self._client = None
        self._resource = None

    def connect(self) -> None:
        """Initialize S3 client."""
        config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        )
        
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3.endpoint_url,
            aws_access_key_id=settings.s3.access_key,
            aws_secret_access_key=settings.s3.secret_key,
            region_name=settings.s3.region,
            config=config,
        )
        
        self._resource = boto3.resource(
            "s3",
            endpoint_url=settings.s3.endpoint_url,
            aws_access_key_id=settings.s3.access_key,
            aws_secret_access_key=settings.s3.secret_key,
            region_name=settings.s3.region,
        )
        
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        """Create bucket if it doesn't exist."""
        try:
            self._client.head_bucket(Bucket=settings.s3.bucket_name)
        except ClientError:
            try:
                self._client.create_bucket(Bucket=settings.s3.bucket_name)
            except ClientError:
                pass

    def upload_result(
        self,
        task_id: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload task result to S3."""
        key = f"results/{task_id}"
        
        self._client.put_object(
            Bucket=settings.s3.bucket_name,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        
        return key

    def download_result(self, task_id: str) -> Optional[bytes]:
        """Download task result from S3."""
        key = f"results/{task_id}"
        
        try:
            response = self._client.get_object(
                Bucket=settings.s3.bucket_name,
                Key=key,
            )
            return response["Body"].read()
        except ClientError:
            return None

    def delete_result(self, task_id: str) -> bool:
        """Delete task result from S3."""
        key = f"results/{task_id}"
        
        try:
            self._client.delete_object(
                Bucket=settings.s3.bucket_name,
                Key=key,
            )
            return True
        except ClientError:
            return False

    def generate_presigned_url(
        self,
        task_id: str,
        expiry_seconds: Optional[int] = None,
    ) -> Optional[str]:
        """Generate presigned URL for result download."""
        key = f"results/{task_id}"
        expiry = expiry_seconds or settings.s3.presigned_expiry_seconds
        
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": settings.s3.bucket_name,
                    "Key": key,
                },
                ExpiresIn=expiry,
            )
            return url
        except ClientError:
            return None

    def upload_presigned_put_url(
        self,
        task_id: str,
        expiry_seconds: Optional[int] = None,
    ) -> Optional[str]:
        """Generate presigned URL for result upload."""
        key = f"results/{task_id}"
        expiry = expiry_seconds or settings.s3.presigned_expiry_seconds
        
        try:
            url = self._client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.s3.bucket_name,
                    "Key": key,
                },
                ExpiresIn=expiry,
            )
            return url
        except ClientError:
            return None

    def get_result_size(self, task_id: str) -> Optional[int]:
        """Get size of stored result."""
        key = f"results/{task_id}"
        
        try:
            response = self._client.head_object(
                Bucket=settings.s3.bucket_name,
                Key=key,
            )
            return response["ContentLength"]
        except ClientError:
            return None

    def list_results(
        self,
        prefix: str = "results/",
        max_keys: int = 100,
    ) -> list[dict[str, Any]]:
        """List stored results."""
        try:
            response = self._client.list_objects_v2(
                Bucket=settings.s3.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys,
            )
            
            return [
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                }
                for obj in response.get("Contents", [])
            ]
        except ClientError:
            return []

    def result_exists(self, task_id: str) -> bool:
        """Check if result exists."""
        key = f"results/{task_id}"
        
        try:
            self._client.head_object(
                Bucket=settings.s3.bucket_name,
                Key=key,
            )
            return True
        except ClientError:
            return False

    def cleanup_old_results(self, days: int = 7) -> int:
        """Delete results older than specified days."""
        from datetime import datetime, timedelta
        
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = 0
        
        for result in self.list_results():
            if result["last_modified"].replace("Z", "+00:00") < cutoff.isoformat():
                key = result["key"]
                try:
                    self._client.delete_object(
                        Bucket=settings.s3.bucket_name,
                        Key=key,
                    )
                    deleted += 1
                except ClientError:
                    pass
        
        return deleted


storage = StorageClient()
