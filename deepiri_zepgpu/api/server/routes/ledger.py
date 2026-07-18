"""Compute ledger REST API — attestation, blocks, balances, verify."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.api.server.dependencies import get_db_session, get_required_user
from deepiri_zepgpu.compute_ledger.keys import generate_keypair
from deepiri_zepgpu.compute_ledger.poa import LedgerValidationError
from deepiri_zepgpu.compute_ledger.schemas import (
    BalanceResponse,
    BlockResponse,
    ChainStatusResponse,
    CreditSettleRequest,
    JobCompletedRequest,
    KeypairResponse,
    SubmitResponse,
    TransactionResponse,
    TransactionSubmitRequest,
    VerifyResponse,
)
from deepiri_zepgpu.compute_ledger.service import LedgerService, new_signed_transaction
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction, TxType
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.models import User

router = APIRouter(prefix="/ledger", tags=["Compute Ledger"])


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
        transactions=txs,
    )


@router.get("/status", response_model=ChainStatusResponse)
async def ledger_status(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    if not settings.ledger.enabled:
        raise HTTPException(status_code=503, detail="Compute ledger is disabled")
    service = LedgerService(db)
    await service.ensure_initialized()
    tip = await service.repo.get_tip(service.chain_id)
    pending = await service.repo.list_pending_transactions(service.chain_id)
    _, pub = service.validator_keys()
    return ChainStatusResponse(
        chain_id=service.chain_id,
        tip_height=tip.height if tip else -1,
        tip_hash=tip.hash if tip else None,
        block_count=(tip.height + 1) if tip else 0,
        pending_count=len(pending),
        validator_public_key=pub,
        enabled=settings.ledger.enabled,
    )


@router.get("/verify", response_model=VerifyResponse)
async def verify_ledger(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
    result = await service.verify_chain()
    return VerifyResponse(
        valid=result["valid"],
        chain_id=result["chain_id"],
        block_count=result["block_count"],
        tip_height=result["tip_height"],
        tip_hash=result["tip_hash"],
        state_root=result["state_root"],
        errors=result["errors"],
        balances=[BalanceResponse(**b) for b in result["balances"]],
    )


@router.get("/blocks", response_model=list[BlockResponse])
async def list_blocks(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
    await service.ensure_initialized()
    rows = await service.repo.list_blocks(service.chain_id, limit=limit, offset=offset)
    return [_block_response(service._block_to_domain(r)) for r in rows]


@router.get("/blocks/height/{height}", response_model=BlockResponse)
async def get_block_by_height(
    height: int,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
    row = await service.repo.get_block_by_height(service.chain_id, height)
    if not row:
        raise HTTPException(status_code=404, detail="Block not found")
    return _block_response(service._block_to_domain(row))


@router.get("/blocks/hash/{block_hash}", response_model=BlockResponse)
async def get_block_by_hash(
    block_hash: str,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
    row = await service.repo.get_block_by_hash(block_hash)
    if not row or row.chain_id != service.chain_id:
        raise HTTPException(status_code=404, detail="Block not found")
    return _block_response(service._block_to_domain(row))


@router.get("/balances", response_model=list[BalanceResponse])
async def list_balances(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
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
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
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
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
    try:
        tx_type = TxType(body.tx_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid tx_type: {body.tx_type}") from exc

    data = body.model_dump()
    if not data.get("id"):
        from uuid import uuid4

        data["id"] = str(uuid4())
    if not data.get("timestamp"):
        from datetime import datetime, timezone

        data["timestamp"] = datetime.now(timezone.utc).isoformat()
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
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
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


@router.post("/settle", response_model=SubmitResponse)
async def settle_credits(
    body: CreditSettleRequest,
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
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
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
    try:
        block = await service.seal_pending()
    except LedgerValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if block is None:
        return None
    return _block_response(block)


@router.post("/rebuild-balances", response_model=list[BalanceResponse])
async def rebuild_balances(
    user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db_session),
):
    service = LedgerService(db)
    balances = await service.rebuild_balances()
    return [BalanceResponse(**b) for b in balances]


@router.post("/keys", response_model=KeypairResponse)
async def create_keypair(user: User = Depends(get_required_user)):
    """Generate a peer attestation keypair (client-held private key)."""
    priv, pub = generate_keypair()
    return KeypairResponse(private_key=priv, public_key=pub)
