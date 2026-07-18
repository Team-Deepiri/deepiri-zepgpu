"""Golden cryptographic vectors — pin hashing / Merkle / PoA invariants forever."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deepiri_zepgpu.compute_ledger.block import GENESIS_PREV_HASH, ComputeBlock
from deepiri_zepgpu.compute_ledger.hashing import canonical_json, sha256_hex
from deepiri_zepgpu.compute_ledger.keys import derive_keypair_from_seed, sign_message, verify_signature
from deepiri_zepgpu.compute_ledger.merkle import merkle_proof, merkle_root, verify_merkle_proof
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction, TxType

# Stable seed — never change without bumping golden fixture version.
GOLDEN_SEED = "zepgpu-revolution-golden-v1"
GOLDEN_FIXTURE_VERSION = 1


def build_golden_payload() -> dict[str, Any]:
    """Compute deterministic golden vectors from fixed seeds and payloads."""
    priv, pub = derive_keypair_from_seed(GOLDEN_SEED)
    message = b"zepgpu-attest-v1"
    signature = sign_message(priv, message)

    leaves = [sha256_hex(f"leaf-{i}") for i in range(5)]
    root = merkle_root(leaves)
    proofs = []
    for i in range(5):
        proof = merkle_proof(leaves, i)
        proofs.append(
            {
                "index": i,
                "leaf": leaves[i],
                "root": proof.root,
                "valid": verify_merkle_proof(proof),
                "step_count": len(proof.steps),
            }
        )

    tx = ComputeTransaction(
        id="00000000-0000-4000-8000-000000000001",
        tx_type=TxType.JOB_COMPLETED,
        sender=pub,
        nonce=0,
        timestamp="2026-01-01T00:00:00+00:00",
        payload={
            "task_id": "golden-task",
            "provider_account": "provider-alpha",
            "consumer_account": "consumer-beta",
            "gpu_seconds": 42.0,
        },
    )
    tx.signature = sign_message(priv, canonical_json(tx.signing_payload()))
    tx_hash = tx.compute_hash()

    block = ComputeBlock(
        id="00000000-0000-4000-8000-0000000000aa",
        height=1,
        previous_hash=GENESIS_PREV_HASH,
        timestamp="2026-01-01T00:00:01+00:00",
        transactions=[tx],
        validator=pub,
    )
    block.transactions_root = block.compute_transactions_root()
    block.state_root = sha256_hex("golden-state")
    block.hash = block.compute_hash()
    block.validator_signature = sign_message(priv, block.hash)
    block.ensure_proposer_approval()

    return {
        "version": GOLDEN_FIXTURE_VERSION,
        "seed": GOLDEN_SEED,
        "canonical_json": canonical_json({"b": 2, "a": 1}).decode("utf-8"),
        "sha256_hello": sha256_hex("hello"),
        "keypair": {"public_key": pub},
        "signature": {
            "message": message.decode("utf-8"),
            "signature": signature,
            "verifies": verify_signature(pub, message, signature),
            "rejects_tamper": not verify_signature(pub, b"tampered", signature),
        },
        "merkle": {
            "leaves": leaves,
            "root": root,
            "proofs_valid": all(p["valid"] for p in proofs),
            "proof_count": len(proofs),
        },
        "transaction": {
            "hash": tx_hash,
            "tx_type": tx.tx_type.value,
            "signature_valid": verify_signature(
                pub, canonical_json(tx.signing_payload()), tx.signature
            ),
        },
        "block": {
            "hash": block.hash,
            "transactions_root": block.transactions_root,
            "height": block.height,
            "approvals": len(block.approvals),
        },
    }


def default_fixture_path() -> Path:
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ledger_golden_vectors.json"


def write_golden_fixture(path: Path | None = None) -> Path:
    target = path or default_fixture_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_golden_payload()
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return target


def verify_golden_fixture(path: Path | None = None) -> dict[str, Any]:
    """Compare live golden computation against committed fixture."""
    target = path or default_fixture_path()
    if not target.exists():
        return {"valid": False, "error": f"missing fixture: {target}"}
    expected = json.loads(target.read_text())
    actual = build_golden_payload()
    mismatches: list[str] = []

    def _walk(prefix: str, a: Any, b: Any) -> None:
        if type(a) != type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
            mismatches.append(f"{prefix}: type {type(a).__name__} != {type(b).__name__}")
            return
        if isinstance(a, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a:
                    mismatches.append(f"{prefix}.{key}: missing in actual")
                elif key not in b:
                    mismatches.append(f"{prefix}.{key}: missing in fixture")
                else:
                    _walk(f"{prefix}.{key}", a[key], b[key])
        elif isinstance(a, list):
            if len(a) != len(b):
                mismatches.append(f"{prefix}: len {len(a)} != {len(b)}")
            else:
                for i, (x, y) in enumerate(zip(a, b)):
                    _walk(f"{prefix}[{i}]", x, y)
        elif a != b:
            mismatches.append(f"{prefix}: {a!r} != {b!r}")

    # Compare stable subset (ignore proof step structure details if present)
    for key in (
        "version",
        "seed",
        "canonical_json",
        "sha256_hello",
        "keypair",
        "signature",
        "merkle",
        "transaction",
        "block",
    ):
        _walk(key, actual.get(key), expected.get(key))

    return {
        "valid": len(mismatches) == 0,
        "fixture": str(target),
        "mismatches": mismatches,
        "actual_block_hash": actual["block"]["hash"],
        "expected_block_hash": expected.get("block", {}).get("hash"),
    }
