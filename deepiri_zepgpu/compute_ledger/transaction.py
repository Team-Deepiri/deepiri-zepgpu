"""Compute ledger transaction types and hashing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from deepiri_zepgpu.compute_ledger.hashing import canonical_json, sha256_hex


class TxType(str, Enum):
    """Supported compute-ledger transaction types."""

    JOB_SUBMITTED = "JOB_SUBMITTED"
    JOB_ASSIGNED = "JOB_ASSIGNED"
    JOB_COMPLETED = "JOB_COMPLETED"
    CREDIT_SETTLED = "CREDIT_SETTLED"
    VALIDATOR_REGISTERED = "VALIDATOR_REGISTERED"


@dataclass
class ComputeTransaction:
    """Signed compute attestation / settlement transaction."""

    tx_type: TxType
    sender: str
    nonce: int
    payload: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: str = field(default_factory=lambda: str(uuid4()))
    signature: str = ""

    def signing_payload(self) -> dict[str, Any]:
        """Fields that participate in the transaction hash / signature."""
        return {
            "id": self.id,
            "tx_type": self.tx_type.value if isinstance(self.tx_type, TxType) else self.tx_type,
            "sender": self.sender,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    def compute_hash(self) -> str:
        """Hash of the unsigned transaction body."""
        return sha256_hex(canonical_json(self.signing_payload()))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tx_type"] = self.tx_type.value if isinstance(self.tx_type, TxType) else self.tx_type
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComputeTransaction:
        return cls(
            id=data["id"],
            tx_type=TxType(data["tx_type"]),
            sender=data["sender"],
            nonce=int(data["nonce"]),
            timestamp=data["timestamp"],
            payload=dict(data.get("payload") or {}),
            signature=data.get("signature") or "",
        )
