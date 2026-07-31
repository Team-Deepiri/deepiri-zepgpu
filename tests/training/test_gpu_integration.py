import os
from pathlib import Path

import pytest

from deepiri_zepgpu.training.config import TrainingRunConfig


@pytest.mark.gpu
@pytest.mark.skipif(os.getenv("ZEPGPU_RUN_GPU_TESTS") != "1", reason="optional CUDA test")
def test_tiny_lora_gpu_smoke(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("peft")
    if not torch.cuda.is_available():
        pytest.skip("CUDA is unavailable")
    from deepiri_zepgpu.training.runner import run_training

    config = TrainingRunConfig(
        smoke_run=True, checkpoint_every_steps=1, output_dir=tmp_path / "run"
    )
    metrics = run_training(config)
    assert metrics.artifact_ref
    assert Path(metrics.artifact_ref).is_dir()
    assert metrics.communication_compute_ratio == 0
    assert metrics.peak_allocated_vram_bytes > 0

    resumed = run_training(
        TrainingRunConfig(
            smoke_run=True,
            checkpoint_every_steps=1,
            output_dir=tmp_path / "run",
            resume_from=tmp_path / "run" / "checkpoint-1",
        )
    )
    assert resumed.run_id == metrics.run_id
    assert [step.step for step in resumed.steps] == [2]
