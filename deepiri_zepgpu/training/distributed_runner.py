"""Two-worker LoRA distributed training runner (Phase 17)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from deepiri_zepgpu.training.compare import naive_full_precision_bytes
from deepiri_zepgpu.training.config import (
    DirectBackend,
    RuntimeMode,
    TrainingRunConfig,
    filter_secrets,
)
from deepiri_zepgpu.training.example import EXAMPLE_TEXTS
from deepiri_zepgpu.training.metrics import (
    StepMetric,
    TrainingMetrics,
    assert_catastrophic_quality,
    runtime_versions,
)
from deepiri_zepgpu.training.relay import BinaryRelayStore
from deepiri_zepgpu.training.runner import (
    NvmlSampler,
    _accumulate_step,
    _checkpoint,
    _imports,
    _load_model,
    _resolve_device,
    _seed_runtime,
)
from deepiri_zepgpu.training.sync import SyncOrchestrator
from deepiri_zepgpu.training.transport import (
    InMemoryDirectChannel,
    TransferManager,
)


class DistributedValidationError(ValueError):
    pass


class DistributedAbortError(RuntimeError):
    pass


def assert_in_process_runner_supported(
    config: TrainingRunConfig, *, allow_injected_channel: bool
) -> None:
    """Fail closed when config asks for backends this in-process runner cannot honor."""
    if allow_injected_channel:
        return
    if config.distributed.direct_backend != DirectBackend.MEMORY:
        raise DistributedValidationError(
            "in-process runner supports direct_backend='memory' only; "
            f"got {config.distributed.direct_backend.value!r}. "
            "Inject a LAN channel for loopback tests, or use the multi-process path."
        )
    if config.distributed.runtime.mode != RuntimeMode.PROCESS:
        raise DistributedValidationError(
            "in-process runner supports runtime.mode='process' only; "
            f"got {config.distributed.runtime.mode.value!r}. "
            "Docker runtime is library-present but not supervised by this runner yet."
        )


def validate_matching_configs(left: TrainingRunConfig, right: TrainingRunConfig) -> None:
    checks = [
        ("model_name", left.model_name, right.model_name),
        ("adapter_mode", left.adapter_mode, right.adapter_mode),
        ("precision", left.precision, right.precision),
        ("load_in_4bit", left.load_in_4bit, right.load_in_4bit),
        ("lora.rank", left.lora.rank, right.lora.rank),
        ("lora.alpha", left.lora.alpha, right.lora.alpha),
        ("lora.target_modules", left.lora.target_modules, right.lora.target_modules),
        ("sequence_length", left.sequence_length, right.sequence_length),
    ]
    for name, a, b in checks:
        if a != b:
            raise DistributedValidationError(f"worker configs differ on {name}: {a!r} vs {b!r}")
    if not left.distributed.enabled or not right.distributed.enabled:
        raise DistributedValidationError("both workers require distributed.enabled=true")
    if left.distributed.worker_count != 2 or right.distributed.worker_count != 2:
        raise DistributedValidationError("Phase 17 supports exactly two workers")


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


def _adapters_equal(
    left: dict[str, np.ndarray], right: dict[str, np.ndarray], *, atol: float = 1e-5
) -> bool:
    if set(left) != set(right):
        return False
    return all(np.allclose(left[name], right[name], rtol=0.0, atol=atol) for name in left)


def _delta_from_snapshots(
    before: dict[str, np.ndarray], after: dict[str, np.ndarray]
) -> dict[str, np.ndarray]:
    if set(before) != set(after):
        raise DistributedValidationError("adapter parameter set changed during local steps")
    return {name: (after[name] - before[name]).astype(np.float32) for name in before}


def _channel_register(channel: Any, worker_id: str, receiver: Any) -> None:
    channel.register(worker_id, receiver)


def run_two_worker_training(
    config: TrainingRunConfig,
    *,
    room_id: str | None = None,
    run_id: str | None = None,
    transfer_manager: TransferManager | None = None,
    direct_channel: Any | None = None,
    abort_event: asyncio.Event | None = None,
    round_timeout_seconds: float | None = None,
) -> tuple[TrainingMetrics, TrainingMetrics, dict[str, Any]]:
    """Run an in-process two-worker LoRA sync (process/memory path)."""
    if not config.distributed.enabled:
        raise DistributedValidationError("distributed.enabled must be true")
    assert_in_process_runner_supported(config, allow_injected_channel=direct_channel is not None)
    validate_matching_configs(config, config)
    return asyncio.run(
        run_two_worker_training_async(
            config,
            room_id=room_id,
            run_id=run_id,
            transfer_manager=transfer_manager,
            direct_channel=direct_channel,
            abort_event=abort_event,
            round_timeout_seconds=round_timeout_seconds,
        )
    )


async def run_two_worker_training_async(
    config: TrainingRunConfig,
    *,
    room_id: str | None = None,
    run_id: str | None = None,
    transfer_manager: TransferManager | None = None,
    direct_channel: Any | None = None,
    abort_event: asyncio.Event | None = None,
    round_timeout_seconds: float | None = None,
) -> tuple[TrainingMetrics, TrainingMetrics, dict[str, Any]]:
    torch, transformers, peft = _imports()
    device = _resolve_device(config, torch)
    assert_in_process_runner_supported(config, allow_injected_channel=direct_channel is not None)

    room = room_id or str(uuid.uuid4())
    run = run_id or str(uuid.uuid4())
    worker_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    channel: Any = direct_channel or InMemoryDirectChannel()
    manager = transfer_manager or TransferManager(
        direct=channel, relay=BinaryRelayStore(), chunk_size=64 * 1024
    )
    abort = abort_event or asyncio.Event()
    round_timeout = float(
        round_timeout_seconds
        if round_timeout_seconds is not None
        else config.distributed.runtime.timeout_seconds
    )

    configs: list[TrainingRunConfig] = []
    for rank in range(2):
        worker_config = config.model_copy(deep=True)
        # Identical init seed so adapters start synchronized; diversify only for local steps.
        worker_config.seed = config.seed
        worker_config.output_dir = Path(config.output_dir) / f"worker-{rank}"
        configs.append(worker_config)

    orchestrators = [
        SyncOrchestrator.from_compression_config(
            room_id=room,
            run_id=run,
            worker_id=worker_ids[rank],
            peer_worker_id=worker_ids[1 - rank],
            transfer_manager=manager,
            compression=config.distributed.compression,
            overlap_mode=config.distributed.overlap_mode,
        )
        for rank in range(2)
    ]

    async def _recv0(encoded: bytes) -> None:
        orchestrators[0].receive_encoded(encoded)

    async def _recv1(encoded: bytes) -> None:
        orchestrators[1].receive_encoded(encoded)

    _channel_register(channel, worker_ids[0], _recv0)
    _channel_register(channel, worker_ids[1], _recv1)

    models = []
    optimizers = []
    tokenizers = []
    started_at = datetime.now(UTC)
    for worker_config in configs:
        _seed_runtime(torch, transformers, worker_config.seed)
        worker_config.output_dir.mkdir(parents=True, exist_ok=True)
        worker_config.write_json(worker_config.output_dir / "config.json")
        tokenizer, model, optimizer, start_step, _ = _load_model(
            worker_config, torch, transformers, peft, run, device
        )
        if start_step != 0:
            raise DistributedValidationError("Phase 17 in-process runner does not resume mid-round")
        models.append(model)
        optimizers.append(optimizer)
        tokenizers.append(tokenizer)

    structures = [_adapter_state_dict(model) for model in models]
    if set(structures[0]) != set(structures[1]):
        raise DistributedValidationError("adapter structures do not match across workers")
    for name in structures[0]:
        if structures[0][name].shape != structures[1][name].shape:
            raise DistributedValidationError(f"adapter shape mismatch for {name}")
    # Broadcast worker-0 adapters so both ranks start from identical weights.
    _apply_adapter_state(models[1], structures[0], torch)
    if not _adapters_equal(_adapter_state_dict(models[0]), _adapter_state_dict(models[1])):
        raise DistributedValidationError("failed to broadcast identical initial adapters")

    nvml = (
        NvmlSampler(0 if device.index is None else device.index) if device.type == "cuda" else None
    )
    all_steps: list[list[StepMetric]] = [[], []]
    latest_checkpoints: list[str | None] = [None, None]
    actual_direct_backend = (
        config.distributed.direct_backend.value
        if direct_channel is None
        else "memory" if isinstance(channel, InMemoryDirectChannel) else "memory+delayed"
    )

    def _train_rank(rank: int, round_number: int) -> list[StepMetric]:
        worker_config = configs[rank]
        step_metrics: list[StepMetric] = []
        train_seed = config.seed + rank * config.distributed.worker_seed_offset + round_number
        _seed_runtime(torch, transformers, train_seed)
        texts = worker_config.dataset.texts or EXAMPLE_TEXTS
        encoded = tokenizers[rank](
            texts,
            truncation=True,
            max_length=worker_config.sequence_length,
            padding="max_length",
            return_tensors="pt",
        )
        models[rank].train()
        for local_step in range(1, worker_config.distributed.local_steps_per_round + 1):
            step_index = (
                round_number - 1
            ) * worker_config.distributed.local_steps_per_round + local_step
            step_started = time.perf_counter()
            optimizers[rank].zero_grad(set_to_none=True)
            token_count, sample_count, losses = _accumulate_step(
                worker_config, models[rank], encoded, texts, step_index, device
            )
            optimizers[rank].step()
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            elapsed = time.perf_counter() - step_started
            step_metrics.append(
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
        return step_metrics

    try:
        for round_number in range(1, config.distributed.max_rounds + 1):
            if abort.is_set():
                raise DistributedAbortError("training aborted before round start")
            before = [_adapter_state_dict(model) for model in models]
            # Concurrent local steps on CPU; keep CUDA sequential for device safety.
            rank_steps: list[list[StepMetric]]
            if device.type == "cpu":
                left_steps, right_steps = await asyncio.gather(
                    asyncio.to_thread(_train_rank, 0, round_number),
                    asyncio.to_thread(_train_rank, 1, round_number),
                )
                rank_steps = [left_steps, right_steps]
            else:
                rank_steps = [_train_rank(0, round_number), _train_rank(1, round_number)]
            for rank, steps in enumerate(rank_steps):
                all_steps[rank].extend(steps)

            after = [_adapter_state_dict(model) for model in models]
            deltas = [_delta_from_snapshots(before[i], after[i]) for i in range(2)]
            left_update = orchestrators[0].compressor.compress(deltas[0], orchestrators[0].state)
            right_update = orchestrators[1].compressor.compress(deltas[1], orchestrators[1].state)

            prefetch_slots: list[Any] = [None, None]

            def _make_overlap(rank: int, slots: list[Any]) -> Any:
                async def _overlap() -> None:
                    texts = configs[rank].dataset.texts or EXAMPLE_TEXTS

                    def _tokenize() -> Any:
                        return tokenizers[rank](
                            texts,
                            truncation=True,
                            max_length=configs[rank].sequence_length,
                            padding="max_length",
                            return_tensors="pt",
                        )

                    slots[rank] = await asyncio.to_thread(_tokenize)

                return _overlap

            try:
                left_result, right_result = await asyncio.wait_for(
                    asyncio.gather(
                        orchestrators[0].sync_round(
                            round_number,
                            deltas[0],
                            precompressed=left_update,
                            overlap_work=_make_overlap(0, prefetch_slots),
                        ),
                        orchestrators[1].sync_round(
                            round_number,
                            deltas[1],
                            precompressed=right_update,
                            overlap_work=_make_overlap(1, prefetch_slots),
                        ),
                    ),
                    timeout=round_timeout,
                )
            except Exception as exc:
                abort.set()
                # Preserve latest checkpoints before aborting the peer path.
                for rank, worker_config in enumerate(configs):
                    step = max(
                        1, (round_number - 1) * worker_config.distributed.local_steps_per_round
                    )
                    try:
                        meta = _checkpoint(
                            torch=torch,
                            model=models[rank],
                            optimizer=optimizers[rank],
                            config=worker_config,
                            run_id=run,
                            step=step,
                        )
                        latest_checkpoints[rank] = str(Path(meta.adapter_ref).parent)
                    except Exception:
                        pass
                if isinstance(exc, TimeoutError):
                    raise DistributedAbortError(
                        f"sync round {round_number} exceeded timeout {round_timeout}s"
                    ) from exc
                raise DistributedAbortError(
                    f"sync round {round_number} failed; aborting both workers: {exc}"
                ) from exc
            _ = prefetch_slots

            for rank, result in enumerate((left_result, right_result)):
                applied = {
                    name: (before[rank][name] + result.averaged[name]).astype(np.float32)
                    for name in before[rank]
                }
                _apply_adapter_state(models[rank], applied, torch)
                if all_steps[rank]:
                    last = all_steps[rank][-1]
                    wall = last.compute_seconds + result.blocked_sync_seconds
                    all_steps[rank][-1] = last.model_copy(
                        update={
                            "step_seconds": wall,
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

            if not _adapters_equal(_adapter_state_dict(models[0]), _adapter_state_dict(models[1])):
                raise DistributedValidationError("adapters diverged after sync averaging")

            for rank, worker_config in enumerate(configs):
                step = round_number * worker_config.distributed.local_steps_per_round
                if (
                    round_number % max(1, worker_config.checkpoint_every_steps) == 0
                    or round_number == config.distributed.max_rounds
                ):
                    meta = _checkpoint(
                        torch=torch,
                        model=models[rank],
                        optimizer=optimizers[rank],
                        config=worker_config,
                        run_id=run,
                        step=step,
                    )
                    latest_checkpoints[rank] = str(Path(meta.adapter_ref).parent)
    finally:
        if nvml is not None:
            nvml.shutdown()

    metrics_pair: list[TrainingMetrics] = []
    for rank, worker_config in enumerate(configs):
        final_dir = worker_config.output_dir / "adapter-final"
        models[rank].save_pretrained(final_dir)
        tokenizers[rank].save_pretrained(final_dir)
        peak_allocated = (
            int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
        )
        peak_reserved = int(torch.cuda.max_memory_reserved(device)) if device.type == "cuda" else 0
        hardware: dict[str, Any] = {"device": str(device), "cuda": str(torch.version.cuda)}
        if device.type == "cuda":
            hardware["device"] = torch.cuda.get_device_name(device)
            hardware["compute_capability"] = ".".join(
                map(str, torch.cuda.get_device_capability(device))
            )
        metrics = TrainingMetrics(
            schema_version=2,
            run_id=f"{run}-worker-{rank}",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            model=worker_config.model_name,
            dataset=worker_config.dataset.name,
            adapter_mode=worker_config.adapter_mode.value,
            precision=worker_config.precision.value,
            batch_size=worker_config.batch_size,
            sequence_length=worker_config.sequence_length,
            gradient_accumulation_steps=worker_config.gradient_accumulation_steps,
            software_versions=runtime_versions(
                {"torch": torch, "transformers": transformers, "peft": peft}
            ),
            hardware=hardware,
            steps=all_steps[rank],
            peak_allocated_vram_bytes=peak_allocated,
            peak_reserved_vram_bytes=peak_reserved,
            artifact_ref=str(final_dir),
            compressor_backend=worker_config.distributed.compression.backend.value,
            direct_backend=actual_direct_backend,
        )
        assert_catastrophic_quality(metrics)
        metrics.write_json(worker_config.output_dir / "metrics.json")
        (worker_config.output_dir / "summary.txt").write_text(
            metrics.summary() + "\n", encoding="utf-8"
        )
        metrics_pair.append(metrics)

    sample = structures[0]
    naive = naive_full_precision_bytes([int(arr.nbytes) for arr in sample.values()])
    Path(config.output_dir).mkdir(parents=True, exist_ok=True)
    naive_path = Path(config.output_dir) / "naive_fp_bytes.json"
    naive_path.write_text(json.dumps(naive, indent=2), encoding="utf-8")
    bundle = {
        "room_id": room,
        "run_id": run,
        "worker_ids": worker_ids,
        "naive": naive,
        "latest_checkpoints": latest_checkpoints,
        "worker_metrics": [metrics.model_dump(mode="json") for metrics in metrics_pair],
        "config": config.to_public_dict(),
        "config_redacted": True,
        "runner": "in_process_memory",
        "direct_backend_actual": actual_direct_backend,
    }
    # Persist only the already-redacted public view (never raw TrainingRunConfig).
    public_bundle = filter_secrets(bundle)
    (Path(config.output_dir) / "comparison_bundle.json").write_text(
        json.dumps(public_bundle, indent=2), encoding="utf-8"
    )
    return metrics_pair[0], metrics_pair[1], public_bundle
