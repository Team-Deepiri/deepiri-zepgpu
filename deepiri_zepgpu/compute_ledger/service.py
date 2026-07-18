"""High-level compute ledger service: genesis, submit, seal, verify, replay."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.compute_ledger.block import GENESIS_PREV_HASH, ComputeBlock
from deepiri_zepgpu.compute_ledger.hashing import canonical_json
from deepiri_zepgpu.compute_ledger.keys import (
    derive_keypair_from_seed,
    public_key_from_private,
    sign_message,
)
from deepiri_zepgpu.compute_ledger.poa import LedgerValidationError, validate_block, validate_transaction
from deepiri_zepgpu.compute_ledger.replay import CreditState, apply_transaction, replay_transactions
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction, TxType
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.models.ledger import LedgerTxType
from deepiri_zepgpu.database.repositories.ledger_repository import LedgerRepository

logger = logging.getLogger(__name__)


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class LedgerService:
    """Permissioned PoA compute ledger backed by Postgres."""

    def __init__(self, db: AsyncSession, chain_id: str | None = None):
        self.db = db
        self.repo = LedgerRepository(db)
        self.chain_id = chain_id or settings.ledger.chain_id

    def validator_keys(self) -> tuple[str, str]:
        """Return (private_b64, public_b64) for the relay PoA validator."""
        if settings.ledger.validator_private_key:
            priv = settings.ledger.validator_private_key.strip()
            return priv, public_key_from_private(priv)
        seed = f"{settings.auth.secret_key}:{self.chain_id}:zepgpu-ledger-validator"
        return derive_keypair_from_seed(seed)

    async def ensure_initialized(self) -> ComputeBlock:
        """Create genesis + register relay validator if the chain is empty."""
        tip = await self.repo.get_tip(self.chain_id)
        if tip:
            return self._block_to_domain(tip)

        priv, pub = self.validator_keys()
        await self.repo.upsert_validator(chain_id=self.chain_id, public_key=pub, label="relay")

        genesis_tx = ComputeTransaction(
            tx_type=TxType.VALIDATOR_REGISTERED,
            sender=pub,
            nonce=0,
            payload={"label": "relay", "role": "poa_validator"},
        )
        genesis_tx.signature = sign_message(priv, canonical_json(genesis_tx.signing_payload()))

        state = CreditState()
        apply_transaction(state, genesis_tx)

        block = ComputeBlock(
            height=0,
            previous_hash=GENESIS_PREV_HASH,
            transactions=[genesis_tx],
            validator=pub,
        )
        block.transactions_root = block.compute_transactions_root()
        block.state_root = state.state_root()
        block.hash = block.compute_hash()
        block.validator_signature = sign_message(priv, block.hash)

        await self._persist_block(block, state)
        await self.db.commit()
        logger.info("Initialized compute ledger genesis for chain %s", self.chain_id)
        return block

    async def submit_transaction(
        self,
        tx: ComputeTransaction,
        *,
        auto_seal: bool | None = None,
        require_signature: bool = True,
    ) -> dict[str, Any]:
        """Validate and queue a transaction; optionally seal into a new block."""
        await self.ensure_initialized()
        validate_transaction(tx, require_signature=require_signature)

        max_nonce = await self.repo.get_max_nonce(self.chain_id, tx.sender)
        if tx.nonce <= max_nonce:
            raise LedgerValidationError(
                f"Nonce {tx.nonce} is not greater than last nonce {max_nonce}"
            )

        await self.repo.add_pending_transaction(
            chain_id=self.chain_id,
            tx_id=tx.id,
            tx_hash=tx.compute_hash(),
            tx_type=LedgerTxType(tx.tx_type.value),
            sender=tx.sender,
            nonce=tx.nonce,
            timestamp=_parse_ts(tx.timestamp),
            payload=tx.payload,
            signature=tx.signature,
        )
        await self.db.flush()

        should_seal = settings.ledger.auto_seal if auto_seal is None else auto_seal
        sealed_block = None
        if should_seal:
            sealed_block = await self.seal_pending()

        return {
            "transaction": tx.to_dict(),
            "block": sealed_block.to_dict() if sealed_block else None,
        }

    async def seal_pending(self) -> ComputeBlock | None:
        """Seal all pending transactions into the next PoA block."""
        await self.ensure_initialized()
        pending = await self.repo.list_pending_transactions(self.chain_id)
        if not pending:
            return None

        tip = await self.repo.get_tip(self.chain_id)
        if tip is None:
            raise LedgerValidationError("Chain has no tip")

        priv, pub = self.validator_keys()
        validators = {v.public_key for v in await self.repo.get_active_validators(self.chain_id)}
        if pub not in validators:
            await self.repo.upsert_validator(chain_id=self.chain_id, public_key=pub, label="relay")
            validators.add(pub)

        txs = [self._row_to_tx(row) for row in pending]
        sealed = await self.repo.list_sealed_transactions(self.chain_id)
        state = replay_transactions([self._row_to_tx(r) for r in sealed])
        for tx in txs:
            apply_transaction(state, tx)

        block = ComputeBlock(
            height=tip.height + 1,
            previous_hash=tip.hash,
            transactions=txs,
            validator=pub,
        )
        block.transactions_root = block.compute_transactions_root()
        block.state_root = state.state_root()
        block.hash = block.compute_hash()
        block.validator_signature = sign_message(priv, block.hash)

        validate_block(
            block,
            authorized_validators=validators,
            expected_previous_hash=tip.hash,
            expected_height=tip.height + 1,
        )
        await self._persist_block(block, state)
        await self.db.commit()
        return block

    async def verify_chain(self) -> dict[str, Any]:
        """Walk the chain and verify hashes, linkage, PoA signatures, and replay."""
        await self.ensure_initialized()
        blocks = await self.repo.list_all_blocks_ascending(self.chain_id)
        validators = {v.public_key for v in await self.repo.get_active_validators(self.chain_id)}

        errors: list[str] = []
        all_txs: list[ComputeTransaction] = []
        prev_hash = GENESIS_PREV_HASH

        for expected_height, row in enumerate(blocks):
            block = self._block_to_domain(row)
            try:
                validate_block(
                    block,
                    authorized_validators=validators,
                    expected_previous_hash=prev_hash,
                    expected_height=expected_height,
                )
            except LedgerValidationError as exc:
                errors.append(f"height={expected_height}: {exc}")
            prev_hash = block.hash
            all_txs.extend(block.transactions)

        try:
            state = replay_transactions(all_txs)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"replay failed: {exc}")
            state = CreditState()

        tip = blocks[-1] if blocks else None
        return {
            "valid": len(errors) == 0,
            "chain_id": self.chain_id,
            "block_count": len(blocks),
            "tip_height": tip.height if tip else -1,
            "tip_hash": tip.hash if tip else None,
            "state_root": state.state_root(),
            "errors": errors,
            "balances": state.to_list(),
        }

    async def rebuild_balances(self) -> list[dict[str, Any]]:
        sealed = await self.repo.list_sealed_transactions(self.chain_id)
        state = replay_transactions([self._row_to_tx(r) for r in sealed])
        await self.repo.replace_balances(self.chain_id, state.to_list())
        await self.db.commit()
        return state.to_list()

    async def record_job_completed(
        self,
        *,
        task_id: str,
        provider_account: str,
        consumer_account: str,
        gpu_seconds: float,
        input_hash: str | None = None,
        output_hash: str | None = None,
        peer_id: str | None = None,
        sign_with_validator: bool = True,
    ) -> dict[str, Any]:
        """Convenience: create a JOB_COMPLETED attestation signed by the relay."""
        await self.ensure_initialized()
        priv, pub = self.validator_keys()
        sender = pub if sign_with_validator else provider_account
        nonce = (await self.repo.get_max_nonce(self.chain_id, sender)) + 1
        tx = ComputeTransaction(
            tx_type=TxType.JOB_COMPLETED,
            sender=sender,
            nonce=nonce,
            payload={
                "task_id": task_id,
                "provider_account": provider_account,
                "consumer_account": consumer_account,
                "gpu_seconds": gpu_seconds,
                "input_hash": input_hash,
                "output_hash": output_hash,
                "peer_id": peer_id,
            },
        )
        tx.signature = sign_message(priv, canonical_json(tx.signing_payload()))
        return await self.submit_transaction(tx)

    async def _persist_block(self, block: ComputeBlock, state: CreditState) -> None:
        from sqlalchemy import select
        from deepiri_zepgpu.database.models.ledger import LedgerTransaction

        for tx in block.transactions:
            existing = await self.db.execute(
                select(LedgerTransaction).where(LedgerTransaction.id == tx.id)
            )
            if existing.scalar_one_or_none() is None:
                await self.repo.add_pending_transaction(
                    chain_id=self.chain_id,
                    tx_id=tx.id,
                    tx_hash=tx.compute_hash(),
                    tx_type=LedgerTxType(tx.tx_type.value),
                    sender=tx.sender,
                    nonce=tx.nonce,
                    timestamp=_parse_ts(tx.timestamp),
                    payload=tx.payload,
                    signature=tx.signature,
                )

        await self.repo.create_block(
            block_id=block.id,
            chain_id=self.chain_id,
            height=block.height,
            block_hash=block.hash,
            previous_hash=block.previous_hash,
            timestamp=_parse_ts(block.timestamp),
            transactions_root=block.transactions_root,
            state_root=block.state_root,
            validator_public_key=block.validator,
            validator_signature=block.validator_signature,
            tx_ids_in_order=[tx.id for tx in block.transactions],
        )
        await self.repo.replace_balances(self.chain_id, state.to_list())
    def _row_to_tx(self, row: Any) -> ComputeTransaction:
        return ComputeTransaction(
            id=str(row.id),
            tx_type=TxType(row.tx_type.value if hasattr(row.tx_type, "value") else row.tx_type),
            sender=row.sender,
            nonce=int(row.nonce),
            timestamp=row.timestamp.isoformat() if isinstance(row.timestamp, datetime) else str(row.timestamp),
            payload=dict(row.payload or {}),
            signature=row.signature,
        )

    def _block_to_domain(self, row: Any) -> ComputeBlock:
        txs = [self._row_to_tx(t) for t in sorted(row.transactions or [], key=lambda x: x.position or 0)]
        return ComputeBlock(
            id=str(row.id),
            height=row.height,
            previous_hash=row.previous_hash,
            timestamp=row.timestamp.isoformat() if isinstance(row.timestamp, datetime) else str(row.timestamp),
            transactions=txs,
            transactions_root=row.transactions_root,
            state_root=row.state_root,
            validator=row.validator_public_key,
            hash=row.hash,
            validator_signature=row.validator_signature,
        )


def new_signed_transaction(
    *,
    private_key_b64: str,
    tx_type: TxType,
    nonce: int,
    payload: dict[str, Any],
    sender: str | None = None,
) -> ComputeTransaction:
    """Helper for callers (API / peers) to build a signed transaction."""
    pub = sender or public_key_from_private(private_key_b64)
    tx = ComputeTransaction(
        id=str(uuid4()),
        tx_type=tx_type,
        sender=pub,
        nonce=nonce,
        payload=payload,
    )
    tx.signature = sign_message(private_key_b64, canonical_json(tx.signing_payload()))
    return tx
