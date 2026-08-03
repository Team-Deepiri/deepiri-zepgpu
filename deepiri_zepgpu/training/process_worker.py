"""Single-process WAN LoRA worker against a live coordinator (Phase 17)."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from deepiri_zepgpu.training.config import OverlapMode, TrainingRunConfig
from deepiri_zepgpu.training.example import EXAMPLE_TEXTS
from deepiri_zepgpu.training.metrics import (
    StepMetric,
    TrainingMetrics,
    assert_catastrophic_quality,
    runtime_versions,
)
from deepiri_zepgpu.training.runner import (
    NvmlSampler,
    _accumulate_step,
    _checkpoint,
    _imports,
    _load_model,
    _resolve_device,
    _seed_runtime,
)
from deepiri_zepgpu.training.sync import (
    DeterministicTransferIdBus,
    SyncOrchestrator,
    deterministic_transfer_id,
)
from deepiri_zepgpu.training.transport import HttpRelayChannel, PcclDirectChannel, TransferManager
from deepiri_zepgpu.training.worker import HttpWorkerCoordinator, PersistentTrainingWorker


def _adapter_state_dict(model: Any) -> dict[str, np.ndarray]:
    state: dict[str, np.ndarray] = {}
    for name, parameter in model.named_parameters():
        if parameter.requires_grad and "lora" in name.lower():
            state[name] = parameter.detach().float().cpu().numpy().astype(np.float32, copy=True)
    if not state:
        for name, parameter in model.named_parameters():
            if parameter.requires_grad:
                state[name] = parameter.detach().float().cpu().numpy().astype(np.float32, copy=True)
    return state


def _apply_adapter_state(model: Any, averaged: dict[str, np.ndarray], torch: Any) -> None:
    with torch.no_grad():
        named = dict(model.named_parameters())
        for name, array in averaged.items():
            parameter = named.get(name)
            if parameter is None or not parameter.requires_grad:
                continue
            tensor = torch.as_tensor(array, device=parameter.device, dtype=parameter.dtype)
            parameter.copy_(tensor)


def _delta_from_snapshots(
    before: dict[str, np.ndarray], after: dict[str, np.ndarray]
) -> dict[str, np.ndarray]:
    if set(before) != set(after):
        raise RuntimeError("adapter parameter set changed during local steps")
    return {name: (after[name] - before[name]).astype(np.float32) for name in before}


def load_worker_identity(work_dir: Path) -> dict[str, Any]:
    identity = json.loads((work_dir / "identity.json").read_text(encoding="utf-8"))
    credential = (work_dir / "run.cred").read_text(encoding="utf-8").strip()
    provider_token = (work_dir / "provider.token").read_text(encoding="utf-8").strip()
    config = TrainingRunConfig.model_validate(
        json.loads((work_dir / "config.json").read_text(encoding="utf-8"))
    )
    return {
        "identity": identity,
        "credential": credential,
        "provider_token": provider_token,
        "config": config,
    }


async def wait_until_running(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    run_id: str,
    worker_id: str,
    peer_id: str,
    credential: str,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_seconds
    url = f"{base_url.rstrip('/')}/api/v1/training-runs/{run_id}/workers/{worker_id}/startup"
    while time.perf_counter() < deadline:
        response = await client.get(
            url,
            params={"peer_id": peer_id},
            headers={"Authorization": f"Bearer {credential}"},
        )
        response.raise_for_status()
        body = response.json()
        if body.get("run_state") == "running":
            return dict(body)
        if body.get("run_state") in {"failed", "cancelled", "timed_out", "completed"}:
            raise RuntimeError(f"run entered terminal state before start: {body.get('run_state')}")
        await asyncio.sleep(0.25)
    raise TimeoutError("timed out waiting for training run to start")


async def run_worker(work_dir: Path, *, base_url: str) -> TrainingMetrics:
    payload = load_worker_identity(work_dir)
    identity = payload["identity"]
    config: TrainingRunConfig = payload["config"]
    config.output_dir = work_dir / "artifacts"
    config.output_dir.mkdir(parents=True, exist_ok=True)

    run_id = str(identity["run_id"])
    room_id = str(identity["room_id"])
    worker_id = str(identity["worker_id"])
    peer_id = str(identity["peer_id"])
    peer_worker_id = str(identity["peer_worker_id"])
    credential = str(payload["credential"])
    provider_token = str(payload["provider_token"])

    # Emit ready before heavy imports so the coordinator can leave PREPARING promptly.
    async with httpx.AsyncClient(timeout=60.0) as client:
        coordinator = HttpWorkerCoordinator(
            base_url=base_url,
            run_id=run_id,
            peer_id=peer_id,
            client=client,
        )
        worker = PersistentTrainingWorker(
            worker_id=worker_id,
            provider_token=provider_token,
            run_credential=credential,
            coordinator=coordinator,
        )
        await worker.start()
        startup = await wait_until_running(
            client,
            base_url=base_url,
            run_id=run_id,
            worker_id=worker_id,
            peer_id=peer_id,
            credential=credential,
            timeout_seconds=float(config.startup_timeout_seconds),
        )
        config = TrainingRunConfig.model_validate(startup["config"])
        config.output_dir = work_dir / "artifacts"
        config.output_dir.mkdir(parents=True, exist_ok=True)

        torch, transformers, peft = _imports()
        device = _resolve_device(config, torch)
        _seed_runtime(torch, transformers, config.seed)

        relay = HttpRelayChannel(
            base_url=base_url,
            peer_id=peer_id,
            credential=credential,
            chunk_size=64 * 1024,
            client=client,
        )
        manager = TransferManager(
            direct=PcclDirectChannel(sender=None),
            relay=relay,
            max_retries=0,
        )
        bus = DeterministicTransferIdBus(run_id=run_id)
        orchestrator = SyncOrchestrator.from_compression_config(
            room_id=room_id,
            run_id=run_id,
            worker_id=worker_id,
            peer_worker_id=peer_worker_id,
            transfer_manager=manager,
            compression=config.distributed.compression,
            overlap_mode=config.distributed.overlap_mode,
            transfer_bus=bus,
            transfer_id_factory=lambda round_number: deterministic_transfer_id(
                run_id, round_number, worker_id
            ),
        )

        tokenizer, model, optimizer, start_step, _ = _load_model(
            config, torch, transformers, peft, run_id, device
        )
        if start_step != 0:
            raise RuntimeError("process worker does not resume mid-round yet")

        nvml = (
            NvmlSampler(0 if device.index is None else device.index)
            if device.type == "cuda"
            else None
        )
        steps: list[StepMetric] = []
        started_at = datetime.now(UTC)
        try:
            for round_number in range(1, config.distributed.max_rounds + 1):
                before = _adapter_state_dict(model)
                texts = config.dataset.texts or EXAMPLE_TEXTS
                encoded = tokenizer(
                    texts,
                    truncation=True,
                    max_length=config.sequence_length,
                    padding="max_length",
                    return_tensors="pt",
                )
                model.train()
                for local_step in range(1, config.distributed.local_steps_per_round + 1):
                    step_index = (
                        round_number - 1
                    ) * config.distributed.local_steps_per_round + local_step
                    step_started = time.perf_counter()
                    optimizer.zero_grad(set_to_none=True)
                    token_count, sample_count, losses = _accumulate_step(
                        config, model, encoded, texts, step_index, device
                    )
                    optimizer.step()
                    if device.type == "cuda":
                        torch.cuda.synchronize(device)
                    elapsed = time.perf_counter() - step_started
                    steps.append(
                        StepMetric(
                            step=step_index,
                            tokens=token_count,
                            samples=sample_count,
                            step_seconds=elapsed,
                            compute_seconds=elapsed,
                            loss=sum(losses) / len(losses),
                            round=round_number,
                            path_type="none",
                            gpu_utilization_percent=nvml.sample() if nvml else None,
                        )
                    )

                after = _adapter_state_dict(model)
                deltas = _delta_from_snapshots(before, after)
                round_before = before
                round_deltas = deltas
                round_texts = texts
                round_no = round_number

                async def _round_op(
                    round_no: int = round_no,
                    round_deltas: dict[str, np.ndarray] = round_deltas,
                    round_before: dict[str, np.ndarray] = round_before,
                    round_texts: list[str] = round_texts,
                ) -> dict[str, Any]:
                    async def _overlap() -> None:
                        if config.distributed.overlap_mode != OverlapMode.EAGER:
                            return
                        _ = tokenizer(
                            round_texts,
                            truncation=True,
                            max_length=config.sequence_length,
                            padding="max_length",
                            return_tensors="pt",
                        )

                    result = await orchestrator.sync_round(
                        round_no,
                        round_deltas,
                        prefer_relay_download=True,
                        overlap_work=_overlap,
                    )
                    applied = {
                        name: (round_before[name] + result.averaged[name]).astype(np.float32)
                        for name in round_before
                    }
                    _apply_adapter_state(model, applied, torch)
                    if steps:
                        last = steps[-1]
                        steps[-1] = last.model_copy(
                            update={
                                "step_seconds": last.compute_seconds + result.blocked_sync_seconds,
                                "blocked_sync_seconds": result.blocked_sync_seconds,
                                "overlapped_sync_seconds": result.overlapped_sync_seconds,
                                "sync_seconds": result.blocked_sync_seconds,
                                "bytes_sent": result.bytes_sent,
                                "bytes_received": result.bytes_received,
                                "uncompressed_bytes": result.uncompressed_bytes,
                                "compressed_bytes": result.compressed_bytes,
                                "compression_ratio": result.compression_ratio,
                                "path_type": result.path,
                                "bandwidth_bps": result.bandwidth_bps,
                            }
                        )
                    return {
                        "path": result.path,
                        "compressed_bytes": result.compressed_bytes,
                        "blocked_sync_seconds": result.blocked_sync_seconds,
                    }

                await worker.run_round(round_number, _round_op)
                await worker.progress(
                    {
                        "round": round_number,
                        "loss": steps[-1].loss if steps else None,
                        "tokens": sum(step.tokens for step in steps),
                    }
                )

                async def _ckpt() -> None:
                    _checkpoint(
                        torch=torch,
                        model=model,
                        optimizer=optimizer,
                        config=config,
                        run_id=run_id,
                        step=round_number * config.distributed.local_steps_per_round,
                    )

                if (
                    round_number % max(1, config.checkpoint_every_steps) == 0
                    or round_number == config.distributed.max_rounds
                ):
                    await worker.checkpoint(_ckpt)

            final_dir = config.output_dir / "adapter-final"
            model.save_pretrained(final_dir)
            tokenizer.save_pretrained(final_dir)
            peak_allocated = (
                int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
            )
            peak_reserved = (
                int(torch.cuda.max_memory_reserved(device)) if device.type == "cuda" else 0
            )
            hardware: dict[str, Any] = {"device": str(device), "cuda": str(torch.version.cuda)}
            if device.type == "cuda":
                hardware["device"] = torch.cuda.get_device_name(device)
            metrics = TrainingMetrics(
                schema_version=2,
                run_id=f"{run_id}-{worker_id}",
                started_at=started_at,
                completed_at=datetime.now(UTC),
                model=config.model_name,
                dataset=config.dataset.name,
                adapter_mode=config.adapter_mode.value,
                precision=config.precision.value,
                batch_size=config.batch_size,
                sequence_length=config.sequence_length,
                gradient_accumulation_steps=config.gradient_accumulation_steps,
                software_versions=runtime_versions(
                    {"torch": torch, "transformers": transformers, "peft": peft}
                ),
                hardware=hardware,
                steps=steps,
                peak_allocated_vram_bytes=peak_allocated,
                peak_reserved_vram_bytes=peak_reserved,
                artifact_ref=str(final_dir),
                compressor_backend=config.distributed.compression.backend.value,
                direct_backend="relay",
            )
            assert_catastrophic_quality(metrics)
            metrics.write_json(config.output_dir / "metrics.json")
            (config.output_dir / "summary.txt").write_text(metrics.summary() + "\n", encoding="utf-8")
            await worker.complete({"artifact_ref": str(final_dir)})
            return metrics
        finally:
            if nvml is not None:
                nvml.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 17 single-process WAN LoRA worker")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    metrics = asyncio.run(run_worker(args.work_dir, base_url=args.base_url))
    print(metrics.summary())


if __name__ == "__main__":
    main()
