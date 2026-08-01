"""Command line entry point for local adapter training."""

from __future__ import annotations

import argparse
from pathlib import Path

from deepiri_zepgpu.training.config import TrainingRunConfig
from deepiri_zepgpu.training.runner import run_training


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single-GPU LoRA/QLoRA baseline")
    parser.add_argument("config", type=Path, help="Versioned training JSON configuration")
    parser.add_argument("--smoke", action="store_true", help="Limit the run to two short steps")
    parser.add_argument("--resume-from", type=Path, default=None)
    args = parser.parse_args()
    config = TrainingRunConfig.from_json_file(args.config)
    if args.smoke:
        config.smoke_run = True
        config.max_steps = min(config.max_steps, 2)
        config.sequence_length = min(config.sequence_length, 64)
    if args.resume_from:
        config.resume_from = args.resume_from
    print(run_training(config).summary())


if __name__ == "__main__":
    main()
