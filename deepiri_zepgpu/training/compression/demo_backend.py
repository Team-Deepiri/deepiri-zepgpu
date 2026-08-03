"""DeMo-adapted compressor backend (codec demo-v1)."""

from __future__ import annotations

import struct
from typing import Any

import numpy as np

from deepiri_zepgpu.training.compression.base import (
    CODEC_DEMO,
    CompressedUpdate,
    CompressorState,
)
from deepiri_zepgpu.training.compression.vendor.demo.dct import (
    as_numpy,
    decode_topk,
    encode_topk,
)
from deepiri_zepgpu.training.config import CompressionConfig

_META = struct.Struct("!I")
_ONE = struct.Struct("!HHII")  # name_len, ndim, top_k, chunk
_HDR = struct.Struct("!IIffI")  # totalk, original_size, vmin, scale, bits


class DemoCompressor:
    """Wraps adapted DeMo DCT/top-k/error-feedback for ZepGPU binary envelopes."""

    name = "demo"
    codec_id = CODEC_DEMO

    def __init__(self, config: CompressionConfig) -> None:
        self.config = config
        self.decay = 0.999

    def knobs(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "top_k": self.config.top_k,
            "chunk_size": self.config.chunk_size,
            "quant_bits": self.config.quant_bits,
            "error_feedback": self.config.error_feedback,
            "compression_decay": self.decay,
            "source": "bloc97/DeMo adapted TransformDCT/CompressDCT",
        }

    def compress(self, tensors: dict[str, Any], state: CompressorState) -> CompressedUpdate:
        parts: list[bytes] = [_META.pack(len(tensors))]
        shapes: list[tuple[int, ...]] = []
        names: list[str] = []
        uncompressed = 0
        for name in sorted(tensors):
            array = as_numpy(tensors[name])
            uncompressed += int(array.nbytes)
            residual = state.residuals.get(name) if self.config.error_feedback else None
            idx, val, transmit, xshape, totalk, new_residual = encode_topk(
                array,
                top_k=self.config.top_k,
                chunk_size=self.config.chunk_size,
                residual=None if residual is None else np.asarray(residual, dtype=np.float32),
                decay=self.decay if self.config.error_feedback else 0.0,
            )
            bits = self.config.quant_bits
            vmin = float(val.min()) if val.size else 0.0
            vmax = float(val.max()) if val.size else 1.0
            if vmax <= vmin:
                scale = 1.0
                q = np.zeros(val.shape, dtype=np.uint16)
            else:
                levels = (1 << bits) - 1
                scale = (vmax - vmin) / levels
                q = np.clip(np.rint((val - vmin) / scale), 0, levels).astype(np.uint16)

            # Residual must track quantized wire values, not pre-quant selection.
            val_q = (q.astype(np.float32) * np.float32(scale) + np.float32(vmin)).astype(np.float32)
            transmit_q = decode_topk(
                idx,
                val_q,
                shape=array.shape,
                chunk_size=self.config.chunk_size,
                xshape=xshape,
                totalk=totalk,
            )
            if self.config.error_feedback:
                delta = transmit.reshape(-1) + new_residual.reshape(-1)
                state.residuals[name] = (delta - transmit_q.reshape(-1)).astype(np.float32)
            else:
                state.residuals[name] = np.zeros(array.size, dtype=np.float32)

            effective_top_k = int(idx.shape[-1]) if idx.size else 1
            name_b = name.encode("utf-8")
            shape = tuple(int(dim) for dim in array.shape)
            shapes.append(shape)
            names.append(name)
            parts.append(
                _ONE.pack(len(name_b), len(shape), effective_top_k, self.config.chunk_size)
            )
            parts.append(name_b)
            parts.append(struct.pack(f"!{len(shape)}q", *shape))
            parts.append(_HDR.pack(totalk, array.size, vmin, scale, bits))
            parts.append(np.asarray(idx, dtype=np.int32).tobytes(order="C"))
            parts.append(np.asarray(q, dtype=np.uint16).tobytes(order="C"))

        payload = b"".join(parts)
        return CompressedUpdate(
            codec=self.codec_id,
            payload=payload,
            shapes=tuple(shapes),
            dtypes=tuple("float32" for _ in names),
            names=tuple(names),
            uncompressed_bytes=uncompressed,
            compressed_bytes=len(payload),
            metadata=self.knobs(),
        )

    def decompress(self, update: CompressedUpdate) -> dict[str, Any]:
        if update.codec != self.codec_id:
            raise ValueError(f"expected codec {self.codec_id}, got {update.codec}")
        data = update.payload
        (count,) = _META.unpack_from(data, 0)
        cursor = _META.size
        result: dict[str, Any] = {}
        for _ in range(count):
            name_len, ndim, top_k, chunk = _ONE.unpack_from(data, cursor)
            cursor += _ONE.size
            name = data[cursor : cursor + name_len].decode("utf-8")
            cursor += name_len
            shape = struct.unpack_from(f"!{ndim}q", data, cursor)
            cursor += 8 * ndim
            totalk, original_size, vmin, scale, bits = _HDR.unpack_from(data, cursor)
            cursor += _HDR.size
            rows = (original_size + chunk - 1) // chunk
            idx_bytes = rows * top_k * 4
            val_bytes = rows * top_k * 2
            idx: np.ndarray = np.frombuffer(
                data[cursor : cursor + idx_bytes], dtype=np.int32
            ).reshape(rows, top_k)
            cursor += idx_bytes
            q: np.ndarray = np.frombuffer(
                data[cursor : cursor + val_bytes], dtype=np.uint16
            ).reshape(rows, top_k)
            cursor += val_bytes
            val = (q.astype(np.float32) * np.float32(scale) + np.float32(vmin)).astype(np.float32)
            result[name] = decode_topk(
                idx,
                val,
                shape=shape,
                chunk_size=chunk,
                xshape=(rows, chunk),
                totalk=chunk,
            )
            _ = (bits, totalk)
        return result
