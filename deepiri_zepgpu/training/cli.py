"""Command line entry point for local and two-worker WAN adapter training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from deepiri_zepgpu.training.compare import (
    compare_runs,
    comparison_summary,
    write_comparison,
)
from deepiri_zepgpu.training.config import (
    CompressorBackend,
    DirectBackend,
    OverlapMode,
    Precision,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.runner import run_training


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run single-GPU or two-worker WAN LoRA/QLoRA training"
    )
    parser.add_argument("config", type=Path, help="Versioned training JSON configuration")
    parser.add_argument("--smoke", action="store_true", help="Limit the run to a short smoke")
    parser.add_argument("--resume-from", type=Path, default=None)
    parser.add_argument(
        "--wan",
        action="store_true",
        help="Force distributed two-worker in-process WAN sync path",
    )
    parser.add_argument(
        "--compressor",
        choices=["zep", "demo", "none"],
        default=None,
        help="Override compression.backend for A/B comparison",
    )
    parser.add_argument(
        "--direct-backend",
        choices=["memory", "lan", "pccl"],
        default=None,
        help="Override distributed.direct_backend",
    )
    parser.add_argument(
        "--overlap",
        choices=["blocking", "eager"],
        default=None,
        help="Override distributed.overlap_mode",
    )
    parser.add_argument(
        "--compare-phase15",
        type=Path,
        default=None,
        help="Optional Phase 15 metrics JSON for recorded comparison",
    )
    args = parser.parse_args()
    # Apply CLI overrides then re-validate so smoke/WAN bounds and enums re-run.
    overrides: dict = TrainingRunConfig.from_json_file(args.config).model_dump(mode="python")
    if args.smoke:
        overrides["smoke_run"] = True
        overrides["max_steps"] = min(int(overrides.get("max_steps", 2)), 2)
        overrides["sequence_length"] = min(int(overrides.get("sequence_length", 64)), 64)
    if args.resume_from:
        overrides["resume_from"] = args.resume_from
    if args.wan:
        distributed = dict(overrides.get("distributed") or {})
        distributed["enabled"] = True
        overrides["distributed"] = distributed
        overrides["schema_version"] = 2
    if args.compressor:
        distributed = dict(overrides.get("distributed") or {})
        compression = dict(distributed.get("compression") or {})
        compression["backend"] = CompressorBackend(args.compressor).value
        distributed["compression"] = compression
        overrides["distributed"] = distributed
    if args.direct_backend:
        distributed = dict(overrides.get("distributed") or {})
        distributed["direct_backend"] = DirectBackend(args.direct_backend).value
        overrides["distributed"] = distributed
    if args.overlap:
        distributed = dict(overrides.get("distributed") or {})
        distributed["overlap_mode"] = OverlapMode(args.overlap).value
        overrides["distributed"] = distributed
    config = TrainingRunConfig.model_validate(overrides)

    if config.distributed.enabled:
        from deepiri_zepgpu.training.distributed_runner import run_two_worker_training

        # Prefer CPU for process-mode smoke when CUDA may be absent.
        if args.smoke and config.device.startswith("cuda"):
            try:
                import torch

                if not torch.cuda.is_available():
                    config = config.model_copy(
                        update={
                            "device": "cpu",
                            "precision": (
                                Precision.FP32
                                if config.precision.value == "fp16"
                                else config.precision
                            ),
                        }
                    )
                    config = TrainingRunConfig.model_validate(config.model_dump(mode="python"))
            except ImportError:
                config = TrainingRunConfig.model_validate(
                    {**config.model_dump(mode="python"), "device": "cpu"}
                )

        left, right, bundle = run_two_worker_training(config)
        print(left.summary())
        print("---")
        print(right.summary())
        naive_path = Path(config.output_dir) / "naive_fp_bytes.json"
        if args.compare_phase15 and args.compare_phase15.exists():
            comparison = compare_runs(
                phase15=args.compare_phase15,
                phase17=left,
                naive=naive_path if naive_path.exists() else bundle.get("naive"),
                phase17_label=config.distributed.compression.backend.value,
            )
            out = Path(config.output_dir) / "phase17_comparison.json"
            write_comparison(comparison, out)
            print(comparison_summary(comparison))
        else:
            print(
                json.dumps({"naive": bundle.get("naive"), "run_id": bundle.get("run_id")}, indent=2)
            )
        return

    print(run_training(config).summary())


if __name__ == "__main__":
    main()
