"""Explicitly gated Phase 18 hardware preflight."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deepiri_zepgpu.database.models.training_run import (
    TrainingGpuReservation,
    TrainingReservationState,
)
from deepiri_zepgpu.database.models.user import User, UserRole
from deepiri_zepgpu.database.models.vpn_models import (
    GpuShare,
    GpuShareState,
    Peer,
    PeerOnlineStatus,
    VpnNetwork,
)
from deepiri_zepgpu.database.repositories.training_run_repository import TrainingRunRepository
from deepiri_zepgpu.training.config import (
    DistributedStrategy,
    NetworkScope,
    Phase18TrainingConfig,
    TrainingRunConfig,
)
from deepiri_zepgpu.training.launcher import DistributedTrainingLauncher
from deepiri_zepgpu.training.placement import PlacementPlanner, PlacementStatus
from deepiri_zepgpu.training.topology import GpuCandidate, ProviderCandidate


@pytest.mark.gpu
def test_phase18_same_host_two_gpu_preflight() -> None:
    if os.getenv("ZEPGPU_PHASE18_GPU_TEST") != "1":
        pytest.skip("set ZEPGPU_PHASE18_GPU_TEST=1 for Phase 18 hardware checks")
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available() or torch.cuda.device_count() < 2:
        pytest.skip("Phase 18 FSDP2 smoke requires at least two CUDA GPUs")
    assert torch.distributed.is_available()
    from torch.distributed._composable.fsdp import fully_shard

    assert callable(fully_shard)


@pytest.mark.gpu
@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("ZEPGPU_PHASE18_GPU_TEST") != "1",
    reason="set ZEPGPU_PHASE18_GPU_TEST=1 for Phase 18 hardware checks",
)
@pytest.mark.asyncio
async def test_zepgpu_fsdp2_manifest_reservation_launcher_runtime_and_cleanup(
    integration_engine, tmp_path: Path
) -> None:
    """Hardware gate for the ZepGPU path, not merely raw PyTorch FSDP2."""

    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available() or torch.cuda.device_count() < 2:
        pytest.skip("Phase 18 FSDP2 integration requires at least two CUDA GPUs")
    factory = async_sessionmaker(integration_engine, expire_on_commit=False, class_=AsyncSession)
    now = datetime.now(UTC)
    user_id, room_id, provider_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    share_ids = [uuid.uuid4(), uuid.uuid4()]
    user = User(
        id=user_id,
        username=f"phase18-gpu-{uuid.uuid4().hex[:8]}",
        email=f"phase18-gpu-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="unused",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    room = VpnNetwork(id=room_id, name="phase18-gpu", host_id=user_id)
    peer = Peer(
        id=provider_id,
        user_id=user_id,
        vpn_network_id=room_id,
        wireguard_public_key=f"phase18-gpu-{provider_id}",
        vpn_ip="10.8.0.2",
        last_seen=now,
        online_status=PeerOnlineStatus.ONLINE,
        is_gpu_host=True,
        health_state="healthy",
    )
    shares = [
        GpuShare(
            id=share_id,
            peer_id=provider_id,
            vpn_network_id=room_id,
            device_index=index,
            total_memory_mb=int(torch.cuda.get_device_properties(index).total_memory // 2**20),
            available_memory_mb=int(torch.cuda.get_device_properties(index).total_memory // 2**20),
            state=GpuShareState.IDLE,
            is_active=True,
        )
        for index, share_id in enumerate(share_ids)
    ]
    config = TrainingRunConfig(
        phase18=Phase18TrainingConfig(
            strategy=DistributedStrategy.FSDP2,
            requested_node_count=1,
            gpus_per_node=2,
            total_gpus=2,
            min_k=1,
            network_scope=NetworkScope.SAME_HOST,
        )
    )
    runtime_version = str(torch.__version__).split("+", 1)[0]
    nccl_version = ".".join(str(item) for item in torch.cuda.nccl.version())
    candidate = ProviderCandidate(
        provider_id=str(provider_id),
        room_id=str(room_id),
        online=True,
        health_state="healthy",
        last_seen=now,
        capabilities_reported_at=now,
        capabilities={
            "runtime": {
                "cuda_version": str(torch.version.cuda),
                "pytorch_version": runtime_version,
                "nccl_version": nccl_version,
                "fsdp_available": True,
            },
            "topology": {"p2p_access": True, "nvlink": False},
        },
        gpu_shares=[
            GpuCandidate(
                gpu_share_id=str(share.id),
                provider_id=str(provider_id),
                room_id=str(room_id),
                device_index=share.device_index,
                total_memory_mb=share.total_memory_mb,
                available_memory_mb=share.available_memory_mb,
            )
            for share in shares
        ],
    )
    plan = PlacementPlanner(now=now).plan(
        room_id=str(room_id), config=config, providers=[candidate]
    )
    assert plan.status == PlacementStatus.CAPABLE
    async with factory() as session:
        session.add_all([user, room, peer, *shares])
        await session.flush()
        run = await TrainingRunRepository(session).create(
            room_id=str(room_id),
            user_id=str(user_id),
            config=config.to_public_dict(),
            provider_ids=[str(provider_id)],
            placement_plan=plan.model_dump(mode="json"),
        )
        launched = await DistributedTrainingLauncher(
            session, credential_secret=b"phase18-hardware-gate-secret!!"
        ).launch(run, reservation_owner=str(user_id))
        assert len(launched.reservation_ids) == 2
        manifest = {
            "config": config.to_public_dict(),
            "placement_plan": plan.model_dump(mode="json"),
            "processes": [asdict(item) for item in launched.workers[0].processes],
            "reservation_ids": launched.reservation_ids,
        }
        manifest_path = tmp_path / "phase18-fsdp2-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        run_id = str(run.id)
        await session.commit()

    environment = os.environ.copy()
    environment["ZEPGPU_PHASE18_GPU_TEST"] = "1"
    script = Path(__file__).resolve().parents[2] / "scripts" / "verify_phase18_fsdp2.py"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "torch.distributed.run",
            "--nproc_per_node=2",
            str(script),
            "--mode",
            "fsdp2",
            "--hidden-size",
            "256",
            "--layers",
            "2",
            "--zepgpu-manifest",
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env=environment,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    results = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    assert len(results) == 2
    assert {item["rank"] for item in results} == {0, 1}
    assert all(len(item["zepgpu_reservation_ids"]) == 2 for item in results)

    async with factory() as session:
        run = await TrainingRunRepository(session).get(run_id)
        assert run is not None
        await DistributedTrainingLauncher(
            session, credential_secret=b"phase18-hardware-gate-secret!!"
        ).cancel(run, reason="hardware acceptance completed")
        reservations = list(
            (
                await session.execute(
                    select(TrainingGpuReservation).where(TrainingGpuReservation.run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
        assert {item.state for item in reservations} == {TrainingReservationState.RELEASED}
