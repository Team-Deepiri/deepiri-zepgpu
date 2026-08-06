"""Full-precision (naive) compressor for baseline byte comparisons."""

from __future__ import annotations

from typing import Any

from deepiri_zepgpu.training.compression.base import (
    CODEC_NONE,
    CompressedUpdate,
    CompressorState,
    pack_named_arrays,
    unpack_named_arrays,
)


class NoneCompressor:
    name = "none"
    codec_id = CODEC_NONE

    def compress(self, tensors: dict[str, Any], state: CompressorState) -> CompressedUpdate:
        names = sorted(tensors)
        arrays = [tensors[name] for name in names]
        update = pack_named_arrays(names, arrays, codec=self.codec_id)
        # Payload framing overhead exists; naive bytes = raw float32 bytes only.
        return CompressedUpdate(
            codec=update.codec,
            payload=update.payload,
            shapes=update.shapes,
            dtypes=update.dtypes,
            names=update.names,
            uncompressed_bytes=update.uncompressed_bytes,
            compressed_bytes=update.uncompressed_bytes,
            metadata={"framing_bytes": len(update.payload)},
        )

    def decompress(self, update: CompressedUpdate) -> dict[str, Any]:
        if update.codec != self.codec_id:
            raise ValueError(f"expected codec {self.codec_id}, got {update.codec}")
        return unpack_named_arrays(update)

    def knobs(self) -> dict[str, Any]:
        return {"backend": "none"}
