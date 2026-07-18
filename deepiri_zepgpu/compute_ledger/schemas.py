"""Pydantic schemas for compute ledger API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TransactionSubmitRequest(BaseModel):
    id: Optional[str] = None
    tx_type: str
    sender: str
    nonce: int
    timestamp: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    signature: str


class JobCompletedRequest(BaseModel):
    task_id: str
    provider_account: str
    consumer_account: str
    gpu_seconds: float = Field(ge=0)
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    peer_id: Optional[str] = None


class PeerJobCompletedRequest(BaseModel):
    """Peer-signed JOB_COMPLETED attestation."""

    id: Optional[str] = None
    sender: str
    nonce: int
    timestamp: Optional[str] = None
    payload: dict[str, Any]
    signature: str
    peer_id: str


class CreditSettleRequest(BaseModel):
    from_account: str
    to_account: str
    amount_seconds: float = Field(ge=0)
    memo: Optional[str] = None


class BlockApproveRequest(BaseModel):
    validator: str
    signature: str


class TransactionResponse(BaseModel):
    id: str
    tx_type: str
    sender: str
    nonce: int
    timestamp: str
    payload: dict[str, Any]
    signature: str
    tx_hash: Optional[str] = None


class ApprovalResponse(BaseModel):
    validator: str
    signature: str


class BlockResponse(BaseModel):
    id: str
    height: int
    hash: str
    previous_hash: str
    timestamp: str
    transactions_root: str
    state_root: str
    validator: str
    validator_signature: str
    approvals: list[ApprovalResponse] = Field(default_factory=list)
    finalized: bool = True
    transactions: list[TransactionResponse] = Field(default_factory=list)


class BalanceResponse(BaseModel):
    account: str
    credit_seconds: float
    debit_seconds: float
    net_seconds: float


class ChainStatusResponse(BaseModel):
    chain_id: str
    network_id: Optional[str] = None
    tip_height: int
    tip_hash: Optional[str]
    block_count: int
    pending_count: int
    unfinalized_count: int = 0
    validator_public_key: str
    quorum_threshold: int = 1
    approval_count: int = 0
    enabled: bool


class VerifyResponse(BaseModel):
    valid: bool
    chain_id: str
    network_id: Optional[str] = None
    block_count: int
    tip_height: int
    tip_hash: Optional[str]
    state_root: str
    quorum_threshold: int = 1
    errors: list[str]
    balances: list[BalanceResponse]


class SubmitResponse(BaseModel):
    transaction: TransactionResponse
    block: Optional[BlockResponse] = None


class KeypairResponse(BaseModel):
    private_key: str
    public_key: str
    note: str = "Store the private key securely. It is not retained by the server."


class MerkleProofResponse(BaseModel):
    block_hash: str
    block_height: int
    transactions_root: str
    proof: dict[str, Any]
    valid: bool


class RegisterValidatorRequest(BaseModel):
    public_key: str
    label: str = "validator"
