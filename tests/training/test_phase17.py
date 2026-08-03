"""Phase 17 compression, metrics, compare, sync, runtime, and LAN tests."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from deepiri_zepgpu.training.compare import (
    compare_runs,
    comparison_summary,
    naive_full_precision_bytes,
    relative_delta,
    write_comparison,
)
from deepiri_zepgpu.training.compression.base import CompressorState, get_compressor
from deepiri_zepgpu.training.config import (
    CompressionConfig,
    CompressorBackend,
    DirectBackend,
    DistributedTrainingConfig,
    RuntimeConfig,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.image_trust import ImageTrustError, ImageTrustPolicy
from deepiri_zepgpu.training.lan import LanDirectChannel, build_direct_channel
from deepiri_zepgpu.training.metrics import (
    StepMetric,
    TrainingMetrics,
    assert_catastrophic_quality,
    communication_to_compute_ratio,
    load_metrics,
)
from deepiri_zepgpu.training.relay import BinaryRelayStore
from deepiri_zepgpu.training.runtime import TrainingRuntime, TrainingRuntimeError
from deepiri_zepgpu.training.sync import SyncOrchestrator
from deepiri_zepgpu.training.transport import PcclDirectChannel, TransferManager
from deepiri_zepgpu.training.workload import TrainingWorkloadSpec


def test_distributed_config_and_codec_ids() -> None:
    config = TrainingRunConfig(
        schema_version=1,
        distributed=DistributedTrainingConfig(enabled=True, max_rounds=2, local_steps_per_round=1),
    )
    assert config.schema_version == 2
    assert config.max_steps == 2
    assert config.codec_id() == "zep-v1"
    config.distributed.compression.backend = CompressorBackend.DEMO
    assert config.codec_id() == "demo-v1"
    with pytest.raises(ValidationError):
        RuntimeConfig(privileged=True)


@pytest.mark.parametrize("backend", [CompressorBackend.ZEP, CompressorBackend.DEMO])
def test_compressor_roundtrip_and_smaller_than_naive(backend: CompressorBackend) -> None:
    rng = np.random.default_rng(0)
    tensors = {
        "a": rng.normal(size=4096).astype(np.float32),
        "b": rng.normal(size=(64, 64)).astype(np.float32),
    }
    naive = get_compressor(CompressionConfig(backend=CompressorBackend.NONE))
    naive_update = naive.compress(tensors, CompressorState())
    compressor = get_compressor(
        CompressionConfig(backend=backend, top_k=8, chunk_size=64, quant_bits=4)
    )
    update = compressor.compress(tensors, CompressorState())
    restored = compressor.decompress(update)
    assert set(restored) == set(tensors)
    assert restored["a"].shape == tensors["a"].shape
    assert restored["b"].shape == tensors["b"].shape
    assert update.compressed_bytes < naive_update.uncompressed_bytes
    assert update.codec.endswith("-v1")


@pytest.mark.parametrize("backend", [CompressorBackend.ZEP, CompressorBackend.DEMO])
def test_toy_compressor_convergence(backend: CompressorBackend) -> None:
    compressor = get_compressor(
        CompressionConfig(backend=backend, top_k=32, chunk_size=32, quant_bits=8)
    )
    target = {"x": np.zeros(64, dtype=np.float32)}
    current = {"x": np.linspace(-1, 1, 64, dtype=np.float32)}
    state = CompressorState()
    energies = []
    for _ in range(12):
        delta = {"x": (target["x"] - current["x"]).astype(np.float32)}
        update = compressor.compress(delta, state)
        applied = compressor.decompress(update)
        current["x"] = current["x"] + applied["x"]
        energies.append(float(np.linalg.norm(current["x"] - target["x"])))
    assert energies[-1] < energies[0]


def test_metrics_v2_ratio_uses_blocked_only_and_loads_v1(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    metrics = TrainingMetrics(
        schema_version=2,
        run_id="r",
        started_at=now,
        completed_at=now,
        model="m",
        dataset="d",
        adapter_mode="lora",
        precision="fp32",
        batch_size=1,
        sequence_length=64,
        gradient_accumulation_steps=1,
        steps=[
            StepMetric(
                step=1,
                tokens=10,
                samples=1,
                step_seconds=5,
                compute_seconds=4,
                blocked_sync_seconds=1,
                overlapped_sync_seconds=2,
                uncompressed_bytes=100,
                compressed_bytes=25,
                path_type="direct",
                loss=1.5,
            )
        ],
        compressor_backend="zep",
        direct_backend="memory",
    )
    assert metrics.communication_compute_ratio == communication_to_compute_ratio(1, 4)
    assert metrics.compression_ratio == 0.25
    assert metrics.final_loss == 1.5
    path = tmp_path / "m.json"
    metrics.write_json(path)
    loaded = load_metrics(path)
    assert loaded.schema_version == 2

    v1 = {
        "schema_version": 1,
        "run_id": "legacy",
        "started_at": now.isoformat(),
        "completed_at": now.isoformat(),
        "model": "m",
        "dataset": "d",
        "adapter_mode": "lora",
        "precision": "fp16",
        "batch_size": 1,
        "sequence_length": 64,
        "gradient_accumulation_steps": 1,
        "steps": [
            {
                "step": 1,
                "tokens": 1,
                "samples": 1,
                "step_seconds": 1,
                "compute_seconds": 1,
                "sync_seconds": 0,
                "bytes_sent": 0,
                "bytes_received": 0,
                "loss": 6.8,
            }
        ],
    }
    v1_path = tmp_path / "v1.json"
    import json

    v1_path.write_text(json.dumps(v1), encoding="utf-8")
    legacy = load_metrics(v1_path)
    assert legacy.final_loss == 6.8
    assert_catastrophic_quality(legacy)
    with pytest.raises(ValidationError):
        StepMetric(
            step=1,
            tokens=1,
            samples=1,
            step_seconds=1,
            compute_seconds=1,
            loss=float("nan"),
        )


def test_compare_records_without_relative_loss_gate(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    phase15 = TrainingMetrics(
        run_id="p15",
        started_at=now,
        completed_at=now,
        model="m",
        dataset="d",
        adapter_mode="lora",
        precision="fp16",
        batch_size=1,
        sequence_length=64,
        gradient_accumulation_steps=1,
        steps=[
            StepMetric(step=1, tokens=1, samples=1, step_seconds=1, compute_seconds=1, loss=6.89)
        ],
    )
    phase17 = TrainingMetrics(
        schema_version=2,
        run_id="p17",
        started_at=now,
        completed_at=now,
        model="m",
        dataset="d",
        adapter_mode="lora",
        precision="fp16",
        batch_size=1,
        sequence_length=64,
        gradient_accumulation_steps=1,
        steps=[
            StepMetric(
                step=1,
                tokens=1,
                samples=1,
                step_seconds=1,
                compute_seconds=1,
                loss=8.0,
                compressed_bytes=50,
                uncompressed_bytes=200,
                round=1,
            ),
            StepMetric(
                step=2,
                tokens=1,
                samples=1,
                step_seconds=1,
                compute_seconds=1,
                loss=7.5,
                compressed_bytes=50,
                uncompressed_bytes=200,
                round=2,
            ),
        ],
    )
    naive = naive_full_precision_bytes([200])
    comparison = compare_runs(phase15=phase15, phase17=phase17, naive=naive, phase17_label="zep")
    assert comparison["deltas"]["loss_relative"] == relative_delta(7.5, 6.89)
    # Total compressed=100 across 2 rounds; per-round=50 < naive 200.
    assert comparison["efficiency"]["sync_rounds"] == 2
    assert comparison["efficiency"]["compressed_bytes_per_round"] == 50.0
    assert comparison["efficiency"]["bytes_below_naive"] is True
    assert "Record comparison only" in comparison["quality_policy"]
    out = tmp_path / "cmp.json"
    write_comparison(comparison, out)
    assert "Phase 15 vs Phase 17" in comparison_summary(comparison)


def test_demo_topk_greater_than_chunk_roundtrips() -> None:
    compressor = get_compressor(
        CompressionConfig(backend=CompressorBackend.DEMO, top_k=32, chunk_size=8, quant_bits=4)
    )
    tensors = {"w": np.linspace(-1, 1, 64, dtype=np.float32)}
    update = compressor.compress(tensors, CompressorState())
    restored = compressor.decompress(update)
    assert restored["w"].shape == tensors["w"].shape


@pytest.mark.asyncio
async def test_eager_overlap_measures_concurrent_work() -> None:
    import uuid

    from deepiri_zepgpu.training.config import OverlapMode
    from deepiri_zepgpu.training.transport import DelayedDirectChannel, InMemoryDirectChannel

    room, run = str(uuid.uuid4()), str(uuid.uuid4())
    w0, w1 = str(uuid.uuid4()), str(uuid.uuid4())
    memory = InMemoryDirectChannel()
    delayed = DelayedDirectChannel(memory, delay_seconds=0.05)
    store = BinaryRelayStore()
    manager = TransferManager(direct=delayed, relay=store, chunk_size=1024)
    compression = CompressionConfig(backend=CompressorBackend.ZEP, top_k=8, chunk_size=32)
    left = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w0,
        peer_worker_id=w1,
        transfer_manager=manager,
        compression=compression,
        overlap_mode=OverlapMode.EAGER,
    )
    right = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w1,
        peer_worker_id=w0,
        transfer_manager=manager,
        compression=compression,
        overlap_mode=OverlapMode.EAGER,
    )

    async def recv0(encoded: bytes) -> None:
        left.receive_encoded(encoded)

    async def recv1(encoded: bytes) -> None:
        right.receive_encoded(encoded)

    delayed.register(w0, recv0)
    delayed.register(w1, recv1)

    async def busy() -> None:
        await asyncio.sleep(0.04)

    d0 = {"a": np.ones(64, dtype=np.float32)}
    d1 = {"a": np.full(64, 5.0, dtype=np.float32)}
    r0, r1 = await asyncio.gather(
        left.sync_round(1, d0, overlap_work=busy),
        right.sync_round(1, d1, overlap_work=busy),
    )
    assert r0.overlapped_sync_seconds > 0.02
    assert r0.blocked_sync_seconds < r0.overlapped_sync_seconds + r0.blocked_sync_seconds
    assert np.allclose(r0.averaged["a"], 3.0)
    _ = r1


def test_in_process_runner_rejects_unsupported_backends() -> None:
    from deepiri_zepgpu.training.distributed_runner import (
        DistributedValidationError,
        assert_in_process_runner_supported,
    )

    config = TrainingRunConfig(
        schema_version=2,
        distributed=DistributedTrainingConfig(enabled=True, direct_backend=DirectBackend.LAN),
    )
    with pytest.raises(DistributedValidationError, match="memory"):
        assert_in_process_runner_supported(config, allow_injected_channel=False)


@pytest.mark.asyncio
async def test_sync_relay_download_via_transfer_bus() -> None:
    import uuid

    from deepiri_zepgpu.training.sync import InMemoryTransferIdBus

    room, run = str(uuid.uuid4()), str(uuid.uuid4())
    w0, w1 = str(uuid.uuid4()), str(uuid.uuid4())
    store = BinaryRelayStore()
    bus = InMemoryTransferIdBus()
    compression = CompressionConfig(backend=CompressorBackend.ZEP, top_k=8, chunk_size=32)
    left_manager = TransferManager(
        direct=PcclDirectChannel(sender=None), relay=store, chunk_size=1024, max_retries=0
    )
    right_manager = TransferManager(
        direct=PcclDirectChannel(sender=None), relay=store, chunk_size=1024, max_retries=0
    )
    left = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w0,
        peer_worker_id=w1,
        transfer_manager=left_manager,
        compression=compression,
        transfer_bus=bus,
    )
    right = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w1,
        peer_worker_id=w0,
        transfer_manager=right_manager,
        compression=compression,
        transfer_bus=bus,
    )
    d0 = {"a": np.ones(64, dtype=np.float32)}
    d1 = {"a": np.full(64, 5.0, dtype=np.float32)}
    r0, r1 = await asyncio.gather(
        left.sync_round(1, d0, prefer_relay_download=True),
        right.sync_round(1, d1, prefer_relay_download=True),
    )
    assert r0.path == "relay"
    assert r1.path == "relay"
    assert np.allclose(r0.averaged["a"], r1.averaged["a"])


@pytest.mark.asyncio
async def test_sync_direct_and_relay_fallback() -> None:
    import uuid

    room, run = str(uuid.uuid4()), str(uuid.uuid4())
    w0, w1 = str(uuid.uuid4()), str(uuid.uuid4())
    memory = build_direct_channel("memory")
    store = BinaryRelayStore()
    manager = TransferManager(direct=memory, relay=store, chunk_size=1024)
    left = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w0,
        peer_worker_id=w1,
        transfer_manager=manager,
        compression=CompressionConfig(backend=CompressorBackend.ZEP, top_k=8, chunk_size=32),
    )
    right = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w1,
        peer_worker_id=w0,
        transfer_manager=manager,
        compression=CompressionConfig(backend=CompressorBackend.ZEP, top_k=8, chunk_size=32),
    )

    async def recv0(encoded: bytes) -> None:
        left.receive_encoded(encoded)

    async def recv1(encoded: bytes) -> None:
        right.receive_encoded(encoded)

    memory.register(w0, recv0)
    memory.register(w1, recv1)
    d0 = {"a": np.ones(64, dtype=np.float32)}
    d1 = {"a": np.full(64, 5.0, dtype=np.float32)}
    u0 = left.compressor.compress(d0, left.state)
    u1 = right.compressor.compress(d1, right.state)
    e0 = left.envelope_for(1, u0)
    e1 = right.envelope_for(1, u1)
    r0, r1 = await asyncio.gather(
        left.sync_round(1, d0, peer_encoded=e1.encode(), precompressed=u0),
        right.sync_round(1, d1, peer_encoded=e0.encode(), precompressed=u1),
    )
    assert r0.path == "direct"
    assert np.allclose(r0.averaged["a"], 3.0)

    relay_manager = TransferManager(
        direct=PcclDirectChannel(sender=None), relay=store, chunk_size=1024, max_retries=0
    )
    left_relay = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w0,
        peer_worker_id=w1,
        transfer_manager=relay_manager,
        compression=CompressionConfig(backend=CompressorBackend.ZEP, top_k=8, chunk_size=32),
    )
    packed = left_relay.compressor.compress(d0, left_relay.state)
    peer = right.envelope_for(2, right.compressor.compress(d1, CompressorState()))
    relay_result = await left_relay.sync_round(
        2, d0, peer_encoded=peer.encode(), precompressed=packed
    )
    assert relay_result.path == "relay"


@pytest.mark.asyncio
async def test_lan_direct_hmac_roundtrip() -> None:
    cred = "test-credential"
    a = LanDirectChannel(credential=cred)
    b = LanDirectChannel(credential=cred)
    received: list[bytes] = []

    async def on_msg(encoded: bytes) -> None:
        received.append(encoded)

    b.register_receiver(on_msg)
    port = await b.start()
    await a.start()
    a.set_peer("b", "127.0.0.1", port)
    await a.send("b", b"hello-phase17")
    await asyncio.sleep(0.05)
    assert received == [b"hello-phase17"]
    await a.stop()
    await b.stop()


def test_image_trust_and_workload_security(tmp_path: Path) -> None:
    policy = ImageTrustPolicy({"zepgpu-training:local"})
    policy.assert_trusted("zepgpu-training:local")
    with pytest.raises(ImageTrustError):
        policy.assert_trusted("untrusted:latest")
    with pytest.raises(ValidationError):
        TrainingWorkloadSpec(image="zepgpu-training:local", privileged=True)
    with pytest.raises(ValidationError):
        TrainingWorkloadSpec(
            image="zepgpu-training:local",
            user="1000:1000",
            host_work_dir=Path("/"),
        )
    with pytest.raises(ValidationError):
        TrainingWorkloadSpec(
            image="zepgpu-training:local",
            user="1000:1000",
            host_work_dir=tmp_path / "escape",
            mount_root=tmp_path / "jail",
        )
    with pytest.raises(ValidationError, match="user"):
        TrainingWorkloadSpec(
            image="zepgpu-training:local",
            host_work_dir=tmp_path / "needs-user",
        )
    with pytest.raises(ValidationError, match="user"):
        TrainingWorkloadSpec(image="zepgpu-training:local", user="-1:0")
    with pytest.raises(ValidationError, match="user"):
        TrainingWorkloadSpec(image="zepgpu-training:local", user="1000:")
    jail = tmp_path / "jail"
    jail.mkdir()
    work = jail / "run"
    work.mkdir()
    spec = TrainingWorkloadSpec(
        image="zepgpu-training:local",
        environment={"HF_TOKEN": "secret", "SAFE": "1"},
        user="1000:1000",
        host_work_dir=work,
        mount_root=jail,
    )
    env = spec.filtered_environment()
    assert "HF_TOKEN" not in env
    assert env["SAFE"] == "1"
    runtime = TrainingRuntime(trust_policy=policy)
    cmd = runtime.build_docker_command(spec, name="zepgpu-train-test")
    assert "--privileged" not in cmd
    assert "zepgpu-training:local" in cmd
    assert any(part.startswith(f"{work.resolve()}:") for part in cmd)
    # Single --gpus device list
    assert cmd.count("--gpus") == 1
    with_user = TrainingWorkloadSpec(
        image="zepgpu-training:local",
        user="1000:1000",
        gpu_devices=[],
    )
    user_cmd = runtime.build_docker_command(with_user, name="zepgpu-train-user")
    assert "--user" in user_cmd
    assert "1000:1000" in user_cmd


def test_runtime_fail_closed_without_allowlist(tmp_path: Path) -> None:
    missing = tmp_path / "missing.allowlist"
    with pytest.raises(TrainingRuntimeError, match="allowlist missing"):
        TrainingRuntime(allowlist_path=missing)
    with pytest.raises(TrainingRuntimeError, match="allowlist missing"):
        TrainingRuntime(allowlist_path=missing, allow_missing_allowlist=False)
    # Explicit opt-in remains available for local experiments only.
    ok = TrainingRuntime(allowlist_path=missing, allow_missing_allowlist=True)
    assert "zepgpu-training:local" in ok.trust_policy.allowed
    empty = tmp_path / "empty.allowlist"
    empty.write_text("# comment only\n", encoding="utf-8")
    with pytest.raises(ImageTrustError, match="empty"):
        ImageTrustPolicy.from_file(empty)


@pytest.mark.asyncio
async def test_process_runtime_timeout_enforced() -> None:
    runtime = TrainingRuntime(trust_policy=ImageTrustPolicy({"zepgpu-training:local"}))
    spec = TrainingWorkloadSpec(
        image="zepgpu-training:local",
        command=["python", "-c", "import time; time.sleep(30)"],
        timeout_seconds=30,
    )
    handle = await runtime.start_process(spec)
    with pytest.raises(TrainingRuntimeError, match="timeout"):
        await runtime.wait(handle, timeout_seconds=0.2)
    assert runtime.list_active() == []


@pytest.mark.asyncio
async def test_lan_rejects_oversized_frame_and_bad_hmac() -> None:
    with pytest.raises(ValueError, match="credential"):
        LanDirectChannel(credential="")
    a = LanDirectChannel(credential="cred", max_frame_bytes=64)
    b = LanDirectChannel(credential="cred", max_frame_bytes=64)
    received: list[bytes] = []

    async def on_msg(encoded: bytes) -> None:
        received.append(encoded)

    b.register_receiver(on_msg)
    port = await b.start()
    await a.start()
    a.set_peer("b", "127.0.0.1", port)
    from deepiri_zepgpu.training.transport import DirectUnavailable

    with pytest.raises(DirectUnavailable):
        await a.send("b", b"x" * 128)
    await a.send("b", b"ok")
    await asyncio.sleep(0.05)
    assert received == [b"ok"]
    evil = LanDirectChannel(credential="wrong", max_frame_bytes=64)
    await evil.start()
    evil.set_peer("b", "127.0.0.1", port)
    await evil.send("b", b"nope")
    await asyncio.sleep(0.05)
    assert received == [b"ok"]
    await a.stop()
    await b.stop()
    await evil.stop()


@pytest.mark.asyncio
async def test_lan_unknown_peer_and_connect_failure() -> None:
    from deepiri_zepgpu.training.transport import DirectUnavailable

    channel = LanDirectChannel(credential="cred")
    await channel.start()
    with pytest.raises(DirectUnavailable, match="no LAN address"):
        await channel.send("missing", b"hello")
    channel.set_peer("gone", "127.0.0.1", 1)  # nothing listening
    with pytest.raises(DirectUnavailable, match="connect failed"):
        await channel.send("gone", b"hello")
    await channel.stop()


@pytest.mark.asyncio
async def test_lan_bidirectional_concurrent_exchange() -> None:
    left = LanDirectChannel(credential="cred")
    right = LanDirectChannel(credential="cred")
    left_inbox: list[bytes] = []
    right_inbox: list[bytes] = []

    async def on_left(encoded: bytes) -> None:
        left_inbox.append(encoded)

    async def on_right(encoded: bytes) -> None:
        right_inbox.append(encoded)

    left.register_receiver(on_left)
    right.register_receiver(on_right)
    port_l = await left.start()
    port_r = await right.start()
    left.set_peer("right", "127.0.0.1", port_r)
    right.set_peer("left", "127.0.0.1", port_l)
    await asyncio.gather(
        left.send("right", b"L->R-1"),
        right.send("left", b"R->L-1"),
        left.send("right", b"L->R-2"),
        right.send("left", b"R->L-2"),
    )
    deadline = asyncio.get_running_loop().time() + 2.0
    while asyncio.get_running_loop().time() < deadline:
        if len(left_inbox) == 2 and len(right_inbox) == 2:
            break
        await asyncio.sleep(0.02)
    assert sorted(left_inbox) == [b"R->L-1", b"R->L-2"]
    assert sorted(right_inbox) == [b"L->R-1", b"L->R-2"]
    await left.stop()
    # Disruption: peer stopped before send.
    from deepiri_zepgpu.training.transport import DirectUnavailable

    with pytest.raises(DirectUnavailable, match="connect failed"):
        await right.send("left", b"after-stop")
    await right.stop()


@pytest.mark.asyncio
async def test_lan_pair_missing_route() -> None:
    from deepiri_zepgpu.training.lan import LanPairDirectChannel
    from deepiri_zepgpu.training.transport import DirectUnavailable

    only = LanDirectChannel(credential="cred")

    async def _recv(_encoded: bytes) -> None:
        return None

    pair = LanPairDirectChannel(channels={"a": only})
    with pytest.raises(DirectUnavailable, match="no LAN channel"):
        pair.register("missing", _recv)
    with pytest.raises(DirectUnavailable, match="no LAN route"):
        await pair.send("nobody", b"x")
    await only.stop()


@pytest.mark.asyncio
async def test_lan_pair_sync_roundtrip() -> None:
    import uuid

    from deepiri_zepgpu.training.lan import LanDirectChannel, LanPairDirectChannel

    room, run = str(uuid.uuid4()), str(uuid.uuid4())
    w0, w1 = str(uuid.uuid4()), str(uuid.uuid4())
    left_lan = LanDirectChannel(credential="lan-sync-cred")
    right_lan = LanDirectChannel(credential="lan-sync-cred")
    port0 = await left_lan.start()
    port1 = await right_lan.start()
    left_lan.set_peer(w1, "127.0.0.1", port1)
    right_lan.set_peer(w0, "127.0.0.1", port0)
    pair = LanPairDirectChannel(channels={w0: left_lan, w1: right_lan})
    store = BinaryRelayStore()
    manager = TransferManager(direct=pair, relay=store, chunk_size=1024)
    compression = CompressionConfig(backend=CompressorBackend.ZEP, top_k=8, chunk_size=32)
    left = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w0,
        peer_worker_id=w1,
        transfer_manager=manager,
        compression=compression,
    )
    right = SyncOrchestrator.from_compression_config(
        room_id=room,
        run_id=run,
        worker_id=w1,
        peer_worker_id=w0,
        transfer_manager=manager,
        compression=compression,
    )

    async def recv0(encoded: bytes) -> None:
        left.receive_encoded(encoded)

    async def recv1(encoded: bytes) -> None:
        right.receive_encoded(encoded)

    pair.register(w0, recv0)
    pair.register(w1, recv1)
    d0 = {"a": np.ones(64, dtype=np.float32)}
    d1 = {"a": np.full(64, 5.0, dtype=np.float32)}
    r0, r1 = await asyncio.gather(left.sync_round(1, d0), right.sync_round(1, d1))
    assert r0.path == "direct"
    assert np.allclose(r0.averaged["a"], r1.averaged["a"])
    await left_lan.stop()
    await right_lan.stop()


@pytest.mark.asyncio
async def test_process_runtime_cleanup() -> None:
    runtime = TrainingRuntime(trust_policy=ImageTrustPolicy({"zepgpu-training:local"}))
    spec = TrainingWorkloadSpec(
        image="zepgpu-training:local",
        command=["python", "-c", "import time; time.sleep(30)"],
    )
    handle = await runtime.start_process(spec)
    assert handle.work_dir is not None and handle.work_dir.exists()
    await runtime.cleanup(handle)
    assert not handle.work_dir.exists()
    assert runtime.list_active() == []


def test_two_worker_wan_smoke_cpu(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("peft")
    from deepiri_zepgpu.training.config import Precision
    from deepiri_zepgpu.training.distributed_runner import run_two_worker_training

    model_name = "hf-internal-testing/tiny-random-gpt2"
    try:
        from transformers import AutoTokenizer

        try:
            AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        except Exception:
            AutoTokenizer.from_pretrained(model_name)
    except Exception as exc:
        pytest.skip(f"tiny model unavailable offline/online: {exc}")

    config = TrainingRunConfig(
        schema_version=2,
        run_name="wan-smoke",
        model_name=model_name,
        device="cpu",
        precision=Precision.FP32,
        smoke_run=True,
        gradient_checkpointing=False,
        output_dir=tmp_path / "wan",
        distributed=DistributedTrainingConfig(
            enabled=True,
            local_steps_per_round=1,
            max_rounds=2,
            compression=CompressionConfig(backend=CompressorBackend.ZEP),
        ),
    )
    try:
        left, right, bundle = run_two_worker_training(config)
    except Exception as exc:
        # Sandbox/proxy or missing cache should skip rather than fail CI hard.
        message = str(exc).lower()
        if any(
            token in message for token in ("proxy", "403", "huggingface", "connection", "timed out")
        ):
            pytest.skip(f"WAN smoke requires model download/cache: {exc}")
        raise
    assert_catastrophic_quality(left)
    assert_catastrophic_quality(right)
    assert left.compressed_bytes > 0
    assert left.path_type in {"direct", "mixed", "relay"}
    assert bundle["naive"]["bytes_per_round"] >= 0
    assert math.isfinite(left.final_loss or 0.0)
    _ = torch
