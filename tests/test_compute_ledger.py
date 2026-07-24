"""Unit tests for compute ledger core (hashing, keys, PoA, replay, merkle, quorum)."""

from __future__ import annotations

import pytest

from deepiri_zepgpu.compute_ledger.block import GENESIS_PREV_HASH, ComputeBlock
from deepiri_zepgpu.compute_ledger.chain_id import chain_id_for_network, parse_network_id
from deepiri_zepgpu.compute_ledger.hashing import canonical_json, sha256_hex
from deepiri_zepgpu.compute_ledger.keys import (
    derive_keypair_from_seed,
    generate_keypair,
    public_key_from_private,
    sign_message,
    verify_signature,
)
from deepiri_zepgpu.compute_ledger.light_client import verify_header_chain, verify_tx_inclusion
from deepiri_zepgpu.compute_ledger.merkle import merkle_proof, merkle_root, verify_merkle_proof
from deepiri_zepgpu.compute_ledger.poa import (
    LedgerValidationError,
    add_approval,
    validate_approvals,
    validate_block,
    validate_transaction,
)
from deepiri_zepgpu.compute_ledger.replay import CreditState, apply_transaction, replay_transactions
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction, TxType
from deepiri_zepgpu.compute_ledger.light_client import verify_header_chain, verify_tx_inclusion


class TestHashing:
    def test_canonical_json_stable(self):
        a = canonical_json({"b": 1, "a": 2})
        b = canonical_json({"a": 2, "b": 1})
        assert a == b
        assert a == b'{"a":2,"b":1}'

    def test_sha256_hex(self):
        assert len(sha256_hex("hello")) == 64
        assert sha256_hex("hello") == sha256_hex(b"hello")


class TestKeys:
    def test_sign_verify_roundtrip(self):
        priv, pub = generate_keypair()
        sig = sign_message(priv, b"attest")
        assert verify_signature(pub, b"attest", sig)
        assert not verify_signature(pub, b"tampered", sig)

    def test_derive_stable(self):
        a = derive_keypair_from_seed("seed-one")
        b = derive_keypair_from_seed("seed-one")
        c = derive_keypair_from_seed("seed-two")
        assert a == b
        assert a[1] != c[1]
        assert public_key_from_private(a[0]) == a[1]


class TestMerkle:
    def test_single_leaf_root_is_leaf(self):
        leaf = sha256_hex("tx1")
        assert merkle_root([leaf]) == leaf

    def test_proof_roundtrip(self):
        leaves = [sha256_hex(f"tx-{i}") for i in range(5)]
        root = merkle_root(leaves)
        for i in range(5):
            proof = merkle_proof(leaves, i)
            assert proof.root == root
            assert verify_merkle_proof(proof)
            bad = merkle_proof(leaves, i)
            step0 = bad.steps[0]
            bad.steps[0] = type(step0)(hash="0" * 64, position=step0.position)
            assert not verify_merkle_proof(bad)


class TestChainId:
    def test_scoped_chain(self):
        cid = chain_id_for_network("abc-123")
        assert "vpn:abc-123" in cid
        assert parse_network_id(cid) == "abc-123"
        assert parse_network_id("zepgpu-compute-v1") is None


class TestReplay:
    def test_job_completed_credits(self):
        priv, pub = generate_keypair()
        tx = ComputeTransaction(
            tx_type=TxType.JOB_COMPLETED,
            sender=pub,
            nonce=0,
            payload={
                "provider_account": "peer-a",
                "consumer_account": "user-1",
                "gpu_seconds": 12.5,
            },
        )
        tx.signature = sign_message(priv, canonical_json(tx.signing_payload()))
        state = replay_transactions([tx])
        assert state.balances["peer-a"].credit_seconds == 12.5
        assert state.balances["user-1"].debit_seconds == 12.5
        assert state.balances["peer-a"].net_seconds == 12.5

    def test_reject_stale_nonce(self):
        _, pub = generate_keypair()
        state = CreditState()
        tx1 = ComputeTransaction(tx_type=TxType.JOB_SUBMITTED, sender=pub, nonce=1, payload={})
        apply_transaction(state, tx1)
        tx2 = ComputeTransaction(tx_type=TxType.JOB_SUBMITTED, sender=pub, nonce=1, payload={})
        with pytest.raises(ValueError, match="nonce"):
            apply_transaction(state, tx2)

    def test_credit_settle(self):
        priv, pub = generate_keypair()
        completed = ComputeTransaction(
            tx_type=TxType.JOB_COMPLETED,
            sender=pub,
            nonce=0,
            payload={
                "provider_account": "peer-a",
                "consumer_account": "user-1",
                "gpu_seconds": 10.0,
            },
        )
        settle = ComputeTransaction(
            tx_type=TxType.CREDIT_SETTLED,
            sender=pub,
            nonce=1,
            payload={
                "from_account": "user-1",
                "to_account": "peer-a",
                "amount_seconds": 3.0,
            },
        )
        state = replay_transactions([completed, settle])
        assert state.balances["peer-a"].credit_seconds == 13.0
        assert state.balances["user-1"].debit_seconds == 13.0


class TestPoA:
    def _signed_tx(self, priv: str, pub: str, nonce: int = 0) -> ComputeTransaction:
        tx = ComputeTransaction(
            tx_type=TxType.JOB_COMPLETED,
            sender=pub,
            nonce=nonce,
            payload={
                "provider_account": pub,
                "consumer_account": "consumer",
                "gpu_seconds": 1.0,
            },
        )
        tx.signature = sign_message(priv, canonical_json(tx.signing_payload()))
        return tx

    def test_validate_transaction_bad_sig(self):
        priv, pub = generate_keypair()
        tx = self._signed_tx(priv, pub)
        tx.signature = "AAAA"
        with pytest.raises(LedgerValidationError):
            validate_transaction(tx)

    def test_seal_and_validate_block(self):
        priv, pub = generate_keypair()
        tx = self._signed_tx(priv, pub)
        state = replay_transactions([tx])
        block = ComputeBlock(
            height=0,
            previous_hash=GENESIS_PREV_HASH,
            transactions=[tx],
            validator=pub,
        )
        block.transactions_root = block.compute_transactions_root()
        block.state_root = state.state_root()
        block.hash = block.compute_hash()
        block.validator_signature = sign_message(priv, block.hash)
        block.ensure_proposer_approval()

        validate_block(
            block,
            authorized_validators={pub},
            expected_previous_hash=GENESIS_PREV_HASH,
            expected_height=0,
            quorum_threshold=1,
        )

        block.hash = "0" * 64
        with pytest.raises(LedgerValidationError, match="hash"):
            validate_block(
                block,
                authorized_validators={pub},
                expected_previous_hash=GENESIS_PREV_HASH,
                expected_height=0,
            )

    def test_unauthorized_validator(self):
        priv, pub = generate_keypair()
        other_priv, other_pub = generate_keypair()
        tx = self._signed_tx(priv, pub)
        block = ComputeBlock(
            height=0,
            previous_hash=GENESIS_PREV_HASH,
            transactions=[tx],
            validator=other_pub,
        )
        block.transactions_root = block.compute_transactions_root()
        block.state_root = "0" * 64
        block.hash = block.compute_hash()
        block.validator_signature = sign_message(other_priv, block.hash)
        with pytest.raises(LedgerValidationError, match="not authorized"):
            validate_block(block, authorized_validators={pub})

    def test_quorum_two_of_three(self):
        keys = [generate_keypair() for _ in range(3)]
        priv0, pub0 = keys[0]
        priv1, pub1 = keys[1]
        _, pub2 = keys[2]
        tx = self._signed_tx(priv0, pub0)
        state = replay_transactions([tx])
        block = ComputeBlock(
            height=0,
            previous_hash=GENESIS_PREV_HASH,
            transactions=[tx],
            validator=pub0,
        )
        block.transactions_root = block.compute_transactions_root()
        block.state_root = state.state_root()
        block.hash = block.compute_hash()
        block.validator_signature = sign_message(priv0, block.hash)
        block.ensure_proposer_approval()

        with pytest.raises(LedgerValidationError, match="Quorum"):
            validate_approvals(
                block,
                authorized_validators={pub0, pub1, pub2},
                quorum_threshold=2,
            )

        add_approval(
            block,
            validator_public_key=pub1,
            signature=sign_message(priv1, block.hash),
            authorized_validators={pub0, pub1, pub2},
        )
        validate_approvals(
            block,
            authorized_validators={pub0, pub1, pub2},
            quorum_threshold=2,
        )
        assert len(block.approvals) == 2


class TestBridgeReplay:
    def test_burn_and_mint(self):
        priv, pub = generate_keypair()
        earn = ComputeTransaction(
            tx_type=TxType.JOB_COMPLETED,
            sender=pub,
            nonce=0,
            payload={
                "provider_account": "acct",
                "consumer_account": "user",
                "gpu_seconds": 20.0,
            },
        )
        burn = ComputeTransaction(
            tx_type=TxType.BRIDGE_BURN,
            sender=pub,
            nonce=1,
            payload={"account": "acct", "amount_seconds": 5.0, "dest_chain_id": "other"},
        )
        mint = ComputeTransaction(
            tx_type=TxType.BRIDGE_MINT,
            sender=pub,
            nonce=2,
            payload={
                "account": "acct",
                "amount_seconds": 5.0,
                "receipt_id": "abc",
            },
        )
        # burn alone on source-like chain
        state = replay_transactions([earn, burn])
        assert state.balances["acct"].net_seconds == 15.0
        # mint alone on dest-like chain
        dest = replay_transactions([mint])
        assert dest.balances["acct"].credit_seconds == 5.0

    def test_burn_insufficient(self):
        priv, pub = generate_keypair()
        burn = ComputeTransaction(
            tx_type=TxType.BRIDGE_BURN,
            sender=pub,
            nonce=0,
            payload={"account": "acct", "amount_seconds": 5.0},
        )
        with pytest.raises(ValueError, match="insufficient"):
            replay_transactions([burn])


class TestLightClient:
    def _header_from_block(self, block: ComputeBlock):
        from deepiri_zepgpu.compute_ledger.light_client import BlockHeader

        return BlockHeader.from_block(block)

    def test_header_chain_and_inclusion(self):
        priv, pub = generate_keypair()
        tx = ComputeTransaction(
            tx_type=TxType.JOB_COMPLETED,
            sender=pub,
            nonce=0,
            payload={
                "provider_account": pub,
                "consumer_account": "c",
                "gpu_seconds": 1.0,
            },
        )
        tx.signature = sign_message(priv, canonical_json(tx.signing_payload()))
        state = replay_transactions([tx])
        block = ComputeBlock(
            height=0,
            previous_hash=GENESIS_PREV_HASH,
            transactions=[tx],
            validator=pub,
        )
        block.transactions_root = block.compute_transactions_root()
        block.state_root = state.state_root()
        block.hash = block.compute_hash()
        block.validator_signature = sign_message(priv, block.hash)
        block.ensure_proposer_approval()

        header = self._header_from_block(block)
        result = verify_header_chain(
            [header],
            authorized_validators={pub},
            quorum_threshold=1,
        )
        assert result["valid"] is True

        proof = merkle_proof(block.leaf_hashes(), 0)
        assert verify_tx_inclusion(header=header, proof=proof)
