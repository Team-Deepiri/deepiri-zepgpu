"""Permissioned compute ledger for ZepGPU GPU-pool attestation and credits.

Week-1: append-only hash-linked blocks, Ed25519 signed transactions,
proof-of-authority block sealing, and deterministic credit replay.

Week-2: multi-validator quorum, per-VPN-network chains, peer attestation
keys, and Merkle inclusion proofs.
"""

from deepiri_zepgpu.compute_ledger.hashing import canonical_json, sha256_hex
from deepiri_zepgpu.compute_ledger.keys import generate_keypair, sign_message, verify_signature
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction, TxType
from deepiri_zepgpu.compute_ledger.block import ComputeBlock
from deepiri_zepgpu.compute_ledger.poa import validate_block, validate_transaction
from deepiri_zepgpu.compute_ledger.replay import CreditState, replay_transactions
from deepiri_zepgpu.compute_ledger.merkle import merkle_proof, merkle_root, verify_merkle_proof
from deepiri_zepgpu.compute_ledger.chain_id import chain_id_for_network

__all__ = [
    "canonical_json",
    "sha256_hex",
    "generate_keypair",
    "sign_message",
    "verify_signature",
    "ComputeTransaction",
    "TxType",
    "ComputeBlock",
    "validate_block",
    "validate_transaction",
    "CreditState",
    "replay_transactions",
    "merkle_proof",
    "merkle_root",
    "verify_merkle_proof",
    "chain_id_for_network",
]
