"""Hardware-gated single-GPU/FSDP2 comparison for Phase 18 acceptance."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from deepiri_zepgpu.training.config import DistributedStrategy, TrainingRunConfig
from deepiri_zepgpu.training.island_runtime import IslandRankAssignment, IslandRuntime
from deepiri_zepgpu.training.placement import PlacementPlan


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--mode", choices=("single", "fsdp2"), required=True)
    value.add_argument("--hidden-size", type=int, default=4096)
    value.add_argument("--layers", type=int, default=4)
    value.add_argument("--batch-size", type=int, default=1)
    value.add_argument("--zepgpu-manifest", type=Path)
    return value


def build_model(torch: Any, hidden_size: int, layers: int) -> Any:
    blocks = []
    for _ in range(layers):
        blocks.extend(
            [
                torch.nn.Linear(hidden_size, hidden_size, bias=False),
                torch.nn.GELU(),
            ]
        )
    return torch.nn.Sequential(*blocks)


def main() -> int:
    args = parser().parse_args()
    if os.getenv("ZEPGPU_PHASE18_GPU_TEST") != "1":
        print("Set ZEPGPU_PHASE18_GPU_TEST=1 to run hardware acceptance.", file=sys.stderr)
        return 2
    try:
        import torch
    except ImportError:
        print("PyTorch training dependencies are not installed.", file=sys.stderr)
        return 2
    if not torch.cuda.is_available():
        print("CUDA is not available.", file=sys.stderr)
        return 2

    local_rank = int(os.getenv("LOCAL_RANK", "0"))
    world_size = int(os.getenv("WORLD_SIZE", "1"))
    if args.mode == "fsdp2" and world_size < 2:
        print("FSDP2 mode requires torchrun with at least two processes.", file=sys.stderr)
        return 2
    torch.cuda.set_device(local_rank)
    device = torch.device(f"cuda:{local_rank}")
    torch.cuda.reset_peak_memory_stats(device)
    if args.mode == "fsdp2":
        if args.zepgpu_manifest is None:
            print(
                "FSDP2 acceptance requires --zepgpu-manifest from the ZepGPU launcher.",
                file=sys.stderr,
            )
            return 2
        manifest = json.loads(args.zepgpu_manifest.read_text(encoding="utf-8"))
        config = TrainingRunConfig.model_validate(manifest["config"])
        if config.phase18 is None or config.phase18.strategy != DistributedStrategy.FSDP2:
            print("Manifest does not select Phase 18 FSDP2.", file=sys.stderr)
            return 2
        plan = PlacementPlan.model_validate(manifest["placement_plan"])
        processes = [IslandRankAssignment(**item) for item in manifest["processes"]]
        assignment = next(item for item in processes if item.island_rank == local_rank)
        island = next(
            item for item in plan.candidate_islands if item.island_id == assignment.island_id
        )
        runtime = IslandRuntime(
            island=island,
            strategy=DistributedStrategy.FSDP2,
            assignment=assignment,
        )
        runtime.initialize_process_group()
        model = build_model(torch, args.hidden_size, args.layers).to(device)
        model = runtime.wrap_model(model)
    else:
        manifest = {}
        model = build_model(torch, args.hidden_size, args.layers).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    sample = torch.randn(args.batch_size, args.hidden_size, device=device)
    optimizer.zero_grad(set_to_none=True)
    loss = model(sample).float().square().mean()
    loss.backward()
    optimizer.step()
    torch.cuda.synchronize(device)
    result = {
        "mode": args.mode,
        "rank": local_rank,
        "world_size": world_size,
        "loss": float(loss.detach().cpu()),
        "peak_allocated_vram_bytes": int(torch.cuda.max_memory_allocated(device)),
        "device": torch.cuda.get_device_name(device),
        "zepgpu_plan_id": manifest.get("placement_plan", {}).get("plan_id"),
        "zepgpu_reservation_ids": manifest.get("reservation_ids", []),
    }
    print(json.dumps(result, sort_keys=True))
    if args.mode == "fsdp2":
        torch.distributed.destroy_process_group()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
