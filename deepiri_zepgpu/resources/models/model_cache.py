"""Model caching and management for ML models."""

from __future__ import annotations

import hashlib
import pickle
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar, Optional

T = TypeVar("T")


@dataclass
class ModelMetadata:
    """Metadata for a cached model."""
    name: str
    version: str
    checksum: str
    size_bytes: int
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: datetime = field(default_factory=datetime.utcnow)
    load_count: int = 0


class ModelCache(Generic[T]):
    """Thread-safe cache for ML models."""

    def __init__(self, max_size_mb: int = 10240):
        self._cache: dict[str, T] = {}
        self._metadata: dict[str, ModelMetadata] = {}
        self._max_size_mb = max_size_mb
        self._current_size_mb = 0
        self._lock = threading.RLock()
        self._access_order: list[str] = []

    def put(
        self,
        name: str,
        model: T,
        version: str = "1.0.0",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Add a model to the cache."""
        with self._lock:
            checksum = self._compute_checksum(model)
            size_mb = self._estimate_size_mb(model)

            if self._current_size_mb + size_mb > self._max_size_mb:
                self._evict(size_mb)

            self._cache[name] = model
            self._metadata[name] = ModelMetadata(
                name=name,
                version=version,
                checksum=checksum,
                size_bytes=int(size_mb * 1024 * 1024),
            )
            self._current_size_mb += size_mb
            self._access_order.append(name)

    def get(self, name: str) -> Optional[T]:
        """Get a model from the cache."""
        with self._lock:
            if name not in self._cache:
                return None

            self._metadata[name].last_accessed = datetime.utcnow()
            self._metadata[name].load_count += 1

            self._access_order.remove(name)
            self._access_order.append(name)

            return self._cache[name]

    def contains(self, name: str) -> bool:
        """Check if model is in cache."""
        return name in self._cache

    def remove(self, name: str) -> bool:
        """Remove a model from cache."""
        with self._lock:
            if name not in self._cache:
                return False

            size_mb = self._estimate_size_mb(self._cache[name])
            del self._cache[name]
            del self._metadata[name]
            self._access_order.remove(name)
            self._current_size_mb -= size_mb
            return True

    def clear(self) -> None:
        """Clear all cached models."""
        with self._lock:
            self._cache.clear()
            self._metadata.clear()
            self._access_order.clear()
            self._current_size_mb = 0

    def _evict(self, required_size_mb: float) -> None:
        """Evict least recently used models."""
        while self._current_size_mb + required_size_mb > self._max_size_mb:
            if not self._access_order:
                break
            lru_name = self._access_order[0]
            self.remove(lru_name)

    def _compute_checksum(self, model: T) -> str:
        """Compute checksum for model."""
        serialized = pickle.dumps(model)
        return hashlib.sha256(serialized).hexdigest()[:16]

    def _estimate_size_mb(self, model: T) -> float:
        """Estimate model size in MB."""
        return len(pickle.dumps(model)) / (1024 * 1024)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                "models_cached": len(self._cache),
                "size_mb": self._current_size_mb,
                "max_size_mb": self._max_size_mb,
                "utilization_percent": (self._current_size_mb / self._max_size_mb * 100) if self._max_size_mb > 0 else 0,
                "models": [
                    {
                        "name": m.name,
                        "version": m.version,
                        "size_mb": m.size_bytes / (1024 * 1024),
                        "load_count": m.load_count,
                        "last_accessed": m.last_accessed.isoformat(),
                    }
                    for m in self._metadata.values()
                ],
            }


class ModelRegistry:
    """Registry for managing model loaders and versions."""

    def __init__(self, cache: Optional[ModelCache] = None):
        self._cache = cache or ModelCache()
        self._loaders: dict[str, Callable[[], T]] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        loader: Callable[[], T],
    ) -> None:
        """Register a model loader."""
        with self._lock:
            self._loaders[name] = loader

    def load(
        self,
        name: str,
        force_reload: bool = False,
        **kwargs: Any,
    ) -> Optional[T]:
        """Load a model, using cache if available."""
        if not force_reload:
            cached = self._cache.get(name)
            if cached is not None:
                return cached

        loader = self._loaders.get(name)
        if loader is None:
            raise KeyError(f"No loader registered for model: {name}")

        model = loader(**kwargs)

        self._cache.put(name, model)

        return model

    def preload(self, names: list[str]) -> dict[str, Optional[T]]:
        """Preload multiple models."""
        results = {}
        for name in names:
            try:
                results[name] = self.load(name)
            except Exception as e:
                results[name] = None
                print(f"Failed to preload {name}: {e}")
        return results

    def get_cache(self) -> ModelCache:
        """Get the model cache."""
        return self._cache
