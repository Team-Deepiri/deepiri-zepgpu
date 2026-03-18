"""Storage layer initialization."""

from deepiri_zepgpu.storage.s3_client import storage, StorageClient
from deepiri_zepgpu.storage.result_store import result_store, ResultStore

__all__ = ["storage", "StorageClient", "result_store", "ResultStore"]
