"""Phase 19 recovery verify: corrupt checkpoint rejection + late-joiner bootstrap."""

from __future__ import annotations

import argparse
import json
import tempfile
import uuid
from pathlib import Path

from deepiri_zepgpu.training.checkpoint import make_phase18_checkpoint_metadata
from deepiri_zepgpu.training.recovery import (
    CheckpointCorruptionError,
    bootstrap_late_joiner_state,
    load_verified_checkpoint,
    write_checkpoint_integrity,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=None)
    args = parser.parse_args()

    checks: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="zepgpu-p19-recovery-") as tmp:
        root = Path(tmp)
        good = root / "good"
        meta = make_phase18_checkpoint_metadata(
            run_id=str(uuid.uuid4()),
            step=5,
            outer_round=2,
            directory=good,
            config={"h": 10},
            model_state={"layer": {"ok": True}},
            outer_optimizer_state={"mu": 0.9},
            active_membership=["w0", "w1"],
            compression_config={"backend": "zep"},
            placement={"status": "capable"},
            island_ids=["island-a"],
        )
        write_checkpoint_integrity(good, meta)
        loaded = load_verified_checkpoint(good)
        assert loaded.outer_round == 2
        checks["load_ok"] = "pass"

        boot = bootstrap_late_joiner_state(loaded, worker_id="w2")
        assert "w2" in boot["active_membership"]
        checks["late_join"] = "pass"

        bad = root / "bad"
        bad.mkdir()
        (bad / "checkpoint.json").write_text("{", encoding="utf-8")
        (bad / "checkpoint.sha256").write_text("deadbeef\n", encoding="utf-8")
        try:
            load_verified_checkpoint(bad)
            checks["corrupt_reject"] = "fail"
        except CheckpointCorruptionError:
            checks["corrupt_reject"] = "pass"

        truncated = root / "truncated"
        write_checkpoint_integrity(truncated, meta)
        (truncated / "checkpoint.json").write_text("", encoding="utf-8")
        try:
            load_verified_checkpoint(truncated)
            checks["empty_reject"] = "fail"
        except CheckpointCorruptionError:
            checks["empty_reject"] = "pass"

    artifact = {"checks": checks, "ok": all(value == "pass" for value in checks.values())}
    text = json.dumps(artifact, indent=2)
    print(text)
    if args.artifact:
        args.artifact.write_text(text + "\n", encoding="utf-8")
    if not artifact["ok"]:
        print("[FAIL] Phase 19 recovery verify")
        return 1
    print("[PASS] Phase 19 recovery verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
