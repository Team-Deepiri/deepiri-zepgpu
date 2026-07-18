"""Repository for compute ledger persistence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from deepiri_zepgpu.database.models.ledger import (
    LedgerBalance,
    LedgerBlock,
    LedgerTransaction,
    LedgerTxType,
    LedgerValidator,
)


class LedgerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_validators(self, chain_id: str) -> list[LedgerValidator]:
        result = await self.db.execute(
            select(LedgerValidator).where(
                LedgerValidator.chain_id == chain_id,
                LedgerValidator.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def upsert_validator(
        self,
        *,
        chain_id: str,
        public_key: str,
        label: str = "relay",
    ) -> LedgerValidator:
        result = await self.db.execute(
            select(LedgerValidator).where(
                LedgerValidator.chain_id == chain_id,
                LedgerValidator.public_key == public_key,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.is_active = True
            existing.label = label
            await self.db.flush()
            return existing
        validator = LedgerValidator(
            id=str(uuid.uuid4()),
            chain_id=chain_id,
            public_key=public_key,
            label=label,
            is_active=True,
        )
        self.db.add(validator)
        await self.db.flush()
        return validator

    async def get_tip(self, chain_id: str) -> Optional[LedgerBlock]:
        result = await self.db.execute(
            select(LedgerBlock)
            .where(LedgerBlock.chain_id == chain_id)
            .order_by(LedgerBlock.height.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_block_by_height(self, chain_id: str, height: int) -> Optional[LedgerBlock]:
        result = await self.db.execute(
            select(LedgerBlock)
            .options(selectinload(LedgerBlock.transactions))
            .where(LedgerBlock.chain_id == chain_id, LedgerBlock.height == height)
        )
        return result.scalar_one_or_none()

    async def get_block_by_hash(self, block_hash: str) -> Optional[LedgerBlock]:
        result = await self.db.execute(
            select(LedgerBlock)
            .options(selectinload(LedgerBlock.transactions))
            .where(LedgerBlock.hash == block_hash)
        )
        return result.scalar_one_or_none()

    async def list_blocks(
        self,
        chain_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[LedgerBlock]:
        result = await self.db.execute(
            select(LedgerBlock)
            .options(selectinload(LedgerBlock.transactions))
            .where(LedgerBlock.chain_id == chain_id)
            .order_by(LedgerBlock.height.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def list_all_blocks_ascending(self, chain_id: str) -> list[LedgerBlock]:
        result = await self.db.execute(
            select(LedgerBlock)
            .options(selectinload(LedgerBlock.transactions))
            .where(LedgerBlock.chain_id == chain_id)
            .order_by(LedgerBlock.height.asc())
        )
        return list(result.scalars().all())

    async def list_pending_transactions(self, chain_id: str) -> list[LedgerTransaction]:
        result = await self.db.execute(
            select(LedgerTransaction)
            .where(
                LedgerTransaction.chain_id == chain_id,
                LedgerTransaction.block_id.is_(None),
            )
            .order_by(LedgerTransaction.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_max_nonce(self, chain_id: str, sender: str) -> int:
        from sqlalchemy import func

        result = await self.db.execute(
            select(func.max(LedgerTransaction.nonce)).where(
                LedgerTransaction.chain_id == chain_id,
                LedgerTransaction.sender == sender,
            )
        )
        value = result.scalar_one_or_none()
        return int(value) if value is not None else -1

    async def add_pending_transaction(
        self,
        *,
        chain_id: str,
        tx_id: str,
        tx_hash: str,
        tx_type: LedgerTxType,
        sender: str,
        nonce: int,
        timestamp: datetime,
        payload: dict[str, Any],
        signature: str,
    ) -> LedgerTransaction:
        row = LedgerTransaction(
            id=tx_id,
            chain_id=chain_id,
            tx_hash=tx_hash,
            tx_type=tx_type,
            sender=sender,
            nonce=nonce,
            timestamp=timestamp,
            payload=payload,
            signature=signature,
            block_id=None,
            position=None,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def create_block(
        self,
        *,
        block_id: str,
        chain_id: str,
        height: int,
        block_hash: str,
        previous_hash: str,
        timestamp: datetime,
        transactions_root: str,
        state_root: str,
        validator_public_key: str,
        validator_signature: str,
        tx_ids_in_order: list[str],
    ) -> LedgerBlock:
        block = LedgerBlock(
            id=block_id,
            chain_id=chain_id,
            height=height,
            hash=block_hash,
            previous_hash=previous_hash,
            timestamp=timestamp,
            transactions_root=transactions_root,
            state_root=state_root,
            validator_public_key=validator_public_key,
            validator_signature=validator_signature,
        )
        self.db.add(block)
        await self.db.flush()
        for position, tx_id in enumerate(tx_ids_in_order):
            await self.db.execute(
                update(LedgerTransaction)
                .where(LedgerTransaction.id == tx_id)
                .values(block_id=block_id, position=position)
            )
        await self.db.flush()
        return block

    async def replace_balances(
        self,
        chain_id: str,
        balances: list[dict[str, Any]],
    ) -> None:
        existing = await self.db.execute(
            select(LedgerBalance).where(LedgerBalance.chain_id == chain_id)
        )
        for row in existing.scalars().all():
            await self.db.delete(row)
        await self.db.flush()
        for item in balances:
            self.db.add(
                LedgerBalance(
                    id=str(uuid.uuid4()),
                    chain_id=chain_id,
                    account=item["account"],
                    credit_seconds=float(item["credit_seconds"]),
                    debit_seconds=float(item["debit_seconds"]),
                )
            )
        await self.db.flush()

    async def list_balances(self, chain_id: str) -> list[LedgerBalance]:
        result = await self.db.execute(
            select(LedgerBalance)
            .where(LedgerBalance.chain_id == chain_id)
            .order_by(LedgerBalance.account.asc())
        )
        return list(result.scalars().all())

    async def get_balance(self, chain_id: str, account: str) -> Optional[LedgerBalance]:
        result = await self.db.execute(
            select(LedgerBalance).where(
                LedgerBalance.chain_id == chain_id,
                LedgerBalance.account == account,
            )
        )
        return result.scalar_one_or_none()

    async def list_sealed_transactions(self, chain_id: str) -> list[LedgerTransaction]:
        result = await self.db.execute(
            select(LedgerTransaction)
            .join(LedgerBlock, LedgerTransaction.block_id == LedgerBlock.id)
            .where(LedgerTransaction.chain_id == chain_id)
            .order_by(LedgerBlock.height.asc(), LedgerTransaction.position.asc())
        )
        return list(result.scalars().all())
