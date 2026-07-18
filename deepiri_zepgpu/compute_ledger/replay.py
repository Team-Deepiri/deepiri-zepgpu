"""Deterministic credit state replay from compute ledger transactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deepiri_zepgpu.compute_ledger.hashing import hash_payload
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction, TxType


@dataclass
class CreditBalance:
    """Per-account GPU-second credits."""

    account: str
    credit_seconds: float = 0.0
    debit_seconds: float = 0.0

    @property
    def net_seconds(self) -> float:
        return self.credit_seconds - self.debit_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "credit_seconds": self.credit_seconds,
            "debit_seconds": self.debit_seconds,
            "net_seconds": self.net_seconds,
        }


@dataclass
class CreditState:
    """Global credit ledger derived by replaying transactions."""

    balances: dict[str, CreditBalance] = field(default_factory=dict)
    nonces: dict[str, int] = field(default_factory=dict)

    def get_or_create(self, account: str) -> CreditBalance:
        if account not in self.balances:
            self.balances[account] = CreditBalance(account=account)
        return self.balances[account]

    def state_root(self) -> str:
        """Hash of sorted balances for inclusion in block headers."""
        rows = [
            {
                "account": b.account,
                "credit_seconds": b.credit_seconds,
                "debit_seconds": b.debit_seconds,
            }
            for b in sorted(self.balances.values(), key=lambda x: x.account)
        ]
        return hash_payload(rows)

    def to_list(self) -> list[dict[str, Any]]:
        return [b.to_dict() for b in sorted(self.balances.values(), key=lambda x: x.account)]


def apply_transaction(state: CreditState, tx: ComputeTransaction) -> CreditState:
    """Apply a single transaction to credit state (mutates and returns state)."""
    last_nonce = state.nonces.get(tx.sender, -1)
    if tx.nonce <= last_nonce:
        raise ValueError(f"Stale or duplicate nonce for {tx.sender}: {tx.nonce}")
    state.nonces[tx.sender] = tx.nonce

    payload = tx.payload or {}
    tx_type = tx.tx_type if isinstance(tx.tx_type, TxType) else TxType(tx.tx_type)

    if tx_type == TxType.JOB_COMPLETED:
        provider = str(payload.get("provider_account") or tx.sender)
        consumer = str(payload.get("consumer_account") or "")
        gpu_seconds = float(payload.get("gpu_seconds") or 0.0)
        if gpu_seconds < 0:
            raise ValueError("gpu_seconds must be non-negative")
        state.get_or_create(provider).credit_seconds += gpu_seconds
        if consumer:
            state.get_or_create(consumer).debit_seconds += gpu_seconds

    elif tx_type == TxType.CREDIT_SETTLED:
        from_account = str(payload.get("from_account") or tx.sender)
        to_account = str(payload.get("to_account") or "")
        amount = float(payload.get("amount_seconds") or 0.0)
        if amount < 0:
            raise ValueError("amount_seconds must be non-negative")
        if not to_account:
            raise ValueError("CREDIT_SETTLED requires to_account")
        state.get_or_create(from_account).debit_seconds += amount
        state.get_or_create(to_account).credit_seconds += amount

    elif tx_type == TxType.BRIDGE_BURN:
        account = str(payload.get("account") or "")
        amount = float(payload.get("amount_seconds") or 0.0)
        if not account:
            raise ValueError("BRIDGE_BURN requires account")
        if amount <= 0:
            raise ValueError("BRIDGE_BURN amount_seconds must be positive")
        bal = state.get_or_create(account)
        if bal.net_seconds < amount:
            raise ValueError(
                f"BRIDGE_BURN insufficient balance: have {bal.net_seconds}, need {amount}"
            )
        bal.debit_seconds += amount

    elif tx_type == TxType.BRIDGE_MINT:
        account = str(payload.get("account") or "")
        amount = float(payload.get("amount_seconds") or 0.0)
        if not account:
            raise ValueError("BRIDGE_MINT requires account")
        if amount <= 0:
            raise ValueError("BRIDGE_MINT amount_seconds must be positive")
        if not payload.get("receipt_id"):
            raise ValueError("BRIDGE_MINT requires receipt_id")
        state.get_or_create(account).credit_seconds += amount

    elif tx_type in (
        TxType.JOB_SUBMITTED,
        TxType.JOB_ASSIGNED,
        TxType.VALIDATOR_REGISTERED,
    ):
        # Attestation / registry events — no credit mutation.
        pass
    else:
        raise ValueError(f"Unsupported tx type: {tx_type}")

    return state


def replay_transactions(transactions: list[ComputeTransaction]) -> CreditState:
    """Replay an ordered list of transactions into credit state."""
    state = CreditState()
    for tx in transactions:
        apply_transaction(state, tx)
    return state
