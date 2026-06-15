"""Storage layer initialization."""

from deepiri_zepgpu.storage.result_store import ResultStore, result_store
from deepiri_zepgpu.storage.s3_client import StorageClient, storage

__all__ = ["storage", "StorageClient", "result_store", "ResultStore"]
