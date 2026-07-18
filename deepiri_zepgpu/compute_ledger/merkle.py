"""Binary Merkle tree helpers for transaction inclusion proofs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from deepiri_zepgpu.compute_ledger.hashing import sha256_hex


def _hash_pair(left: str, right: str) -> str:
    """Hash two hex digests in lexicographic order for commutativity safety.

    We keep left/right order as provided (standard Merkle) so proofs are directional.
    """
    return sha256_hex((left + right).encode("ascii"))


def merkle_root(leaves: Sequence[str]) -> str:
    """Compute Merkle root over ordered leaf hashes (hex strings).

    Empty tree uses the zero hash. Odd nodes are duplicated (Bitcoin-style).
    """
    if not leaves:
        return "0" * 64
    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            nxt.append(_hash_pair(level[i], level[i + 1]))
        level = nxt
    return level[0]


@dataclass(frozen=True)
class MerkleProofStep:
    """One sibling hash in a Merkle proof."""

    hash: str
    position: str  # "left" | "right" — sibling position relative to the running hash


@dataclass
class MerkleProof:
    leaf: str
    index: int
    root: str
    steps: list[MerkleProofStep]

    def to_dict(self) -> dict:
        return {
            "leaf": self.leaf,
            "index": self.index,
            "root": self.root,
            "steps": [{"hash": s.hash, "position": s.position} for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict) -> MerkleProof:
        steps = [
            MerkleProofStep(hash=s["hash"], position=s["position"])
            for s in data.get("steps") or []
        ]
        return cls(
            leaf=data["leaf"],
            index=int(data["index"]),
            root=data["root"],
            steps=steps,
        )


def merkle_proof(leaves: Sequence[str], index: int) -> MerkleProof:
    """Build an inclusion proof for ``leaves[index]``."""
    if not leaves:
        raise ValueError("Cannot build proof for empty leaf set")
    if index < 0 or index >= len(leaves):
        raise IndexError("Leaf index out of range")

    leaf = leaves[index]
    level = list(leaves)
    idx = index
    steps: list[MerkleProofStep] = []

    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        if idx % 2 == 0:
            sibling = level[idx + 1]
            steps.append(MerkleProofStep(hash=sibling, position="right"))
        else:
            sibling = level[idx - 1]
            steps.append(MerkleProofStep(hash=sibling, position="left"))
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            nxt.append(_hash_pair(level[i], level[i + 1]))
        level = nxt
        idx //= 2

    return MerkleProof(leaf=leaf, index=index, root=level[0], steps=steps)


def verify_merkle_proof(proof: MerkleProof) -> bool:
    """Recompute root from leaf + steps; compare to claimed root."""
    running = proof.leaf
    for step in proof.steps:
        if step.position == "right":
            running = _hash_pair(running, step.hash)
        elif step.position == "left":
            running = _hash_pair(step.hash, running)
        else:
            return False
    return running == proof.root
