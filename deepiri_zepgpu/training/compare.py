"""Compare Phase 17 WAN runs against Phase 15 and a naive full-precision baseline.

Quality policy: always record deltas. Do not hard-fail on relative loss percentage.
Catastrophic checks (non-finite loss) live in metrics.assert_catastrophic_quality.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deepiri_zepgpu.training.metrics import TrainingMetrics, load_metrics


def _loss(metrics: TrainingMetrics) -> float | None:
    return metrics.final_loss if metrics.final_loss is not None else metrics.mean_loss


def relative_delta(actual: float | None, baseline: float | None) -> float | None:
    if actual is None or baseline is None or baseline == 0:
        return None
    return (actual - baseline) / abs(baseline)


def naive_full_precision_bytes(tensor_nbytes: list[int]) -> dict[str, Any]:
    """Document naive DDP-style full-precision exchange size for the same payloads."""
    total = int(sum(tensor_nbytes))
    return {
        "schema_version": 1,
        "kind": "naive_full_precision_bytes",
        "compression": "none",
        "tensor_count": len(tensor_nbytes),
        "bytes_per_tensor": tensor_nbytes,
        "bytes_per_round": total,
        "notes": (
            "Naive baseline assumes each adapter-delta tensor is sent uncompressed "
            "at full precision once per sync round (no DCT/top-k/low-bit)."
        ),
    }


def compare_runs(
    *,
    phase15: TrainingMetrics | Path,
    phase17: TrainingMetrics | Path,
    naive: dict[str, Any] | Path | None = None,
    phase17_label: str = "phase17",
) -> dict[str, Any]:
    baseline = load_metrics(phase15) if isinstance(phase15, Path) else phase15
    current = load_metrics(phase17) if isinstance(phase17, Path) else phase17
    naive_data: dict[str, Any] | None = (
        json.loads(naive.read_text(encoding="utf-8")) if isinstance(naive, Path) else naive
    )

    baseline_loss = _loss(baseline)
    current_loss = _loss(current)
    naive_bytes = None if naive_data is None else int(naive_data.get("bytes_per_round", 0))
    compressed_total = int(current.compressed_bytes or current.bytes_sent or 0)
    sync_rounds = max(
        1,
        len(
            {
                step.round
                for step in current.steps
                if step.round is not None and (step.compressed_bytes or step.bytes_sent)
            }
        ),
    )
    # Prefer per-round comparison: totals across rounds vs a per-round naive baseline
    # would incorrectly fail multi-round runs.
    compressed_per_round = compressed_total / float(sync_rounds)
    naive_total = None if naive_bytes is None else naive_bytes * sync_rounds
    comparison = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "phase15": {
            "run_id": baseline.run_id,
            "final_loss": baseline_loss,
            "tokens_per_second": baseline.tokens_per_second,
            "peak_allocated_vram_bytes": baseline.peak_allocated_vram_bytes,
            "bytes_sent": baseline.bytes_sent,
            "communication_compute_ratio": baseline.communication_compute_ratio,
        },
        "phase17": {
            "label": phase17_label,
            "run_id": current.run_id,
            "final_loss": current_loss,
            "tokens_per_second": current.tokens_per_second,
            "peak_allocated_vram_bytes": current.peak_allocated_vram_bytes,
            "bytes_sent": current.bytes_sent,
            "compressed_bytes": current.compressed_bytes,
            "uncompressed_bytes": current.uncompressed_bytes,
            "compression_ratio": current.compression_ratio,
            "blocked_sync_seconds": current.blocked_sync_seconds,
            "overlapped_sync_seconds": current.overlapped_sync_seconds,
            "communication_compute_ratio": current.communication_compute_ratio,
            "path_type": current.path_type,
            "compressor_backend": current.compressor_backend,
            "direct_backend": current.direct_backend,
        },
        "deltas": {
            "loss_relative": relative_delta(current_loss, baseline_loss),
            "tokens_per_second_relative": relative_delta(
                current.tokens_per_second, baseline.tokens_per_second
            ),
            "vram_relative": relative_delta(
                float(current.peak_allocated_vram_bytes),
                float(baseline.peak_allocated_vram_bytes),
            ),
        },
        "naive_baseline": naive_data,
        "efficiency": {
            "compressed_bytes_total": compressed_total,
            "compressed_bytes_per_round": compressed_per_round,
            "sync_rounds": sync_rounds,
            "naive_bytes_per_round": naive_bytes,
            "naive_bytes_total": naive_total,
            "bytes_below_naive": (
                None if naive_bytes is None else bool(compressed_per_round < float(naive_bytes))
            ),
            "byte_reduction_factor": (
                None
                if naive_bytes is None or naive_bytes == 0 or compressed_per_round <= 0
                else float(naive_bytes) / float(compressed_per_round)
            ),
        },
        "quality_policy": (
            "Record comparison only. Do not hard-fail on relative loss percentage. "
            "Fail only on non-finite loss, non-completion, or toy compressor non-convergence."
        ),
    }
    return comparison


def write_comparison(comparison: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")


def comparison_summary(comparison: dict[str, Any]) -> str:
    p15 = comparison["phase15"]
    p17 = comparison["phase17"]
    eff = comparison["efficiency"]
    deltas = comparison["deltas"]
    lines = [
        "Phase 15 vs Phase 17 comparison (recorded; no relative-loss hard gate)",
        f"  Phase 15 loss={p15['final_loss']} tokens/s={p15['tokens_per_second']:.2f} "
        f"bytes={p15['bytes_sent']} ratio={p15['communication_compute_ratio']:.6f}",
        f"  Phase 17 ({p17['label']}) loss={p17['final_loss']} "
        f"tokens/s={p17['tokens_per_second']:.2f} compressed={p17['compressed_bytes']} "
        f"ratio={p17['communication_compute_ratio']:.6f} path={p17['path_type']}",
        f"  Loss relative delta: {deltas['loss_relative']}",
        f"  Bytes below naive: {eff['bytes_below_naive']} "
        f"(factor={eff['byte_reduction_factor']})",
    ]
    return "\n".join(lines)
