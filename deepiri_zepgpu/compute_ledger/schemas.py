"""Pydantic schemas for compute ledger API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TransactionSubmitRequest(BaseModel):
    id: str | None = None
    tx_type: str
    sender: str
    nonce: int
    timestamp: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    signature: str


class JobCompletedRequest(BaseModel):
    task_id: str
    provider_account: str
    consumer_account: str
    gpu_seconds: float = Field(ge=0)
    input_hash: str | None = None
    output_hash: str | None = None
    peer_id: str | None = None


class PeerJobCompletedRequest(BaseModel):
    """Peer-signed JOB_COMPLETED attestation."""

    id: str | None = None
    sender: str
    nonce: int
    timestamp: str | None = None
    payload: dict[str, Any]
    signature: str
    peer_id: str


class CreditSettleRequest(BaseModel):
    from_account: str
    to_account: str
    amount_seconds: float = Field(ge=0)
    memo: str | None = None


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
    tx_hash: str | None = None


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
    network_id: str | None = None
    tip_height: int
    tip_hash: str | None
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
    network_id: str | None = None
    block_count: int
    tip_height: int
    tip_hash: str | None
    state_root: str
    quorum_threshold: int = 1
    errors: list[str]
    balances: list[BalanceResponse]


class SubmitResponse(BaseModel):
    transaction: TransactionResponse
    block: BlockResponse | None = None


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


class BridgeTransferRequest(BaseModel):
    source_network_id: str | None = None
    dest_network_id: str | None = None
    account: str
    amount_seconds: float = Field(gt=0)
    memo: str | None = None


class HeaderVerifyRequest(BaseModel):
    headers: list[dict[str, Any]]
    from_height: int | None = None


class SyncHeadersResponse(BaseModel):
    chain_id: str
    network_id: str | None = None
    from_height: int
    headers: list[dict[str, Any]]
    count: int


class HeaderVerifyResponse(BaseModel):
    valid: bool
    chain_id: str
    network_id: str | None = None
    headers: int
    tip_hash: str | None
    tip_height: int
    tip_state_root: str | None = None
    errors: list[str]


class BridgeTransferResponse(BaseModel):
    receipt_id: str
    source_chain_id: str
    dest_chain_id: str
    account: str
    amount_seconds: float
    burn: dict[str, Any]
    mint: dict[str, Any]
    inclusion_proof: dict[str, Any]
