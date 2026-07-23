"""Compute ledger REST API — attestation, quorum, merkle proofs, network chains."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_db_session, get_required_user
from deepiri_zepgpu.compute_ledger.bridge import BridgeService
from deepiri_zepgpu.compute_ledger.chain_id import chain_id_for_network
from deepiri_zepgpu.compute_ledger.keys import generate_keypair
from deepiri_zepgpu.compute_ledger.poa import LedgerValidationError
from deepiri_zepgpu.compute_ledger.schemas import (
    ApprovalResponse,
    BalanceResponse,
    BlockApproveRequest,
    BlockResponse,
    BridgeTransferRequest,
    BridgeTransferResponse,
    ChainStatusResponse,
    CreditSettleRequest,
    HeaderVerifyRequest,
    HeaderVerifyResponse,
    JobCompletedRequest,
    KeypairResponse,
    MerkleProofResponse,
    PeerJobCompletedRequest,
    RegisterValidatorRequest,
    SubmitResponse,
    SyncHeadersResponse,
    TransactionResponse,
    TransactionSubmitRequest,
    VerifyResponse,
)
from deepiri_zepgpu.compute_ledger.service import LedgerService, new_signed_transaction
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction, TxType
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.models import User
from deepiri_zepgpu.vpn.repositories import PeerRepository

router = APIRouter(prefix="/ledger", tags=["Compute Ledger"])


def _service(db: AsyncSession, network_id: str | None) -> LedgerService:
    return LedgerService(db, network_id=network_id)


def _tx_response(tx: ComputeTransaction | dict) -> TransactionResponse:
    data = tx.to_dict() if isinstance(tx, ComputeTransaction) else tx
    ct = ComputeTransaction.from_dict(data) if not isinstance(tx, ComputeTransaction) else tx
    return TransactionResponse(
        id=data["id"],
        tx_type=data["tx_type"],
        sender=data["sender"],
        nonce=data["nonce"],
        timestamp=data["timestamp"],
        payload=data.get("payload") or {},
        signature=data.get("signature") or "",
        tx_hash=ct.compute_hash(),
    )


def _block_response(block: dict | object) -> BlockResponse:
    data = block.to_dict() if hasattr(block, "to_dict") else dict(block)  # type: ignore[arg-type]
    txs = [_tx_response(t) for t in data.get("transactions") or []]
    approvals = [
        ApprovalResponse(validator=a["validator"], signature=a["signature"])
        for a in data.get("approvals") or []
    ]
    return BlockResponse(
        id=data["id"],
        height=data["height"],
        hash=data["hash"],
        previous_hash=data["previous_hash"],
        timestamp=data["timestamp"],
        transactions_root=data["transactions_root"],
        state_root=data["state_root"],
        validator=data["validator"],
        validator_signature=data["validator_signature"],
        approvals=approvals,
        finalized=bool(data.get("finalized", True)),
        transactions=txs,
    )


@router.get("/status", response_model=ChainStatusResponse)
async def ledger_status(
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    if not settings.ledger.enabled:
        raise HTTPException(status_code=503, detail="Compute ledger is disabled")
    service = _service(db, network_id)
    await service.ensure_initialized()
    tip = await service.repo.get_tip(service.chain_id, finalized_only=True)
    pending = await service.repo.list_pending_transactions(service.chain_id)
    unfinalized = await service.repo.get_unfinalized_tip(service.chain_id)
    _, pub = service.validator_keys()
    approval_count = 0
    if unfinalized and unfinalized.approvals:
        approval_count = len(unfinalized.approvals)
    return ChainStatusResponse(
        chain_id=service.chain_id,
        network_id=service.network_id,
        tip_height=tip.height if tip else -1,
        tip_hash=tip.hash if tip else None,
        block_count=(tip.height + 1) if tip else 0,
        pending_count=len(pending),
        unfinalized_count=1 if unfinalized else 0,
        validator_public_key=pub,
        quorum_threshold=service.quorum_threshold,
        approval_count=approval_count,
        enabled=settings.ledger.enabled,
    )


@router.get("/verify", response_model=VerifyResponse)
async def verify_ledger(
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    result = await service.verify_chain()
    return VerifyResponse(
        valid=result["valid"],
        chain_id=result["chain_id"],
        network_id=result.get("network_id"),
        block_count=result["block_count"],
        tip_height=result["tip_height"],
        tip_hash=result["tip_hash"],
        state_root=result["state_root"],
        quorum_threshold=result.get("quorum_threshold", 1),
        errors=result["errors"],
        balances=[BalanceResponse(**b) for b in result["balances"]],
    )


@router.get("/blocks", response_model=list[BlockResponse])
async def list_blocks(
    network_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    await service.ensure_initialized()
    rows = await service.repo.list_blocks(service.chain_id, limit=limit, offset=offset)
    return [_block_response(service._block_to_domain(r)) for r in rows]


@router.get("/blocks/height/{height}", response_model=BlockResponse)
async def get_block_by_height(
    height: int,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    row = await service.repo.get_block_by_height(service.chain_id, height)
    if not row:
        raise HTTPException(status_code=404, detail="Block not found")
    return _block_response(service._block_to_domain(row))


@router.get("/blocks/hash/{block_hash}", response_model=BlockResponse)
async def get_block_by_hash(
    block_hash: str,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    row = await service.repo.get_block_by_hash(block_hash)
    if not row or row.chain_id != service.chain_id:
        raise HTTPException(status_code=404, detail="Block not found")
    return _block_response(service._block_to_domain(row))


@router.get("/blocks/hash/{block_hash}/proof/{tx_hash}", response_model=MerkleProofResponse)
async def get_merkle_proof(
    block_hash: str,
    tx_hash: str,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    try:
        result = await service.get_inclusion_proof(block_hash, tx_hash)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MerkleProofResponse(**result)


@router.post("/blocks/hash/{block_hash}/approve", response_model=BlockResponse)
async def approve_block(
    block_hash: str,
    body: BlockApproveRequest,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    try:
        block = await service.approve_block(
            block_hash,
            validator_public_key=body.validator,
            signature=body.signature,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _block_response(block)


@router.post("/blocks/hash/{block_hash}/approve-relay", response_model=BlockResponse)
async def approve_block_relay(
    block_hash: str,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    try:
        block = await service.approve_block_as_relay(block_hash)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _block_response(block)


@router.get("/balances", response_model=list[BalanceResponse])
async def list_balances(
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    await service.ensure_initialized()
    rows = await service.repo.list_balances(service.chain_id)
    return [
        BalanceResponse(
            account=r.account,
            credit_seconds=r.credit_seconds,
            debit_seconds=r.debit_seconds,
            net_seconds=r.credit_seconds - r.debit_seconds,
        )
        for r in rows
    ]


@router.get("/balances/{account}", response_model=BalanceResponse)
async def get_balance(
    account: str,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    row = await service.repo.get_balance(service.chain_id, account)
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    return BalanceResponse(
        account=row.account,
        credit_seconds=row.credit_seconds,
        debit_seconds=row.debit_seconds,
        net_seconds=row.credit_seconds - row.debit_seconds,
    )


@router.post("/transactions", response_model=SubmitResponse)
async def submit_transaction(
    body: TransactionSubmitRequest,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    try:
        tx_type = TxType(body.tx_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid tx_type: {body.tx_type}") from exc

    data = body.model_dump()
    if not data.get("id"):
        data["id"] = str(uuid4())
    if not data.get("timestamp"):
        data["timestamp"] = datetime.now(UTC).isoformat()
    data["tx_type"] = tx_type.value
    tx = ComputeTransaction.from_dict(data)
    try:
        result = await service.submit_transaction(tx)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SubmitResponse(
        transaction=_tx_response(result["transaction"]),
        block=_block_response(result["block"]) if result["block"] else None,
    )


@router.post("/attestations/job-completed", response_model=SubmitResponse)
async def attest_job_completed(
    body: JobCompletedRequest,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    try:
        result = await service.record_job_completed(
            task_id=body.task_id,
            provider_account=body.provider_account,
            consumer_account=body.consumer_account,
            gpu_seconds=body.gpu_seconds,
            input_hash=body.input_hash,
            output_hash=body.output_hash,
            peer_id=body.peer_id,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SubmitResponse(
        transaction=_tx_response(result["transaction"]),
        block=_block_response(result["block"]) if result["block"] else None,
    )


@router.post("/attestations/peer-job-completed", response_model=SubmitResponse)
async def attest_peer_job_completed(
    body: PeerJobCompletedRequest,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Accept a peer-signed JOB_COMPLETED. Peer must have matching ledger_public_key."""
    peer_repo = PeerRepository(db)
    peer = await peer_repo.get_by_id(body.peer_id)
    if not peer:
        raise HTTPException(status_code=404, detail="Peer not found")
    if not peer.ledger_public_key:
        raise HTTPException(status_code=400, detail="Peer has no ledger attestation key")
    if peer.ledger_public_key != body.sender:
        raise HTTPException(status_code=400, detail="Sender does not match peer ledger key")

    # Prefer network from peer membership when not specified
    scoped_network = network_id or str(peer.vpn_network_id)
    service = _service(db, scoped_network)
    data = {
        "id": body.id or str(uuid4()),
        "tx_type": TxType.JOB_COMPLETED.value,
        "sender": body.sender,
        "nonce": body.nonce,
        "timestamp": body.timestamp or datetime.now(UTC).isoformat(),
        "payload": body.payload,
        "signature": body.signature,
    }
    tx = ComputeTransaction.from_dict(data)
    try:
        result = await service.submit_peer_attestation(
            peer_public_key=peer.ledger_public_key,
            signed_tx=tx,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SubmitResponse(
        transaction=_tx_response(result["transaction"]),
        block=_block_response(result["block"]) if result["block"] else None,
    )


@router.post("/settle", response_model=SubmitResponse)
async def settle_credits(
    body: CreditSettleRequest,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    await service.ensure_initialized()
    priv, pub = service.validator_keys()
    nonce = (await service.repo.get_max_nonce(service.chain_id, pub)) + 1
    tx = new_signed_transaction(
        private_key_b64=priv,
        tx_type=TxType.CREDIT_SETTLED,
        nonce=nonce,
        payload={
            "from_account": body.from_account,
            "to_account": body.to_account,
            "amount_seconds": body.amount_seconds,
            "memo": body.memo,
            "settled_by": str(user.id),
        },
        sender=pub,
    )
    try:
        result = await service.submit_transaction(tx)
    except LedgerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SubmitResponse(
        transaction=_tx_response(result["transaction"]),
        block=_block_response(result["block"]) if result["block"] else None,
    )


@router.post("/seal", response_model=BlockResponse | None)
async def seal_pending(
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    try:
        block = await service.seal_pending()
    except LedgerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if block is None:
        return None
    return _block_response(block)


@router.post("/validators", response_model=dict)
async def register_validator(
    body: RegisterValidatorRequest,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    await service.ensure_initialized()
    row = await service.repo.upsert_validator(
        chain_id=service.chain_id,
        public_key=body.public_key,
        label=body.label,
        vpn_network_id=service.network_id,
    )
    await db.commit()
    return {
        "id": str(row.id),
        "public_key": row.public_key,
        "label": row.label,
        "chain_id": row.chain_id,
        "is_active": row.is_active,
    }


@router.post("/rebuild-balances", response_model=list[BalanceResponse])
async def rebuild_balances(
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    balances = await service.rebuild_balances()
    return [BalanceResponse(**b) for b in balances]


@router.post("/keys", response_model=KeypairResponse)
async def create_keypair(user: User = Depends(get_required_user)):
    priv, pub = generate_keypair()
    return KeypairResponse(private_key=priv, public_key=pub)


@router.get("/chain-id")
async def resolve_chain_id(
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
):
    return {"network_id": network_id, "chain_id": chain_id_for_network(network_id)}


@router.get("/sync/headers", response_model=SyncHeadersResponse)
async def sync_headers(
    network_id: str | None = Query(None),
    from_height: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    finalized_only: bool = Query(True),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    headers = await service.export_headers(
        from_height=from_height,
        limit=limit,
        finalized_only=finalized_only,
    )
    return SyncHeadersResponse(
        chain_id=service.chain_id,
        network_id=service.network_id,
        from_height=from_height,
        headers=headers,
        count=len(headers),
    )


@router.post("/sync/verify-headers", response_model=HeaderVerifyResponse)
async def verify_headers(
    body: HeaderVerifyRequest,
    network_id: str | None = Query(None),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = _service(db, network_id)
    result = await service.verify_headers_payload(
        body.headers,
        from_height=body.from_height,
    )
    return HeaderVerifyResponse(
        valid=result["valid"],
        chain_id=result["chain_id"],
        network_id=result.get("network_id"),
        headers=result["headers"],
        tip_hash=result.get("tip_hash"),
        tip_height=result.get("tip_height", -1),
        tip_state_root=result.get("tip_state_root"),
        errors=result.get("errors") or [],
    )


@router.post("/bridge/transfer", response_model=BridgeTransferResponse)
async def bridge_transfer(
    body: BridgeTransferRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    bridge = BridgeService(db)
    try:
        result = await bridge.transfer(
            source_network_id=body.source_network_id,
            dest_network_id=body.dest_network_id,
            account=body.account,
            amount_seconds=body.amount_seconds,
            memo=body.memo,
        )
    except LedgerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BridgeTransferResponse(**result)
