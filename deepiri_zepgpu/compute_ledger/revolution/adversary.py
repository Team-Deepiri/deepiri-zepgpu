"""Adversarial probes — every attack must be rejected by PoA / bridge / verify."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from deepiri_zepgpu.compute_ledger.block import GENESIS_PREV_HASH, ComputeBlock
from deepiri_zepgpu.compute_ledger.hashing import canonical_json, sha256_hex
from deepiri_zepgpu.compute_ledger.keys import (
    derive_keypair_from_seed,
    generate_keypair,
    sign_message,
    verify_signature,
)
from deepiri_zepgpu.compute_ledger.merkle import merkle_root
from deepiri_zepgpu.compute_ledger.poa import (
    LedgerValidationError,
    add_approval,
    validate_block,
    validate_transaction,
)
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction, TxType


@dataclass
class AttackOutcome:
    name: str
    blocked: bool
    detail: str
    category: str = "adversarial"


@dataclass
class AdversaryReport:
    outcomes: list[AttackOutcome] = field(default_factory=list)

    @property
    def all_blocked(self) -> bool:
        return bool(self.outcomes) and all(o.blocked for o in self.outcomes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_blocked": self.all_blocked,
            "attack_count": len(self.outcomes),
            "blocked_count": sum(1 for o in self.outcomes if o.blocked),
            "outcomes": [o.__dict__ for o in self.outcomes],
        }


def _expect_blocked(name: str, category: str, fn: Callable[[], None]) -> AttackOutcome:
    try:
        fn()
        return AttackOutcome(
            name=name, blocked=False, detail="attack succeeded (BAD)", category=category
        )
    except (LedgerValidationError, ValueError, AssertionError) as exc:
        return AttackOutcome(name=name, blocked=True, detail=str(exc), category=category)


def _signed_tx(priv: str, pub: str, *, nonce: int = 0) -> ComputeTransaction:
    tx = ComputeTransaction(
        id="11111111-1111-4111-8111-111111111111",
        tx_type=TxType.JOB_COMPLETED,
        sender=pub,
        nonce=nonce,
        timestamp="2026-01-01T00:00:00+00:00",
        payload={
            "task_id": "adv",
            "provider_account": "p",
            "consumer_account": "c",
            "gpu_seconds": 1.0,
        },
    )
    tx.signature = sign_message(priv, canonical_json(tx.signing_payload()))
    return tx


def _sealed_block(priv: str, pub: str, txs: list[ComputeTransaction]) -> ComputeBlock:
    block = ComputeBlock(
        height=1,
        previous_hash=GENESIS_PREV_HASH,
        transactions=txs,
        validator=pub,
        timestamp="2026-01-01T00:00:01+00:00",
    )
    block.transactions_root = block.compute_transactions_root()
    block.state_root = sha256_hex("adv-state")
    block.hash = block.compute_hash()
    block.validator_signature = sign_message(priv, block.hash)
    block.ensure_proposer_approval()
    return block


def run_cryptographic_adversary_suite() -> AdversaryReport:
    """Pure in-memory attacks (no database)."""
    report = AdversaryReport()
    priv, pub = derive_keypair_from_seed("adversary-suite-validator")
    evil_priv, evil_pub = generate_keypair()
    tx = _signed_tx(priv, pub)
    block = _sealed_block(priv, pub, [tx])
    authorized = {pub}

    report.outcomes.append(
        _expect_blocked(
            "forged_transaction_signature",
            "crypto",
            lambda: validate_transaction(
                ComputeTransaction(
                    id=tx.id,
                    tx_type=tx.tx_type,
                    sender=tx.sender,
                    nonce=tx.nonce,
                    timestamp=tx.timestamp,
                    payload=tx.payload,
                    signature=sign_message(evil_priv, canonical_json(tx.signing_payload())),
                )
            ),
        )
    )

    report.outcomes.append(
        _expect_blocked(
            "tampered_transaction_payload",
            "crypto",
            lambda: validate_transaction(
                ComputeTransaction(
                    id=tx.id,
                    tx_type=tx.tx_type,
                    sender=tx.sender,
                    nonce=tx.nonce,
                    timestamp=tx.timestamp,
                    payload={**tx.payload, "gpu_seconds": 9999.0},
                    signature=tx.signature,
                )
            ),
        )
    )

    def _rogue_validator_block() -> None:
        rogue = _sealed_block(evil_priv, evil_pub, [tx])
        validate_block(
            rogue,
            authorized_validators=authorized,
            expected_previous_hash=GENESIS_PREV_HASH,
            expected_height=1,
            quorum_threshold=1,
        )

    report.outcomes.append(
        _expect_blocked("unauthorized_block_proposer", "poa", _rogue_validator_block)
    )

    def _broken_merkle() -> None:
        bad = ComputeBlock(
            height=block.height,
            previous_hash=block.previous_hash,
            transactions=list(block.transactions),
            validator=block.validator,
            timestamp=block.timestamp,
            transactions_root="0" * 64,
            state_root=block.state_root,
            hash=block.hash,
            validator_signature=block.validator_signature,
            approvals=list(block.approvals),
        )
        validate_block(
            bad,
            authorized_validators=authorized,
            expected_previous_hash=GENESIS_PREV_HASH,
            expected_height=1,
            quorum_threshold=1,
        )

    report.outcomes.append(
        _expect_blocked("transactions_root_mismatch", "integrity", _broken_merkle)
    )

    def _broken_hash_link() -> None:
        validate_block(
            block,
            authorized_validators=authorized,
            expected_previous_hash="f" * 64,
            expected_height=1,
            quorum_threshold=1,
        )

    report.outcomes.append(_expect_blocked("broken_hash_chain", "integrity", _broken_hash_link))

    def _forged_approval() -> None:
        add_approval(
            block,
            validator_public_key=evil_pub,
            signature=sign_message(evil_priv, block.hash),
            authorized_validators=authorized,
        )

    report.outcomes.append(_expect_blocked("unauthorized_approval", "poa", _forged_approval))

    def _quorum_not_met() -> None:
        solo = _sealed_block(priv, pub, [tx])
        validate_block(
            solo,
            authorized_validators={pub, evil_pub},
            expected_previous_hash=GENESIS_PREV_HASH,
            expected_height=1,
            quorum_threshold=2,
            require_quorum=True,
        )

    report.outcomes.append(_expect_blocked("quorum_threshold_not_met", "poa", _quorum_not_met))

    def _replay_signature_on_wrong_message() -> None:
        assert verify_signature(pub, b"other", tx.signature)

    report.outcomes.append(
        _expect_blocked(
            "signature_replay_on_wrong_message", "crypto", _replay_signature_on_wrong_message
        )
    )

    # Sanity: honest block must still validate
    validate_block(
        block,
        authorized_validators=authorized,
        expected_previous_hash=GENESIS_PREV_HASH,
        expected_height=1,
        quorum_threshold=1,
    )
    report.outcomes.append(
        AttackOutcome(
            name="honest_block_still_validates",
            blocked=True,
            detail="control: honest PoA block validates",
            category="control",
        )
    )

    # Merkle control
    leaves = [t.compute_hash() for t in block.transactions]
    assert merkle_root(leaves) == block.transactions_root
    report.outcomes.append(
        AttackOutcome(
            name="merkle_root_matches_leaves",
            blocked=True,
            detail="control: merkle root consistent",
            category="control",
        )
    )

    return report
