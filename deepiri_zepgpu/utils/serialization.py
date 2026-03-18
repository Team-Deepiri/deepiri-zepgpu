"""Serialization utilities for task and result transport."""

from __future__ import annotations

import base64
import json
import pickle
import zlib
from typing import Any, Optional

import numpy as np


class SerializationError(Exception):
    """Serialization error."""
    pass


class Serializer:
    """Handles serialization of tasks and results."""

    def __init__(self, compression_level: int = 6):
        self._compression_level = compression_level

    def serialize(self, obj: Any, format: str = "pickle") -> bytes:
        """Serialize an object."""
        if format == "pickle":
            return self._serialize_pickle(obj)
        elif format == "json":
            return self._serialize_json(obj)
        elif format == "numpy":
            return self._serialize_numpy(obj)
        else:
            raise ValueError(f"Unknown format: {format}")

    def deserialize(self, data: bytes, format: str = "pickle") -> Any:
        """Deserialize an object."""
        if format == "pickle":
            return self._deserialize_pickle(data)
        elif format == "json":
            return self._deserialize_json(data)
        elif format == "numpy":
            return self._deserialize_numpy(data)
        else:
            raise ValueError(f"Unknown format: {format}")

    def _serialize_pickle(self, obj: Any) -> bytes:
        """Serialize using pickle."""
        try:
            return pickle.dumps(obj)
        except Exception as e:
            raise SerializationError(f"Pickle serialization failed: {e}")

    def _deserialize_pickle(self, data: bytes) -> Any:
        """Deserialize using pickle."""
        try:
            return pickle.loads(data)
        except Exception as e:
            raise SerializationError(f"Pickle deserialization failed: {e}")

    def _serialize_json(self, obj: Any) -> bytes:
        """Serialize using JSON."""
        try:
            return json.dumps(obj, default=self._json_default).encode()
        except Exception as e:
            raise SerializationError(f"JSON serialization failed: {e}")

    def _deserialize_json(self, data: bytes) -> Any:
        """Deserialize using JSON."""
        try:
            return json.loads(data.decode())
        except Exception as e:
            raise SerializationError(f"JSON deserialization failed: {e}")

    def _json_default(self, obj: Any) -> Any:
        """Default JSON serializer for non-serializable objects."""
        if isinstance(obj, np.ndarray):
            return {
                "__type__": "numpy_array",
                "data": base64.b64encode(obj.tobytes()).decode(),
                "dtype": str(obj.dtype),
                "shape": obj.shape,
            }
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif hasattr(obj, "__dict__"):
            return {"__type__": type(obj).__name__, "data": obj.__dict__}
        return str(obj)

    def _serialize_numpy(self, obj: Any) -> bytes:
        """Serialize numpy arrays efficiently."""
        if isinstance(obj, np.ndarray):
            return obj.tobytes()
        return self._serialize_pickle(obj)

    def _deserialize_numpy(self, data: bytes) -> Any:
        """Deserialize numpy array from bytes."""
        return np.frombuffer(data, dtype=np.float32)

    def compress(self, data: bytes) -> bytes:
        """Compress data."""
        return zlib.compress(data, level=self._compression_level)

    def decompress(self, data: bytes) -> bytes:
        """Decompress data."""
        return zlib.decompress(data)

    def serialize_b64(self, obj: Any, format: str = "pickle") -> str:
        """Serialize and return base64 encoded string."""
        return base64.b64encode(self.serialize(obj, format)).decode()

    def deserialize_b64(self, data: str, format: str = "pickle") -> Any:
        """Deserialize from base64 encoded string."""
        return self.deserialize(base64.b64decode(data), format)


def to_json_serializable(obj: Any) -> Any:
    """Convert object to JSON-serializable form."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    elif isinstance(obj, dict):
        return {k: to_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [to_json_serializable(item) for item in obj]
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif hasattr(obj, "tolist"):
        return obj.tolist()
    elif hasattr(obj, "__dict__"):
        return {k: to_json_serializable(v) for k, v in obj.__dict__.items()}
    return str(obj)


def safe_serialize(obj: Any) -> bytes:
    """Safely serialize any object to JSON bytes."""
    return json.dumps(to_json_serializable(obj)).encode()


def safe_deserialize(data: bytes) -> Any:
    """Safely deserialize JSON bytes."""
    return json.loads(data.decode())
