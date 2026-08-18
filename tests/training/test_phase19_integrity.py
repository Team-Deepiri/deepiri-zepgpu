"""Phase 19.2–19.3 integrity and durable checkpoint tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepiri_zepgpu.training.checkpoint import make_phase18_checkpoint_metadata
from deepiri_zepgpu.training.integrity import (
    FileReplayGuard,
    NeutralOuterUpdate,
    ReplayGuard,
    UpdateIntegrityError,
    accept_outer_update,
    payload_digest,
    sign_update,
)
from deepiri_zepgpu.training.recovery import (
    CheckpointCorruptionError,
    bootstrap_late_joiner_state,
    load_verified_checkpoint,
    retention_candidates,
    write_checkpoint_integrity,
)


@pytest.mark.unit
def test_neutral_update_mac_and_checksum() -> None:
    payload = b"adapter-bytes"
    update = NeutralOuterUpdate(
        model_revision="base-v1",
        parameter_names=["lora_A"],
        shapes=[[4, 4]],
        dtype="f32",
        quantization="none",
        round=3,
        worker_id="w0",
        run_id="run-1",
        room_id="room-1",
        payload_sha256=payload_digest(payload),
    )
    mac = sign_update(update, room_mac_key="room-secret")
    guard = ReplayGuard()
    accepted = accept_outer_update(
        update, payload, room_mac_key="room-secret", mac_hex=mac, replay_guard=guard
    )
    assert accepted.round == 3
    # Idempotent identical replay allowed
    accept_outer_update(
        update, payload, room_mac_key="room-secret", mac_hex=mac, replay_guard=guard
    )


@pytest.mark.unit
def test_neutral_update_rejects_bad_mac_checksum_replay() -> None:
    payload = b"adapter-bytes"
    update = NeutralOuterUpdate(
        model_revision="base-v1",
        parameter_names=["lora_A"],
        shapes=[[2, 2]],
        dtype="f32",
        round=1,
        worker_id="w0",
        run_id="run-1",
        room_id="room-1",
        payload_sha256=payload_digest(payload),
    )
    mac = sign_update(update, room_mac_key="room-secret")
    guard = ReplayGuard()
    with pytest.raises(UpdateIntegrityError, match="MAC"):
        accept_outer_update(update, payload, room_mac_key="wrong", mac_hex=mac, replay_guard=guard)
    with pytest.raises(UpdateIntegrityError, match="checksum"):
        accept_outer_update(
            update, b"other", room_mac_key="room-secret", mac_hex=mac, replay_guard=guard
        )
    accept_outer_update(
        update, payload, room_mac_key="room-secret", mac_hex=mac, replay_guard=guard
    )
    with pytest.raises(UpdateIntegrityError, match="conflicting replay"):
        guard.check(update, mac_hex="0" * 64)


@pytest.mark.unit
def test_durable_checkpoint_roundtrip_and_corruption(tmp_path: Path) -> None:
    directory = tmp_path / "ckpt-1"
    meta = make_phase18_checkpoint_metadata(
        run_id="run-1",
        step=10,
        outer_round=2,
        directory=directory,
        config={"lr": 0.1},
        model_state={"w": {"shape": [1]}},
        outer_optimizer_state={"m": 1},
        active_membership=["w0"],
        compression_config={"backend": "zep"},
        placement={"status": "capable"},
        island_ids=["island-1"],
        artifact_refs=[{"kind": "adapter", "uri": "file://a"}],
    )
    write_checkpoint_integrity(directory, meta)
    loaded = load_verified_checkpoint(directory)
    assert loaded.outer_round == 2
    assert loaded.active_membership == ["w0"]

    # Corrupt payload
    (directory / "checkpoint.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(CheckpointCorruptionError):
        load_verified_checkpoint(directory)


@pytest.mark.unit
def test_checkpoint_missing_sidecar_and_late_join(tmp_path: Path) -> None:
    directory = tmp_path / "ckpt-2"
    meta = make_phase18_checkpoint_metadata(
        run_id="run-2",
        step=1,
        outer_round=0,
        directory=directory,
        config={},
        model_state={},
        outer_optimizer_state={},
        active_membership=["w0"],
        compression_config={},
        placement={},
        island_ids=[],
    )
    meta.save(directory)
    with pytest.raises(CheckpointCorruptionError, match="sidecar"):
        load_verified_checkpoint(directory)

    write_checkpoint_integrity(directory, meta)
    boot = bootstrap_late_joiner_state(meta, worker_id="w1")
    assert "w1" in boot["active_membership"]
    assert boot["outer_round"] == 0


@pytest.mark.unit
def test_retention_candidates(tmp_path: Path) -> None:
    root = tmp_path / "ckpts"
    root.mkdir()
    for name in ("a", "b", "c"):
        path = root / name
        path.mkdir()
        (path / "marker").write_text(name, encoding="utf-8")
    victims = retention_candidates(root, keep_last=2)
    assert len(victims) == 1


@pytest.mark.unit
def test_file_replay_guard_survives_restart(tmp_path: Path) -> None:
    payload = b"adapter-bytes"
    update = NeutralOuterUpdate(
        model_revision="base-v1",
        parameter_names=["lora_A"],
        shapes=[[2, 2]],
        dtype="f32",
        round=1,
        worker_id="w0",
        run_id="run-1",
        room_id="room-1",
        payload_sha256=payload_digest(payload),
    )
    mac = sign_update(update, room_mac_key="room-secret")
    path = tmp_path / "replay.json"
    first = FileReplayGuard(path)
    accept_outer_update(
        update, payload, room_mac_key="room-secret", mac_hex=mac, replay_guard=first
    )
    second = FileReplayGuard(path)
    accept_outer_update(
        update, payload, room_mac_key="room-secret", mac_hex=mac, replay_guard=second
    )
    with pytest.raises(UpdateIntegrityError, match="conflicting replay"):
        second.check(update, mac_hex="0" * 64)
