"""Precompiled CUDA/CuPy kernel cache."""

from __future__ import annotations

import hashlib
import importlib
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

try:
    import cupy as cp
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False


@dataclass
class KernelMetadata:
    """Metadata for a compiled kernel."""
    name: str
    source_hash: str
    compiled_at: datetime = field(default_factory=datetime.utcnow)
    source_file: Optional[str] = None
    usage_count: int = 0


class KernelCache:
    """Cache for compiled GPU kernels."""

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        max_kernels: int = 100,
    ):
        self._cache_dir = cache_dir or os.path.expanduser("~/.deepiri/kernel_cache")
        self._max_kernels = max_kernels
        self._kernels: dict[str, Any] = {}
        self._metadata: dict[str, KernelMetadata] = {}
        self._lock = threading.RLock()
        self._usage_order: list[str] = []

        Path(self._cache_dir).mkdir(parents=True, exist_ok=True)

    def compile_and_cache(
        self,
        name: str,
        source: str,
        options: Optional[list[str]] = None,
    ) -> Any:
        """Compile a CUDA kernel and cache it."""
        if not CUPY_AVAILABLE:
            raise RuntimeError("CuPy is not available for kernel compilation")

        with self._lock:
            source_hash = hashlib.sha256(source.encode()).hexdigest()

            if name in self._kernels:
                kernel = self._kernels[name]
                self._metadata[name].usage_count += 1
                self._update_usage_order(name)
                return kernel

            if len(self._kernels) >= self._max_kernels:
                self._evict_lru()

            kernel = cp.RawKernel(source, name)

            kernel_path = os.path.join(self._cache_dir, f"{name}_{source_hash}.cubin")
            with open(kernel_path, "w") as f:
                f.write(source)

            self._kernels[name] = kernel
            self._metadata[name] = KernelMetadata(
                name=name,
                source_hash=source_hash,
                source_file=kernel_path,
            )
            self._usage_order.append(name)

            return kernel

    def get(self, name: str) -> Optional[Any]:
        """Get a cached kernel."""
        with self._lock:
            if name not in self._kernels:
                return None

            self._metadata[name].usage_count += 1
            self._update_usage_order(name)
            return self._kernels[name]

    def contains(self, name: str) -> bool:
        """Check if kernel is cached."""
        return name in self._kernels

    def _update_usage_order(self, name: str) -> None:
        """Update LRU order."""
        if name in self._usage_order:
            self._usage_order.remove(name)
        self._usage_order.append(name)

    def _evict_lru(self) -> None:
        """Evict least recently used kernel."""
        if self._usage_order:
            lru_name = self._usage_order[0]
            self.remove(lru_name)

    def remove(self, name: str) -> bool:
        """Remove a kernel from cache."""
        with self._lock:
            if name not in self._kernels:
                return False

            metadata = self._metadata[name]
            if metadata.source_file and os.path.exists(metadata.source_file):
                os.remove(metadata.source_file)

            del self._kernels[name]
            del self._metadata[name]
            self._usage_order.remove(name)
            return True

    def clear(self) -> None:
        """Clear all cached kernels."""
        with self._lock:
            for name in list(self._kernels.keys()):
                self.remove(name)

    def get_stats(self) -> dict[str, Any]:
        """Get kernel cache statistics."""
        with self._lock:
            return {
                "kernels_cached": len(self._kernels),
                "max_kernels": self._max_kernels,
                "kernels": [
                    {
                        "name": m.name,
                        "usage_count": m.usage_count,
                        "compiled_at": m.compiled_at.isoformat(),
                        "source_hash": m.source_hash[:8],
                    }
                    for m in self._metadata.values()
                ],
            }


@dataclass
class KernelTemplate:
    """Template for generating CUDA kernels."""
    name: str
    source_template: str
    param_types: dict[str, str]

    def render(self, **kwargs: Any) -> str:
        """Render kernel source with parameters."""
        return self.source_template.format(**kwargs)


class KernelBuilder:
    """Builder for CUDA kernels with common patterns."""

    @staticmethod
    def matrix_mult_template(block_size: int = 16) -> KernelTemplate:
        """Generate matrix multiplication kernel template."""
        source = f"""
__global__ void matrixMul(const float* A, const float* B, float* C,
                           int M, int N, int K) {{
    int row = blockIdx.y * blockDim.y + threadIdx.y;
    int col = blockIdx.x * blockDim.x + threadIdx.x;

    if (row < M && col < N) {{
        float sum = 0.0f;
        for (int k = 0; k < K; ++k) {{
            sum += A[row * K + k] * B[k * N + col];
        }}
        C[row * N + col] = sum;
    }}
}}
"""
        return KernelTemplate(
            name="matrixMul",
            source_template=source,
            param_types={"A": "float*", "B": "float*", "C": "float*"},
        )

    @staticmethod
    def vector_add_template() -> KernelTemplate:
        """Generate vector addition kernel template."""
        source = """
__global__ void vectorAdd(const float* A, const float* B, float* C, int N) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < N) {
        C[idx] = A[idx] + B[idx];
    }
}
"""
        return KernelTemplate(
            name="vectorAdd",
            source_template=source,
            param_types={"A": "float*", "B": "float*", "C": "float*"},
        )

    @staticmethod
    def softmax_template() -> KernelTemplate:
        """Generate softmax kernel template."""
        source = """
__global__ void softmax(const float* input, float* output, int N, int C) {
    int n = blockIdx.x;
    if (n < N) {
        float max_val = -INFINITY;
        for (int c = 0; c < C; ++c) {
            max_val = fmaxf(max_val, input[n * C + c]);
        }

        float sum = 0.0f;
        for (int c = 0; c < C; ++c) {
            output[n * C + c] = __expf(input[n * C + c] - max_val);
            sum += output[n * C + c];
        }

        for (int c = 0; c < C; ++c) {
            output[n * C + c] /= sum;
        }
    }
}
"""
        return KernelTemplate(
            name="softmax",
            source_template=source,
            param_types={"input": "float*", "output": "float*"},
        )
