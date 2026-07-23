"""Light-client header sync and offline verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from deepiri_zepgpu.compute_ledger.block import GENESIS_PREV_HASH, ComputeBlock
from deepiri_zepgpu.compute_ledger.keys import verify_signature
from deepiri_zepgpu.compute_ledger.merkle import MerkleProof, verify_merkle_proof
from deepiri_zepgpu.compute_ledger.poa import LedgerValidationError


@dataclass
class BlockHeader:
    """Compact block header for light clients (no transaction bodies)."""

    height: int
    hash: str
    previous_hash: str
    timestamp: str
    transactions_root: str
    state_root: str
    validator: str
    validator_signature: str
    approvals: list[dict[str, str]] = field(default_factory=list)
    finalized: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_block(cls, block: ComputeBlock) -> BlockHeader:
        approvals: list[dict[str, str]] = [
            approval.to_dict() if hasattr(approval, "to_dict") else approval  # type: ignore[misc]
            for approval in block.approvals
        ]
        return cls(
            height=block.height,
            hash=block.hash,
            previous_hash=block.previous_hash,
            timestamp=block.timestamp,
            transactions_root=block.transactions_root,
            state_root=block.state_root,
            validator=block.validator,
            validator_signature=block.validator_signature,
            approvals=approvals,
            finalized=block.finalized,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BlockHeader:
        return cls(
            height=int(data["height"]),
            hash=data["hash"],
            previous_hash=data["previous_hash"],
            timestamp=data["timestamp"],
            transactions_root=data["transactions_root"],
            state_root=data["state_root"],
            validator=data["validator"],
            validator_signature=data["validator_signature"],
            approvals=list(data.get("approvals") or []),
            finalized=bool(data.get("finalized", True)),
        )


def verify_header_signatures(
    header: BlockHeader,
    *,
    authorized_validators: set[str],
    quorum_threshold: int = 1,
) -> None:
    """Validate proposer + approval signatures on a header."""
    if header.validator not in authorized_validators:
        raise LedgerValidationError("Header validator is not authorized")
    if not verify_signature(header.validator, header.hash, header.validator_signature):
        raise LedgerValidationError("Invalid header proposer signature")

    approvals = list(header.approvals)
    if not any(a.get("validator") == header.validator for a in approvals):
        approvals.append({"validator": header.validator, "signature": header.validator_signature})

    seen: set[str] = set()
    for approval in approvals:
        v = approval.get("validator") or ""
        sig = approval.get("signature") or ""
        if v not in authorized_validators:
            raise LedgerValidationError(f"Unauthorized header approval from {v}")
        if v in seen:
            raise LedgerValidationError(f"Duplicate header approval from {v}")
        if not verify_signature(v, header.hash, sig):
            raise LedgerValidationError(f"Invalid header approval from {v}")
        seen.add(v)

    if header.finalized and len(seen) < quorum_threshold:
        raise LedgerValidationError(
            f"Header quorum not met: have {len(seen)}, need {quorum_threshold}"
        )


def verify_header_chain(
    headers: list[BlockHeader],
    *,
    authorized_validators: set[str],
    quorum_threshold: int = 1,
    expected_genesis_prev: str = GENESIS_PREV_HASH,
    from_height: int | None = None,
) -> dict[str, Any]:
    """Verify an ordered contiguous header chain (light-client sync)."""
    errors: list[str] = []
    if not headers:
        return {"valid": True, "headers": 0, "tip_hash": None, "tip_height": -1, "errors": []}

    headers = sorted(headers, key=lambda h: h.height)
    start = from_height if from_height is not None else headers[0].height
    prev_hash = expected_genesis_prev if start == 0 else None

    for i, header in enumerate(headers):
        expected_h = start + i
        if header.height != expected_h:
            errors.append(f"height gap: got {header.height}, expected {expected_h}")
        if prev_hash is not None and header.previous_hash != prev_hash:
            errors.append(f"height={header.height}: previous_hash mismatch")
        try:
            verify_header_signatures(
                header,
                authorized_validators=authorized_validators,
                quorum_threshold=quorum_threshold if header.finalized else 1,
            )
        except LedgerValidationError as exc:
            errors.append(f"height={header.height}: {exc}")
        prev_hash = header.hash

    tip = headers[-1]
    return {
        "valid": len(errors) == 0,
        "headers": len(headers),
        "tip_hash": tip.hash,
        "tip_height": tip.height,
        "tip_state_root": tip.state_root,
        "errors": errors,
    }


def verify_tx_inclusion(
    *,
    header: BlockHeader,
    proof: MerkleProof | dict[str, Any],
) -> bool:
    """Verify a transaction inclusion proof against a trusted header."""
    mp = proof if isinstance(proof, MerkleProof) else MerkleProof.from_dict(proof)
    if mp.root != header.transactions_root:
        return False
    return verify_merkle_proof(mp)
