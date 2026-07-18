"""Compute ledger block structure and hashing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from deepiri_zepgpu.compute_ledger.hashing import canonical_json, hash_payload, sha256_hex
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction

GENESIS_PREV_HASH = "0" * 64


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

    def compute_transactions_root(self) -> str:
        """Deterministic root over ordered transaction hashes."""
        tx_hashes = [tx.compute_hash() for tx in self.transactions]
        return hash_payload(tx_hashes)

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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["transactions"] = [tx.to_dict() for tx in self.transactions]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComputeBlock:
        txs = [ComputeTransaction.from_dict(t) for t in data.get("transactions") or []]
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
        )
