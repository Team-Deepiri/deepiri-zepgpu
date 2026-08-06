"""Shared math helpers.

Phase 17 DeMo DCT number-theory helpers (`_get_prime_divisors`, `_get_divisors`,
`get_smaller_split`) intentionally remain under
`deepiri_zepgpu.training.compression.vendor.demo.dct` so the vendored algorithm
stays self-contained. Import from that module if a training path needs them;
do not duplicate copies here unless a non-training product surface requires the
same primitives.
"""

from __future__ import annotations
