"""Single-process WAN LoRA worker against a live coordinator (Phase 17)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from deepiri_zepgpu.training.adapter_utils import (
    adapter_state_dict,
    apply_adapter_state,
    delta_from_snapshots,
)
from deepiri_zepgpu.training.binary import BinaryEnvelope
from deepiri_zepgpu.training.channel_select import (
    DataPlaneEndpoint,
    build_worker_data_plane,
    ensure_peer_connected,
    normalize_worker_transport_mode,
    publish_endpoint,
)
from deepiri_zepgpu.training.config import DistributedStrategy, OverlapMode, TrainingRunConfig
from deepiri_zepgpu.training.diloco import DiLoCoWorkerRuntime
from deepiri_zepgpu.training.example import EXAMPLE_TEXTS
from deepiri_zepgpu.training.island_runtime import IslandRankAssignment, IslandRuntime
from deepiri_zepgpu.training.metrics import (
    StepMetric,
    TrainingMetrics,
    assert_catastrophic_quality,
    runtime_versions,
)
from deepiri_zepgpu.training.placement import PlacementPlan
from deepiri_zepgpu.training.prom_metrics import (
    record_checkpoint,
    record_sync_round,
    record_training_failure,
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
from deepiri_zepgpu.training.transport import (
    DirectUnavailable,
    HttpRelayChannel,
    TransferManager,
)
from deepiri_zepgpu.training.worker import HttpWorkerCoordinator, PersistentTrainingWorker


def _read_run_credential(work_dir: Path) -> str:
    credential = (work_dir / "run.cred").read_text(encoding="utf-8").strip()
    if not credential:
        raise RuntimeError("Phase 18 run credential is empty")
    return credential


def _auth_headers(credential: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {credential}",
        "Content-Type": "application/octet-stream",
    }


async def _phase18_register(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    run_id: str,
    worker_id: str,
    peer_id: str,
    work_dir: Path,
    runtime: DiLoCoWorkerRuntime,
) -> dict[str, Any]:
    response = await client.post(
        f"{base_url.rstrip('/')}/api/v1/training-runs/{run_id}/workers/"
        f"{worker_id}/phase18/register",
        params={"peer_id": peer_id},
        headers=_auth_headers(_read_run_credential(work_dir)),
        content=runtime.initial_state_envelope(),
    )
    response.raise_for_status()
    return dict(response.json())


async def _phase18_submit_and_wait(
    client: httpx.AsyncClient,
    worker: PersistentTrainingWorker,
    *,
    base_url: str,
    run_id: str,
    worker_id: str,
    peer_id: str,
    work_dir: Path,
    round_number: int,
    encoded: bytes,
) -> tuple[bytes, dict[str, Any], float]:
    started = time.perf_counter()
    response = await client.post(
        f"{base_url.rstrip('/')}/api/v1/training-runs/{run_id}/workers/"
        f"{worker_id}/phase18/updates",
        params={"peer_id": peer_id},
        headers=_auth_headers(_read_run_credential(work_dir)),
        content=encoded,
    )
    response.raise_for_status()
    receipt = dict(response.json())
    if receipt.get("disposition") not in {"accepted", "duplicate"}:
        raise RuntimeError(f"outer update rejected: {receipt.get('reason')}")
    state_url = (
        f"{base_url.rstrip('/')}/api/v1/training-runs/{run_id}/workers/"
        f"{worker_id}/phase18/rounds/{round_number}/state"
    )
    while True:
        state_response = await client.get(
            state_url,
            params={"peer_id": peer_id},
            headers={"Authorization": f"Bearer {_read_run_credential(work_dir)}"},
        )
        if state_response.status_code == 200:
            return state_response.content, receipt, time.perf_counter() - started
        if state_response.status_code != 204:
            state_response.raise_for_status()
        await worker.heartbeat({"waiting_for_outer_round": round_number})
        await asyncio.sleep(0.25)


def _phase18_metrics(
    *,
    config: TrainingRunConfig,
    run_id: str,
    worker_id: str,
    started_at: datetime,
    completed_at: datetime,
    steps: list[StepMetric],
    final_dir: Path,
    torch: Any,
    transformers: Any,
    peft: Any,
    device: Any,
    startup: dict[str, Any],
) -> TrainingMetrics:
    phase18 = config.phase18
    if phase18 is None:  # pragma: no cover - caller is schema v3
        raise RuntimeError("Phase 18 configuration is missing")
    placement = PlacementPlan.model_validate(startup["placement_plan"])
    return TrainingMetrics(
        schema_version=3,
        run_id=run_id,
        worker_id=worker_id,
        started_at=started_at,
        completed_at=completed_at,
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
        hardware={"device": str(device), "cuda": str(torch.version.cuda)},
        steps=steps,
        peak_allocated_vram_bytes=(
            int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
        ),
        peak_reserved_vram_bytes=(
            int(torch.cuda.max_memory_reserved(device)) if device.type == "cuda" else 0
        ),
        artifact_ref=str(final_dir),
        compressor_backend=config.distributed.compression.backend.value,
        direct_backend="phase18_coordinator_binary",
        expected_worker_count=phase18.requested_node_count,
        active_worker_count=phase18.requested_node_count,
        min_k=phase18.min_k,
        local_steps_h=phase18.diloco_h,
        current_outer_round=config.distributed.max_rounds,
        island_ids=placement.selected_island_ids,
        placement_status=placement.status.value,
        placement_warnings=placement.warnings,
    )


async def _run_phase18_diloco(
    *,
    client: httpx.AsyncClient,
    worker: PersistentTrainingWorker,
    startup: dict[str, Any],
    config: TrainingRunConfig,
    work_dir: Path,
    base_url: str,
    run_id: str,
    room_id: str,
    worker_id: str,
    peer_id: str,
) -> TrainingMetrics:
    torch, transformers, peft = _imports()
    device = _resolve_device(config, torch)
    _seed_runtime(torch, transformers, config.seed)
    tokenizer, model, optimizer, start_step, _ = _load_model(
        config, torch, transformers, peft, run_id, device
    )
    if start_step != 0:
        raise RuntimeError("Phase 18 process worker does not resume mid-interval")
    identity_path = work_dir / "identity.json"
    identity_blob: dict[str, Any] = {}
    if identity_path.is_file():
        identity_blob = json.loads(identity_path.read_text(encoding="utf-8"))
    local_runtime = DiLoCoWorkerRuntime(
        room_id=room_id,
        run_id=run_id,
        worker_id=worker_id,
        config=config,
        initial_state=adapter_state_dict(model),
    )
    local_runtime.room_mac_key = str(identity_blob.get("room_mac_key") or "") or None
    registration = await _phase18_register(
        client,
        base_url=base_url,
        run_id=run_id,
        worker_id=worker_id,
        peer_id=peer_id,
        work_dir=work_dir,
        runtime=local_runtime,
    )
    if registration.get("bootstrap_required"):
        response = await client.post(
            f"{base_url.rstrip('/')}/api/v1/training-runs/{run_id}/workers/"
            f"{worker_id}/phase18/bootstrap",
            params={"peer_id": peer_id},
            headers={"Authorization": f"Bearer {_read_run_credential(work_dir)}"},
        )
        response.raise_for_status()
        apply_adapter_state(model, local_runtime.apply_global_state(response.content), torch)

    nvml = (
        NvmlSampler(0 if device.index is None else device.index) if device.type == "cuda" else None
    )
    steps: list[StepMetric] = []
    started_at = datetime.now(UTC)
    try:
        for round_number in range(
            local_runtime.applied_round + 1, config.distributed.max_rounds + 1
        ):
            before = adapter_state_dict(model)
            texts = config.dataset.texts or EXAMPLE_TEXTS
            encoded_batch = tokenizer(
                texts,
                truncation=True,
                max_length=config.sequence_length,
                padding="max_length",
                return_tensors="pt",
            )
            model.train()
            for local_step in range(1, local_runtime.job.diloco_h + 1):
                step_index = (round_number - 1) * local_runtime.job.diloco_h + local_step
                step_started = time.perf_counter()
                optimizer.zero_grad(set_to_none=True)
                token_count, sample_count, losses = _accumulate_step(
                    config, model, encoded_batch, texts, step_index, device
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
            delta = delta_from_snapshots(before, adapter_state_dict(model))
            encoded_update = local_runtime.encode_update(
                round_number=round_number,
                delta=delta,
                completed_local_steps=round_number * local_runtime.job.diloco_h,
            )

            async def _outer_sync(
                sync_round: int = round_number,
                sync_update: bytes = encoded_update,
            ) -> dict[str, Any]:
                global_encoded, receipt, blocked = await _phase18_submit_and_wait(
                    client,
                    worker,
                    base_url=base_url,
                    run_id=run_id,
                    worker_id=worker_id,
                    peer_id=peer_id,
                    work_dir=work_dir,
                    round_number=sync_round,
                    encoded=sync_update,
                )
                apply_adapter_state(model, local_runtime.apply_global_state(global_encoded), torch)
                update_envelope = BinaryEnvelope.decode(sync_update)
                try:
                    uncompressed_bytes = int(update_envelope.extensions.decode("ascii"))
                except (UnicodeDecodeError, ValueError):
                    uncompressed_bytes = 0
                last = steps[-1]
                steps[-1] = last.model_copy(
                    update={
                        "step_seconds": last.compute_seconds + blocked,
                        "blocked_sync_seconds": blocked,
                        "sync_seconds": blocked,
                        "bytes_sent": len(sync_update),
                        "bytes_received": len(global_encoded),
                        "uncompressed_bytes": uncompressed_bytes,
                        "compressed_bytes": len(update_envelope.payload),
                        "path_type": "relay",
                    }
                )
                return receipt

            await worker.run_round(round_number, _outer_sync)
            await worker.progress(
                {
                    "outer_round": round_number,
                    "completed_local_steps": round_number * local_runtime.job.diloco_h,
                    "loss": steps[-1].loss,
                }
            )
            if (
                round_number % local_runtime.job.checkpoint_interval_rounds == 0
                or round_number == config.distributed.max_rounds
            ):

                async def _ckpt(checkpoint_round: int = round_number) -> None:
                    _checkpoint(
                        torch=torch,
                        model=model,
                        optimizer=optimizer,
                        config=config,
                        run_id=run_id,
                        step=checkpoint_round * local_runtime.job.diloco_h,
                    )
                    record_checkpoint(room_id=room_id, operation="save", result="ok")

                await worker.checkpoint(_ckpt)

        final_dir = config.output_dir / "adapter-final"
        model.save_pretrained(final_dir)
        tokenizer.save_pretrained(final_dir)
        metrics = _phase18_metrics(
            config=config,
            run_id=run_id,
            worker_id=worker_id,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            steps=steps,
            final_dir=final_dir,
            torch=torch,
            transformers=transformers,
            peft=peft,
            device=device,
            startup=startup,
        )
        assert_catastrophic_quality(metrics)
        metrics.write_json(config.output_dir / "metrics.json")
        (config.output_dir / "summary.txt").write_text(metrics.summary() + "\n", encoding="utf-8")
        await worker.complete({"artifact_ref": str(final_dir)})
        return metrics
    finally:
        if nvml is not None:
            nvml.shutdown()


async def _run_phase18_island(
    *,
    worker: PersistentTrainingWorker,
    startup: dict[str, Any],
    config: TrainingRunConfig,
    identity: dict[str, Any],
    run_id: str,
    worker_id: str,
) -> TrainingMetrics:
    phase18 = config.phase18
    if phase18 is None:  # pragma: no cover
        raise RuntimeError("Phase 18 configuration is missing")
    process_payload = identity.get("process")
    if not isinstance(process_payload, dict):
        raise RuntimeError("island worker identity is missing its rank assignment")
    assignment = IslandRankAssignment(**process_payload)
    placement = PlacementPlan.model_validate(startup["placement_plan"])
    island = next(
        (item for item in placement.candidate_islands if item.island_id == assignment.island_id),
        None,
    )
    if island is None:
        raise RuntimeError("assigned island is absent from persisted placement")
    rendezvous = identity.get("rendezvous")
    if not isinstance(rendezvous, dict):
        raise RuntimeError("island worker identity is missing rendezvous configuration")
    master_addr = rendezvous.get("master_addr")
    master_port = rendezvous.get("master_port")
    if not isinstance(master_addr, str) or not isinstance(master_port, int):
        raise RuntimeError("island rendezvous address is invalid")
    island_runtime = IslandRuntime(
        island=island,
        strategy=phase18.strategy,
        assignment=assignment,
        init_method=f"tcp://{master_addr}:{master_port}",
    )
    island_runtime.initialize_process_group()
    torch, transformers, peft = _imports()
    rank_config = config.model_copy(update={"device": f"cuda:{assignment.device_index}"})
    device = _resolve_device(rank_config, torch)
    _seed_runtime(torch, transformers, config.seed + assignment.global_rank)
    tokenizer, model, _, start_step, _ = _load_model(
        rank_config, torch, transformers, peft, run_id, device
    )
    if start_step != 0:
        raise RuntimeError("island process worker does not resume mid-step")
    model = island_runtime.wrap_model(model)
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=config.learning_rate,
    )
    texts = config.dataset.texts or EXAMPLE_TEXTS
    encoded_batch = tokenizer(
        texts,
        truncation=True,
        max_length=config.sequence_length,
        padding="max_length",
        return_tensors="pt",
    )
    steps: list[StepMetric] = []
    started_at = datetime.now(UTC)
    for step_index in range(1, config.max_steps + 1):
        step_started = time.perf_counter()
        optimizer.zero_grad(set_to_none=True)
        token_count, sample_count, losses = _accumulate_step(
            rank_config, model, encoded_batch, texts, step_index, device
        )
        optimizer.step()
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
                round=step_index,
                path_type="direct",
                global_rank=assignment.global_rank,
                island_rank=assignment.island_rank,
                assigned_device=assignment.device_index,
                peak_gpu_vram_bytes=island_runtime.peak_vram_bytes(),
            )
        )
        if assignment.island_rank == 0:
            await worker.progress(
                {"step": step_index, "strategy": phase18.strategy.value, "loss": steps[-1].loss}
            )
    final_dir = config.output_dir / f"island-{assignment.island_id}-rank-{assignment.island_rank}"
    torch.distributed.barrier()
    if assignment.island_rank == 0:
        model.save_pretrained(final_dir)
        tokenizer.save_pretrained(final_dir)
    metrics = _phase18_metrics(
        config=config,
        run_id=run_id,
        worker_id=worker_id,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        steps=steps,
        final_dir=final_dir,
        torch=torch,
        transformers=transformers,
        peft=peft,
        device=device,
        startup=startup,
    )
    metrics.write_json(config.output_dir / f"metrics-rank-{assignment.island_rank}.json")
    if assignment.island_rank == 0:
        await worker.complete({"artifact_ref": str(final_dir)})
    if torch.distributed.is_initialized():
        torch.distributed.destroy_process_group()
    return metrics


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
    work_dir: Path,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout_seconds
    url = f"{base_url.rstrip('/')}/api/v1/training-runs/{run_id}/workers/{worker_id}/startup"
    while time.perf_counter() < deadline:
        response = await client.get(
            url,
            params={"peer_id": peer_id},
            headers={"Authorization": f"Bearer {_read_run_credential(work_dir)}"},
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
    credential = str(payload["credential"])
    provider_token = str(payload["provider_token"])

    # Emit ready before heavy imports so the coordinator can leave PREPARING promptly.
    async with httpx.AsyncClient(timeout=60.0) as client:
        coordinator = HttpWorkerCoordinator(
            base_url=base_url,
            run_id=run_id,
            peer_id=peer_id,
            client=client,
            authorization_getter=lambda: _read_run_credential(work_dir),
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
            work_dir=work_dir,
            timeout_seconds=float(config.startup_timeout_seconds),
        )
        config = TrainingRunConfig.model_validate(startup["config"])
        config.output_dir = work_dir / "artifacts"
        config.output_dir.mkdir(parents=True, exist_ok=True)

        if config.schema_version == 3:
            phase18 = config.phase18
            if phase18 is None:  # pragma: no cover - validated config invariant
                raise RuntimeError("schema-v3 worker is missing Phase 18 configuration")
            if phase18.strategy not in {
                DistributedStrategy.DILOCO,
                DistributedStrategy.FSDP2,
                DistributedStrategy.TENSOR_PARALLEL,
            }:
                raise RuntimeError(
                    f"unsupported Phase 18 runtime strategy: {phase18.strategy.value}"
                )

            async def _lease_heartbeat_loop() -> None:
                interval = min(
                    30.0,
                    max(5.0, phase18.reservation_ttl_seconds / 3),
                )
                while True:
                    await asyncio.sleep(interval)
                    await worker.heartbeat({"lease_heartbeat": True, "round": worker.round})

            process_assignment = identity.get("process")
            lifecycle_rank = (
                not isinstance(process_assignment, dict)
                or int(process_assignment.get("island_rank", 0)) == 0
            )
            lease_heartbeat = (
                asyncio.create_task(_lease_heartbeat_loop()) if lifecycle_rank else None
            )
            if phase18.strategy == DistributedStrategy.DILOCO:
                operation = _run_phase18_diloco(
                    client=client,
                    worker=worker,
                    startup=startup,
                    config=config,
                    work_dir=work_dir,
                    base_url=base_url,
                    run_id=run_id,
                    room_id=room_id,
                    worker_id=worker_id,
                    peer_id=peer_id,
                )
            elif phase18.strategy in {
                DistributedStrategy.FSDP2,
                DistributedStrategy.TENSOR_PARALLEL,
            }:
                operation = _run_phase18_island(
                    worker=worker,
                    startup=startup,
                    config=config,
                    identity=identity,
                    run_id=run_id,
                    worker_id=worker_id,
                )
            try:
                return await operation
            except Exception:
                record_training_failure(room_id=room_id, cause="worker_crash")
                raise
            finally:
                if lease_heartbeat is not None:
                    lease_heartbeat.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await lease_heartbeat

        # Schema-v2 remains the exact Phase 17 two-worker runner.
        peer_worker_id = str(identity["peer_worker_id"])
        transport_mode = normalize_worker_transport_mode(
            str(identity.get("transport_mode") or "dialout")
        )
        force_relay = bool(identity.get("force_relay", False))
        vpn_ip = identity.get("vpn_ip")
        listen_host = str(identity.get("data_plane_listen_host") or vpn_ip or "127.0.0.1")
        listen_port = int(identity.get("data_plane_listen_port") or 0)
        overlay_backend = str(identity.get("overlay_backend") or "iroh")
        # Per-worker run.cred tokens differ; peer HMAC needs a shared data-plane secret.
        data_plane_credential = str(identity.get("data_plane_secret") or "").strip() or credential
        endpoint_dir = (
            Path(str(identity["endpoint_dir"]))
            if identity.get("endpoint_dir")
            else work_dir / "endpoints"
        )
        identity_peer = DataPlaneEndpoint.from_dict(
            identity.get("peer_data_plane")
            if isinstance(identity.get("peer_data_plane"), dict)
            else None
        )

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
        data_plane = await build_worker_data_plane(
            transport_mode=transport_mode,
            credential=data_plane_credential,
            worker_id=worker_id,
            peer_id=peer_id,
            peer_worker_id=peer_worker_id,
            listen_host=listen_host,
            listen_port=listen_port,
            peer_endpoint=identity_peer,
            overlay_backend=overlay_backend,
            force_relay=force_relay,
        )
        publish_endpoint(endpoint_dir, worker_id, data_plane.local_endpoint)
        await worker.progress(
            {
                "data_plane": (
                    data_plane.local_endpoint.to_dict() if data_plane.local_endpoint else None
                ),
                "transport_mode": transport_mode,
            }
        )
        manager = TransferManager(
            direct=data_plane.channel,
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

        async def _on_direct_bytes(encoded: bytes) -> None:
            orchestrator.receive_encoded(encoded)

        # Register before peer attach so early frames are not dropped.
        register = getattr(data_plane.channel, "register", None)
        if callable(register):
            register(worker_id, _on_direct_bytes)
        else:
            register_receiver = getattr(data_plane.channel, "register_receiver", None)
            if callable(register_receiver):
                register_receiver(_on_direct_bytes)

        # Leave peer unattached on timeout; TransferManager falls back to HTTP relay.
        with contextlib.suppress(TimeoutError, DirectUnavailable):
            await ensure_peer_connected(
                data_plane,
                peer_worker_id=peer_worker_id,
                endpoint_dir=endpoint_dir,
                identity_peer=identity_peer,
                timeout_seconds=min(60.0, float(config.startup_timeout_seconds)),
                http_client=client,
                base_url=base_url,
                run_id=run_id,
                worker_id=worker_id,
                peer_id=peer_id,
                credential=credential,
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
                before = adapter_state_dict(model)
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

                after = adapter_state_dict(model)
                deltas = delta_from_snapshots(before, after)
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
                    record_sync_round(
                        room_id=room_id,
                        path_type=result.path,
                        result="ok",
                        nbytes=result.bytes_sent + result.bytes_received,
                    )
                    applied = {
                        name: (round_before[name] + result.averaged[name]).astype(np.float32)
                        for name in round_before
                    }
                    apply_adapter_state(model, applied, torch)
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

                async def _ckpt(
                    checkpoint_round: int = round_number,
                ) -> None:
                    _checkpoint(
                        torch=torch,
                        model=model,
                        optimizer=optimizer,
                        config=config,
                        run_id=run_id,
                        step=checkpoint_round * config.distributed.local_steps_per_round,
                    )
                    record_checkpoint(room_id=room_id, operation="save", result="ok")

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
                run_id=run_id,
                worker_id=worker_id,
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
                direct_backend=transport_mode if data_plane.needs_peer else "relay",
            )
            assert_catastrophic_quality(metrics)
            metrics.write_json(config.output_dir / "metrics.json")
            (config.output_dir / "summary.txt").write_text(
                metrics.summary() + "\n", encoding="utf-8"
            )
            await worker.complete({"artifact_ref": str(final_dir)})
            return metrics
        finally:
            if nvml is not None:
                nvml.shutdown()
            await data_plane.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 17 single-process WAN LoRA worker")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    metrics = asyncio.run(run_worker(args.work_dir, base_url=args.base_url))
    print(metrics.summary())


if __name__ == "__main__":
    main()
