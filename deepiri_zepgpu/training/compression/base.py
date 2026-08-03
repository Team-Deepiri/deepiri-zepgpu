"""Compressor protocol and factory."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Protocol

from deepiri_zepgpu.training.config import CompressionConfig, CompressorBackend

CODEC_NONE = "none"
CODEC_ZEP = "zep-v1"
CODEC_DEMO = "demo-v1"

_HEADER = struct.Struct("!I")  # tensor count
_TENSOR_META = struct.Struct("!HHI")  # name_len, dtype_len, ndim then shape dims as !q*


@dataclass
class CompressorState:
    """Per-tensor error-feedback / momentum residual state."""

    residuals: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompressedUpdate:
    codec: str
    payload: bytes
    shapes: tuple[tuple[int, ...], ...]
    dtypes: tuple[str, ...]
    names: tuple[str, ...]
    uncompressed_bytes: int
    compressed_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def compression_ratio(self) -> float:
        if self.uncompressed_bytes <= 0:
            return 0.0
        return self.compressed_bytes / self.uncompressed_bytes


class UpdateCompressor(Protocol):
    name: str
    codec_id: str

    def compress(self, tensors: dict[str, Any], state: CompressorState) -> CompressedUpdate: ...

    def decompress(self, update: CompressedUpdate) -> dict[str, Any]: ...

    def knobs(self) -> dict[str, Any]: ...


def get_compressor(config: CompressionConfig) -> UpdateCompressor:
    if config.backend == CompressorBackend.NONE:
        from deepiri_zepgpu.training.compression.none import NoneCompressor

        return NoneCompressor()
    if config.backend == CompressorBackend.ZEP:
        from deepiri_zepgpu.training.compression.zep import ZepCompressor

        return ZepCompressor(config)
    if config.backend == CompressorBackend.DEMO:
        from deepiri_zepgpu.training.compression.demo_backend import DemoCompressor

        return DemoCompressor(config)
    raise ValueError(f"unknown compressor backend: {config.backend}")


def pack_named_arrays(
    names: list[str],
    arrays: list[Any],
    *,
    codec: str,
    metadata: dict[str, Any] | None = None,
) -> CompressedUpdate:
    """Pack dense float32 arrays as a naive or intermediate payload."""
    import numpy as np

    parts: list[bytes] = [_HEADER.pack(len(arrays))]
    shapes: list[tuple[int, ...]] = []
    dtypes: list[str] = []
    uncompressed = 0
    for name, array in zip(names, arrays, strict=True):
        np_array = np.asarray(array, dtype=np.float32)
        shape = tuple(int(dim) for dim in np_array.shape)
        shapes.append(shape)
        dtypes.append("float32")
        name_b = name.encode("utf-8")
        dtype_b = b"float32"
        parts.append(_TENSOR_META.pack(len(name_b), len(dtype_b), len(shape)))
        parts.append(name_b)
        parts.append(dtype_b)
        parts.append(struct.pack(f"!{len(shape)}q", *shape))
        raw = np_array.tobytes(order="C")
        uncompressed += len(raw)
        parts.append(struct.pack("!I", len(raw)))
        parts.append(raw)
    payload = b"".join(parts)
    return CompressedUpdate(
        codec=codec,
        payload=payload,
        shapes=tuple(shapes),
        dtypes=tuple(dtypes),
        names=tuple(names),
        uncompressed_bytes=uncompressed,
        compressed_bytes=len(payload),
        metadata=dict(metadata or {}),
    )


def unpack_named_arrays(update: CompressedUpdate) -> dict[str, Any]:
    import numpy as np

    data = update.payload
    (count,) = _HEADER.unpack_from(data, 0)
    cursor = _HEADER.size
    result: dict[str, Any] = {}
    for _ in range(count):
        name_len, dtype_len, ndim = _TENSOR_META.unpack_from(data, cursor)
        cursor += _TENSOR_META.size
        name = data[cursor : cursor + name_len].decode("utf-8")
        cursor += name_len
        dtype = data[cursor : cursor + dtype_len].decode("utf-8")
        cursor += dtype_len
        shape = struct.unpack_from(f"!{ndim}q", data, cursor)
        cursor += 8 * ndim
        (nbytes,) = struct.unpack_from("!I", data, cursor)
        cursor += 4
        raw = data[cursor : cursor + nbytes]
        cursor += nbytes
        if dtype != "float32":
            raise ValueError(f"unsupported packed dtype: {dtype}")
        result[name] = np.frombuffer(raw, dtype=np.float32).reshape(shape).copy()
    return result
