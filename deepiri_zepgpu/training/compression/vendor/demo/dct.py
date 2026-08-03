"""Adapted DeMo DCT transform and top-k compression (no einops / DDP).

Derived from bloc97/DeMo `demo.py` (arXiv:2411.19870). See ATTRIBUTION.md.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _dct(x: np.ndarray, norm: str | None = "ortho") -> np.ndarray:
    x_shape = x.shape
    n = x_shape[-1]
    x2 = np.ascontiguousarray(x).reshape(-1, n)
    v = np.concatenate([x2[:, ::2], x2[:, 1::2][:, ::-1]], axis=1)
    vc = np.fft.fft(v, axis=1)
    k = -np.arange(n, dtype=np.float64)[None, :] * math.pi / (2 * n)
    wr = np.cos(k)
    wi = np.sin(k)
    v_out = vc.real * wr - vc.imag * wi
    if norm == "ortho":
        v_out[:, 0] /= math.sqrt(n) * 2
        v_out[:, 1:] /= math.sqrt(n / 2) * 2
    return (2 * v_out).reshape(x_shape).astype(np.float32)


def _idct(x: np.ndarray, norm: str | None = "ortho") -> np.ndarray:
    x_shape = x.shape
    n = x_shape[-1]
    xv = np.ascontiguousarray(x).reshape(-1, n).astype(np.float64) / 2
    if norm == "ortho":
        xv[:, 0] *= math.sqrt(n) * 2
        xv[:, 1:] *= math.sqrt(n / 2) * 2
    k = np.arange(n, dtype=np.float64)[None, :] * math.pi / (2 * n)
    wr = np.cos(k)
    wi = np.sin(k)
    v_t_r = xv
    v_t_i = np.concatenate([xv[:, :1] * 0, -xv[:, ::-1][:, :-1]], axis=1)
    vr = v_t_r * wr - v_t_i * wi
    vi = v_t_r * wi + v_t_i * wr
    v = np.fft.irfft(vr + 1j * vi, n=n, axis=1)
    out = np.zeros_like(v)
    out[:, ::2] += v[:, : n - (n // 2)]
    out[:, 1::2] += v[:, ::-1][:, : n // 2]
    return out.reshape(x_shape).astype(np.float32)


def _get_prime_divisors(n: int) -> list[int]:
    divisors: list[int] = []
    while n % 2 == 0:
        divisors.append(2)
        n //= 2
    while n % 3 == 0:
        divisors.append(3)
        n //= 3
    i = 5
    while i * i <= n:
        for k in (i, i + 2):
            while n % k == 0:
                divisors.append(k)
                n //= k
        i += 6
    if n > 1:
        divisors.append(n)
    return divisors


def _get_divisors(n: int) -> list[int]:
    if n == 1:
        return [1]
    if n <= 1:
        return []
    prime_factors = _get_prime_divisors(n)
    divisors = [1]
    last_prime = 0
    factor = 0
    slice_len = 0
    for prime in prime_factors:
        if last_prime != prime:
            slice_len = len(divisors)
            factor = prime
        else:
            factor *= prime
        for i in range(slice_len):
            divisors.append(divisors[i] * factor)
        last_prime = prime
    divisors.sort()
    return divisors


def get_smaller_split(n: int, close_to: int) -> int:
    all_divisors = _get_divisors(n)
    for ix, val in enumerate(all_divisors):
        if val == close_to:
            return val
        if val > close_to:
            if ix == 0:
                return val
            return all_divisors[ix - 1]
    return n


class TransformDCT:
    """Chunked separable DCT for 1D/2D tensors (DeMo-style)."""

    def __init__(self, shapes: list[tuple[int, ...]], target_chunk: int) -> None:
        self.target_chunk = target_chunk
        self.shape_dict: dict[int, int] = {}
        self.f_dict: dict[int, np.ndarray] = {}
        self.b_dict: dict[int, np.ndarray] = {}
        for shape in shapes:
            for size in shape:
                sc = get_smaller_split(size, self.target_chunk)
                self.shape_dict[size] = sc
                if sc not in self.f_dict:
                    eye = np.eye(sc, dtype=np.float32)
                    self.f_dict[sc] = _dct(eye, norm="ortho")
                    self.b_dict[sc] = _idct(eye, norm="ortho")

    def encode(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        if x.ndim == 1:
            n1 = self.shape_dict[x.shape[0]]
            if x.shape[0] % n1 != 0:
                raise ValueError("1D tensor length must divide DCT chunk")
            blocked = x.reshape(-1, n1)
            return blocked @ self.f_dict[n1]
        if x.ndim == 2:
            n1 = self.shape_dict[x.shape[0]]
            n2 = self.shape_dict[x.shape[1]]
            if x.shape[0] % n1 or x.shape[1] % n2:
                raise ValueError("2D tensor dims must divide DCT chunks")
            y = x.reshape(x.shape[0] // n1, n1, x.shape[1] // n2, n2)
            y = np.einsum("yhxw,hb,wd->yhbd", y, self.f_dict[n1], self.f_dict[n2])
            return y
        flat = x.reshape(-1)
        n1 = get_smaller_split(flat.shape[0], self.target_chunk)
        self.shape_dict[flat.shape[0]] = n1
        if n1 not in self.f_dict:
            eye = np.eye(n1, dtype=np.float32)
            self.f_dict[n1] = _dct(eye, norm="ortho")
            self.b_dict[n1] = _idct(eye, norm="ortho")
        pad = (-flat.size) % n1
        if pad:
            flat = np.concatenate([flat, np.zeros(pad, dtype=np.float32)])
        return (flat.reshape(-1, n1) @ self.f_dict[n1]), flat.size - pad  # type: ignore[return-value]

    def decode(self, x: np.ndarray, original_shape: tuple[int, ...] | None = None) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32)
        if original_shape is not None and len(original_shape) > 2:
            n1 = x.shape[-1]
            recon = x @ self.b_dict[n1]
            return recon.reshape(-1)[: int(np.prod(original_shape))].reshape(original_shape)
        if x.ndim == 2 and original_shape is not None and len(original_shape) == 1:
            n1 = x.shape[1]
            return (x @ self.b_dict[n1]).reshape(-1)[: original_shape[0]]
        if x.ndim == 4:
            n1 = x.shape[2]
            n2 = x.shape[3]
            y = np.einsum("yhbd,hb,wd->yhxw", x, self.b_dict[n1], self.b_dict[n2])
            return y.reshape(y.shape[0] * n1, y.shape[2] * n2)
        if x.ndim == 2:
            n1 = x.shape[1]
            return (x @ self.b_dict[n1]).reshape(-1)
        raise ValueError(f"unsupported DCT decode shape {x.shape}")


class CompressDCT:
    """Top-k sparsification in the DCT domain."""

    @staticmethod
    def _clamp_topk(width: int, topk: int) -> int:
        return max(1, min(topk, width))

    def compress(
        self, x: np.ndarray, topk: int
    ) -> tuple[np.ndarray, np.ndarray, tuple[int, ...], int]:
        x = np.asarray(x, dtype=np.float32)
        xshape = x.shape
        work = x.reshape(*xshape[:-2], -1) if x.ndim > 2 else x
        if work.ndim == 1:
            work = work.reshape(1, -1)
        totalk = work.shape[-1]
        topk = self._clamp_topk(totalk, topk)
        idx = np.argpartition(np.abs(work), -topk, axis=-1)[..., -topk:]
        val = np.take_along_axis(work, idx, axis=-1)
        return idx.astype(np.int32), val.astype(np.float32), xshape, totalk

    def decompress(
        self,
        idx: np.ndarray,
        val: np.ndarray,
        xshape: tuple[int, ...],
        totalk: int,
    ) -> np.ndarray:
        if len(xshape) > 2:
            work_shape = (*xshape[:-2], totalk)
        elif len(xshape) == 1:
            work_shape = (1, totalk)
        else:
            work_shape = (xshape[0], totalk) if len(xshape) == 2 else (totalk,)
            if len(xshape) == 2 and xshape[0] * xshape[1] == totalk:
                work_shape = (1, totalk)
        x = np.zeros(work_shape, dtype=np.float32)
        np.put_along_axis(x, idx, val, axis=-1)
        return x.reshape(xshape)


def encode_topk(
    array: np.ndarray,
    *,
    top_k: int,
    chunk_size: int,
    residual: np.ndarray | None,
    decay: float = 0.999,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[int, ...], int, np.ndarray]:
    """Compress one tensor with DeMo-style residual/error feedback."""
    flat_shape = array.shape
    work = array.astype(np.float32).reshape(-1)
    if residual is None:
        delta = work.copy()
    else:
        delta = residual.reshape(-1) * np.float32(decay) + work
    # Prefer exact chunk_size when divisible after pad.
    chunk = chunk_size
    pad = (-delta.size) % chunk
    padded = np.concatenate([delta, np.zeros(pad, dtype=np.float32)]) if pad else delta
    blocked = padded.reshape(-1, chunk)
    # Use identity-sized DCT matrices via TransformDCT helpers.
    eye = np.eye(chunk, dtype=np.float32)
    fwd = _dct(eye, norm="ortho")
    inv = _idct(eye, norm="ortho")
    transformed = blocked @ fwd
    compress = CompressDCT()
    idx, val, xshape, totalk = compress.compress(transformed, top_k)
    recon_freq = compress.decompress(idx, val, xshape, totalk)
    transmit = (recon_freq.reshape(-1, chunk) @ inv).reshape(-1)[: delta.size]
    new_residual = delta - transmit
    return idx, val, transmit.reshape(flat_shape), xshape, totalk, new_residual


def decode_topk(
    idx: np.ndarray,
    val: np.ndarray,
    *,
    shape: tuple[int, ...],
    chunk_size: int,
    xshape: tuple[int, ...],
    totalk: int,
) -> np.ndarray:
    compress = CompressDCT()
    recon_freq = compress.decompress(idx, val, xshape, totalk)
    inv = _idct(np.eye(chunk_size, dtype=np.float32), norm="ortho")
    recon = (recon_freq.reshape(-1, chunk_size) @ inv).reshape(-1)[: int(np.prod(shape))]
    return recon.reshape(shape).astype(np.float32)


def as_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        return value.detach().cpu().numpy().astype(np.float32, copy=True)
    return np.asarray(value, dtype=np.float32)
