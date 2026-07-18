"""Proof-of-authority validation for compute ledger blocks and transactions."""

from __future__ import annotations

from deepiri_zepgpu.compute_ledger.block import ComputeBlock
from deepiri_zepgpu.compute_ledger.hashing import canonical_json
from deepiri_zepgpu.compute_ledger.keys import verify_signature
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


def validate_block(
    block: ComputeBlock,
    *,
    authorized_validators: set[str],
    expected_previous_hash: str | None = None,
    expected_height: int | None = None,
    require_tx_signatures: bool = True,
) -> None:
    """Validate block linkage, PoA validator signature, and contained txs."""
    if expected_height is not None and block.height != expected_height:
        raise LedgerValidationError(
            f"Unexpected block height: got {block.height}, expected {expected_height}"
        )
    if expected_previous_hash is not None and block.previous_hash != expected_previous_hash:
        raise LedgerValidationError("previous_hash does not match tip")

    if block.validator not in authorized_validators:
        raise LedgerValidationError("Block validator is not authorized")

    expected_root = block.compute_transactions_root()
    if block.transactions_root != expected_root:
        raise LedgerValidationError("transactions_root mismatch")

    expected_hash = block.compute_hash()
    if block.hash != expected_hash:
        raise LedgerValidationError("Block hash mismatch")

    if not block.validator_signature:
        raise LedgerValidationError("Block validator signature required")
    if not verify_signature(block.validator, block.hash, block.validator_signature):
        raise LedgerValidationError("Invalid block validator signature")

    for tx in block.transactions:
        validate_transaction(tx, require_signature=require_tx_signatures)
