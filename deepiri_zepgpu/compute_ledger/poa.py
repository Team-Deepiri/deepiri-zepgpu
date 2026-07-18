"""Proof-of-authority validation for compute ledger blocks and transactions."""

from __future__ import annotations

from deepiri_zepgpu.compute_ledger.block import ComputeBlock, ValidatorApproval
from deepiri_zepgpu.compute_ledger.hashing import canonical_json
from deepiri_zepgpu.compute_ledger.keys import verify_signature
from deepiri_zepgpu.compute_ledger.merkle import merkle_root
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction


class LedgerValidationError(ValueError):
    """Raised when a transaction or block fails validation."""


def validate_transaction(
    tx: ComputeTransaction,
    *,
    require_signature: bool = True,
) -> None:
    """Validate transaction structure and optional sender signature."""
    if not tx.id or not tx.sender:
        raise LedgerValidationError("Transaction missing id or sender")
    if tx.nonce < 0:
        raise LedgerValidationError("Transaction nonce must be non-negative")
    if require_signature:
        if not tx.signature:
            raise LedgerValidationError("Transaction signature required")
        message = canonical_json(tx.signing_payload())
        if not verify_signature(tx.sender, message, tx.signature):
            raise LedgerValidationError("Invalid transaction signature")


def validate_approvals(
    block: ComputeBlock,
    *,
    authorized_validators: set[str],
    quorum_threshold: int,
) -> None:
    """Validate PoA approvals meet quorum."""
    if quorum_threshold < 1:
        raise LedgerValidationError("quorum_threshold must be >= 1")

    block.ensure_proposer_approval()
    seen: set[str] = set()
    for approval in block.approvals:
        if approval.validator not in authorized_validators:
            raise LedgerValidationError(f"Unauthorized approval from {approval.validator}")
        if approval.validator in seen:
            raise LedgerValidationError(f"Duplicate approval from {approval.validator}")
        if not verify_signature(approval.validator, block.hash, approval.signature):
            raise LedgerValidationError(f"Invalid approval signature from {approval.validator}")
        seen.add(approval.validator)

    if block.validator not in seen:
        raise LedgerValidationError("Proposer approval missing")

    if len(seen) < quorum_threshold:
        raise LedgerValidationError(
            f"Quorum not met: have {len(seen)}, need {quorum_threshold}"
        )


def validate_block(
    block: ComputeBlock,
    *,
    authorized_validators: set[str],
    expected_previous_hash: str | None = None,
    expected_height: int | None = None,
    require_tx_signatures: bool = True,
    quorum_threshold: int = 1,
    require_quorum: bool = True,
) -> None:
    """Validate block linkage, Merkle root, PoA signatures, and contained txs."""
    if expected_height is not None and block.height != expected_height:
        raise LedgerValidationError(
            f"Unexpected block height: got {block.height}, expected {expected_height}"
        )
    if expected_previous_hash is not None and block.previous_hash != expected_previous_hash:
        raise LedgerValidationError("previous_hash does not match tip")

    if block.validator not in authorized_validators:
        raise LedgerValidationError("Block validator is not authorized")

    expected_root = merkle_root(block.leaf_hashes())
    if block.transactions_root != expected_root:
        raise LedgerValidationError("transactions_root mismatch")

    expected_hash = block.compute_hash()
    if block.hash != expected_hash:
        raise LedgerValidationError("Block hash mismatch")

    if not block.validator_signature:
        raise LedgerValidationError("Block validator signature required")
    if not verify_signature(block.validator, block.hash, block.validator_signature):
        raise LedgerValidationError("Invalid block validator signature")

    if require_quorum:
        validate_approvals(
            block,
            authorized_validators=authorized_validators,
            quorum_threshold=quorum_threshold,
        )
    elif block.finalized:
        validate_approvals(
            block,
            authorized_validators=authorized_validators,
            quorum_threshold=quorum_threshold,
        )

    for tx in block.transactions:
        validate_transaction(tx, require_signature=require_tx_signatures)


def add_approval(
    block: ComputeBlock,
    *,
    validator_public_key: str,
    signature: str,
    authorized_validators: set[str],
) -> ValidatorApproval:
    """Add a validator approval to a block (mutates approvals)."""
    if validator_public_key not in authorized_validators:
        raise LedgerValidationError("Validator is not authorized")
    if not verify_signature(validator_public_key, block.hash, signature):
        raise LedgerValidationError("Invalid approval signature")
    for existing in block.approvals:
        if existing.validator == validator_public_key:
            raise LedgerValidationError("Validator already approved this block")
    approval = ValidatorApproval(validator=validator_public_key, signature=signature)
    block.approvals.append(approval)
    return approval
