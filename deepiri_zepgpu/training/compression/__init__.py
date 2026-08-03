"""Compressed adapter-update codecs for Phase 17 WAN synchronization.

Backends:
- ``zep``: ZepCompressor — DCT + top-k + error feedback + low-bit (native)
- ``demo``: adapted from bloc97/DeMo TransformDCT/CompressDCT (see vendor/demo/)
- ``none``: full-precision packing for naive baselines
"""

from __future__ import annotations

from deepiri_zepgpu.training.compression.base import (
    CODEC_DEMO,
    CODEC_NONE,
    CODEC_ZEP,
    CompressedUpdate,
    CompressorState,
    UpdateCompressor,
    get_compressor,
)
from deepiri_zepgpu.training.config import CompressionConfig, CompressorBackend

__all__ = [
    "CODEC_DEMO",
    "CODEC_NONE",
    "CODEC_ZEP",
    "CompressedUpdate",
    "CompressionConfig",
    "CompressorBackend",
    "CompressorState",
    "UpdateCompressor",
    "get_compressor",
]
