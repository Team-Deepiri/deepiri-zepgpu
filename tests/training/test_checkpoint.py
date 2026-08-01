from pathlib import Path

from deepiri_zepgpu.training.checkpoint import CheckpointMetadata, make_checkpoint_metadata


def test_checkpoint_metadata_roundtrip_and_resume_state(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint-7"
    metadata = make_checkpoint_metadata(
        run_id="run-1",
        step=7,
        directory=checkpoint,
        config={"model": "tiny", "access_token": "must-not-leak"},
    )
    metadata.save(checkpoint)
    loaded = CheckpointMetadata.load(checkpoint)
    assert loaded.step == 7
    assert loaded.run_id == "run-1"
    assert loaded.adapter_ref.endswith("adapter")
    assert loaded.optimizer_ref.endswith("optimizer.pt")
    assert loaded.config["access_token"] == "[REDACTED]"
