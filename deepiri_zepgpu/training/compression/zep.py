"""ZepCompressor: DCT + top-k + error-feedback + low-bit WAN update codec.

ZepGPU's native compressor, used for A/B comparison against the adapted DeMo backend.
Uses NumPy only so CI can exercise encode/decode without importing the ML stack at
module import time for unrelated training modules.
"""

from __future__ import annotations

import struct
from typing import Any, cast

import numpy as np

from deepiri_zepgpu.training.compression.base import (
    CODEC_ZEP,
    CompressedUpdate,
    CompressorState,
)
from deepiri_zepgpu.training.config import CompressionConfig

_META = struct.Struct("!I")  # tensor count
_ONE = struct.Struct("!HHIIbI")  # name_len, shape_ndim, top_k, chunk, bits, residual_flag


def _dct_1d(x: np.ndarray) -> np.ndarray:
    """Orthonormal DCT-II along the last axis (FFT-based)."""
    n = x.shape[-1]
    if n == 0:
        return x.copy()
    v = np.concatenate([x[..., ::2], x[..., 1::2][..., ::-1]], axis=-1)
    Vc = np.fft.fft(v, axis=-1)
    k = -np.arange(n, dtype=np.float64) * np.pi / (2 * n)
    wr = np.cos(k)
    wi = np.sin(k)
    V = Vc.real * wr - Vc.imag * wi
    V[..., 0] /= np.sqrt(n) * 2
    if n > 1:
        V[..., 1:] /= np.sqrt(n / 2) * 2
    return cast(np.ndarray, (2 * V).astype(np.float32))


def _idct_1d(X: np.ndarray) -> np.ndarray:
    """Inverse of `_dct_1d` (orthonormal DCT-III via FFT)."""
    n = X.shape[-1]
    if n == 0:
        return X.copy()
    Xv = X.astype(np.float64) / 2
    Xv[..., 0] *= np.sqrt(n) * 2
    if n > 1:
        Xv[..., 1:] *= np.sqrt(n / 2) * 2
    k = np.arange(n, dtype=np.float64) * np.pi / (2 * n)
    wr = np.cos(k)
    wi = np.sin(k)
    Vr = Xv * wr - np.concatenate([Xv[..., :1] * 0, -Xv[..., ::-1][..., :-1]], axis=-1) * wi
    Vi = Xv * wi + np.concatenate([Xv[..., :1] * 0, -Xv[..., ::-1][..., :-1]], axis=-1) * wr
    V = Vr + 1j * Vi
    v = np.fft.irfft(V, n=n, axis=-1)
    x = np.zeros_like(v)
    x[..., ::2] = v[..., : n - (n // 2)]
    x[..., 1::2] = v[..., ::-1][..., : n // 2]
    return cast(np.ndarray, x.astype(np.float32))


def _quantize(values: np.ndarray, bits: int) -> tuple[np.ndarray, float, float]:
    if values.size == 0:
        return values.astype(np.int32), 0.0, 1.0
    vmin = float(values.min())
    vmax = float(values.max())
    if vmax <= vmin:
        return np.zeros(values.shape, dtype=np.int32), vmin, 1.0
    levels = (1 << bits) - 1
    scale = (vmax - vmin) / levels
    q = np.clip(np.rint((values - vmin) / scale), 0, levels).astype(np.int32)
    return cast(np.ndarray, q), vmin, scale


def _dequantize(q: np.ndarray, vmin: float, scale: float) -> np.ndarray:
    return cast(
        np.ndarray, (q.astype(np.float32) * np.float32(scale) + np.float32(vmin)).astype(np.float32)
    )


def _as_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        return cast(np.ndarray, value.detach().cpu().numpy().astype(np.float32, copy=True))
    return cast(np.ndarray, np.asarray(value, dtype=np.float32))


class ZepCompressor:
    name = "zep"
    codec_id = CODEC_ZEP

    def __init__(self, config: CompressionConfig) -> None:
        self.config = config

    def knobs(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "top_k": self.config.top_k,
            "chunk_size": self.config.chunk_size,
            "quant_bits": self.config.quant_bits,
            "error_feedback": self.config.error_feedback,
        }

    def compress(self, tensors: dict[str, Any], state: CompressorState) -> CompressedUpdate:
        parts: list[bytes] = [_META.pack(len(tensors))]
        shapes: list[tuple[int, ...]] = []
        names: list[str] = []
        uncompressed = 0
        for name in sorted(tensors):
            array = _as_numpy(tensors[name])
            flat = array.reshape(-1)
            uncompressed += int(flat.nbytes)
            residual = state.residuals.get(name)
            if residual is None or not self.config.error_feedback:
                residual = np.zeros_like(flat)
            else:
                residual = np.asarray(residual, dtype=np.float32).reshape(-1)
            signal = residual + flat
            chunk = self.config.chunk_size
            pad = (-len(signal)) % chunk
            if pad:
                signal = np.concatenate([signal, np.zeros(pad, dtype=np.float32)])
            chunks = signal.reshape(-1, chunk)
            transformed = _dct_1d(chunks)
            top_k = min(self.config.top_k, chunk)
            abs_vals = np.abs(transformed)
            idx = np.argpartition(abs_vals, -top_k, axis=-1)[..., -top_k:]
            vals = np.take_along_axis(transformed, idx, axis=-1)
            q, vmin, scale = _quantize(vals, self.config.quant_bits)
            recon_vals = _dequantize(q, vmin, scale)
            recon_freq = np.zeros_like(transformed)
            np.put_along_axis(recon_freq, idx, recon_vals, axis=-1)
            recon = _idct_1d(recon_freq).reshape(-1)[: flat.size]
            if self.config.error_feedback:
                state.residuals[name] = (signal[: flat.size] - recon).astype(np.float32)
            else:
                state.residuals[name] = np.zeros_like(flat)

            name_b = name.encode("utf-8")
            shape = tuple(int(dim) for dim in array.shape)
            shapes.append(shape)
            names.append(name)
            parts.append(
                _ONE.pack(
                    len(name_b),
                    len(shape),
                    top_k,
                    chunk,
                    self.config.quant_bits,
                    1 if self.config.error_feedback else 0,
                )
            )
            parts.append(name_b)
            parts.append(struct.pack(f"!{len(shape)}q", *shape))
            parts.append(struct.pack("!ffI", vmin, scale, flat.size))
            # Compact wire types: uint16 indices, uint8/uint16 quantized values.
            parts.append(np.asarray(idx, dtype=np.uint16).tobytes(order="C"))
            if self.config.quant_bits <= 8:
                parts.append(np.asarray(q, dtype=np.uint8).tobytes(order="C"))
            else:
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
            name_len, ndim, top_k, chunk, bits, _ef = _ONE.unpack_from(data, cursor)
            cursor += _ONE.size
            name = data[cursor : cursor + name_len].decode("utf-8")
            cursor += name_len
            shape = struct.unpack_from(f"!{ndim}q", data, cursor)
            cursor += 8 * ndim
            vmin, scale, original_size = struct.unpack_from("!ffI", data, cursor)
            cursor += struct.calcsize("!ffI")
            rows = (original_size + chunk - 1) // chunk
            idx_bytes = rows * top_k * 2
            idx: np.ndarray = np.frombuffer(
                data[cursor : cursor + idx_bytes], dtype=np.uint16
            ).reshape(rows, top_k)
            cursor += idx_bytes
            q: np.ndarray
            if bits <= 8:
                val_bytes = rows * top_k
                q = np.frombuffer(data[cursor : cursor + val_bytes], dtype=np.uint8).reshape(
                    rows, top_k
                )
            else:
                val_bytes = rows * top_k * 2
                q = np.frombuffer(data[cursor : cursor + val_bytes], dtype=np.uint16).reshape(
                    rows, top_k
                )
            cursor += val_bytes
            vals = _dequantize(q, vmin, scale)
            freq = np.zeros((rows, chunk), dtype=np.float32)
            np.put_along_axis(freq, idx, vals, axis=-1)
            recon = _idct_1d(freq).reshape(-1)[:original_size].reshape(shape)
            result[name] = recon.astype(np.float32)
            _ = bits  # validated via pack path
        return result
