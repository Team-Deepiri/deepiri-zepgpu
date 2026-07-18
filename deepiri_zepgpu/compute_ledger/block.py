"""Compute ledger block structure and hashing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from deepiri_zepgpu.compute_ledger.hashing import canonical_json, sha256_hex
from deepiri_zepgpu.compute_ledger.merkle import merkle_root
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction

GENESIS_PREV_HASH = "0" * 64


@dataclass
class ValidatorApproval:
    """One PoA validator's signature over a block hash."""

    validator: str
    signature: str

    def to_dict(self) -> dict[str, str]:
        return {"validator": self.validator, "signature": self.signature}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ValidatorApproval:
        return cls(validator=str(data["validator"]), signature=str(data["signature"]))


@dataclass
class ComputeBlock:
    """PoA-sealed block of compute transactions."""

    height: int
    previous_hash: str
    transactions: list[ComputeTransaction]
    validator: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: str = field(default_factory=lambda: str(uuid4()))
    transactions_root: str = ""
    state_root: str = ""
    hash: str = ""
    validator_signature: str = ""
    approvals: list[ValidatorApproval] = field(default_factory=list)
    finalized: bool = True

    def leaf_hashes(self) -> list[str]:
        return [tx.compute_hash() for tx in self.transactions]

    def compute_transactions_root(self) -> str:
        """Merkle root over ordered transaction hashes."""
        return merkle_root(self.leaf_hashes())

    def header_for_hash(self) -> dict[str, Any]:
        return {
            "height": self.height,
            "previous_hash": self.previous_hash,
            "timestamp": self.timestamp,
            "transactions_root": self.transactions_root,
            "state_root": self.state_root,
            "validator": self.validator,
        }

    def compute_hash(self) -> str:
        return sha256_hex(canonical_json(self.header_for_hash()))

    def ensure_proposer_approval(self) -> None:
        """Ensure proposer's signature is present in approvals list."""
        if not self.validator_signature:
            return
        for a in self.approvals:
            if a.validator == self.validator:
                return
        self.approvals.append(
            ValidatorApproval(validator=self.validator, signature=self.validator_signature)
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["transactions"] = [tx.to_dict() for tx in self.transactions]
        data["approvals"] = [a.to_dict() if isinstance(a, ValidatorApproval) else a for a in self.approvals]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComputeBlock:
        txs = [ComputeTransaction.from_dict(t) for t in data.get("transactions") or []]
        approvals = [ValidatorApproval.from_dict(a) for a in data.get("approvals") or []]
        return cls(
            id=data.get("id", str(uuid4())),
            height=int(data["height"]),
            previous_hash=data["previous_hash"],
            timestamp=data["timestamp"],
            transactions=txs,
            transactions_root=data.get("transactions_root") or "",
            state_root=data.get("state_root") or "",
            validator=data["validator"],
            hash=data.get("hash") or "",
            validator_signature=data.get("validator_signature") or "",
            approvals=approvals,
            finalized=bool(data.get("finalized", True)),
        )
