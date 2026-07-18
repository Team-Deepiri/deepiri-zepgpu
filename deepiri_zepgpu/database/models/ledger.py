"""SQLAlchemy models for the permissioned compute ledger."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from deepiri_zepgpu.database.models.base import Base, TimestampMixin, UUIDMixin


class LedgerTxType(str, enum.Enum):
    JOB_SUBMITTED = "JOB_SUBMITTED"
    JOB_ASSIGNED = "JOB_ASSIGNED"
    JOB_COMPLETED = "JOB_COMPLETED"
    CREDIT_SETTLED = "CREDIT_SETTLED"
    VALIDATOR_REGISTERED = "VALIDATOR_REGISTERED"
    BRIDGE_BURN = "BRIDGE_BURN"
    BRIDGE_MINT = "BRIDGE_MINT"


class LedgerValidator(UUIDMixin, TimestampMixin, Base):
    """Authorized PoA validators for the compute ledger."""

    __tablename__ = "ledger_validators"

    public_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="relay")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    chain_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vpn_network_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("chain_id", "public_key", name="uq_ledger_validators_chain_pubkey"),
    )


class LedgerBlock(UUIDMixin, Base):
    """Append-only sealed block."""

    __tablename__ = "ledger_blocks"

    chain_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transactions_root: Mapped[str] = mapped_column(String(64), nullable=False)
    state_root: Mapped[str] = mapped_column(String(64), nullable=False)
    validator_public_key: Mapped[str] = mapped_column(String(128), nullable=False)
    validator_signature: Mapped[str] = mapped_column(Text, nullable=False)
    approvals: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    finalized: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    vpn_network_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    transactions: Mapped[list[LedgerTransaction]] = relationship(
        "LedgerTransaction",
        back_populates="block",
        lazy="selectin",
        order_by="LedgerTransaction.position",
    )

    __table_args__ = (
        UniqueConstraint("chain_id", "height", name="uq_ledger_blocks_chain_height"),
        Index("idx_ledger_blocks_chain_height", "chain_id", "height"),
    )


class LedgerTransaction(UUIDMixin, Base):
    """Compute attestation / settlement transaction (pending or sealed)."""

    __tablename__ = "ledger_transactions"

    chain_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tx_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    tx_type: Mapped[LedgerTxType] = mapped_column(Enum(LedgerTxType), nullable=False, index=True)
    sender: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    nonce: Mapped[int] = mapped_column(BigInteger, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    vpn_network_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    block_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ledger_blocks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    block: Mapped[LedgerBlock | None] = relationship("LedgerBlock", back_populates="transactions")

    __table_args__ = (
        UniqueConstraint("chain_id", "sender", "nonce", name="uq_ledger_tx_sender_nonce"),
        Index("idx_ledger_tx_pending", "chain_id", "block_id"),
    )


class LedgerBalance(UUIDMixin, TimestampMixin, Base):
    """Materialized credit balances (rebuildable via replay)."""

    __tablename__ = "ledger_balances"

    chain_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    credit_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    debit_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    vpn_network_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("chain_id", "account", name="uq_ledger_balances_chain_account"),
    )


class LedgerBridgeReceipt(UUIDMixin, TimestampMixin, Base):
    """Replay-protection registry for cross-network bridge mints."""

    __tablename__ = "ledger_bridge_receipts"

    receipt_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_chain_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    dest_chain_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    account: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    burn_tx_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mint_tx_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)

    __table_args__ = (
        UniqueConstraint("dest_chain_id", "receipt_id", name="uq_ledger_bridge_dest_receipt"),
    )
