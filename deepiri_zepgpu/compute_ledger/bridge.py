"""Cross-network credit bridge (burn on source, mint on destination)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.compute_ledger.hashing import canonical_json, sha256_hex
from deepiri_zepgpu.compute_ledger.light_client import BlockHeader, verify_tx_inclusion
from deepiri_zepgpu.compute_ledger.poa import LedgerValidationError
from deepiri_zepgpu.compute_ledger.service import LedgerService, new_signed_transaction
from deepiri_zepgpu.compute_ledger.transaction import TxType

logger = logging.getLogger(__name__)


def bridge_receipt_id(
    *,
    source_chain_id: str,
    burn_tx_hash: str,
    account: str,
    amount_seconds: float,
) -> str:
    return sha256_hex(
        canonical_json(
            {
                "source_chain_id": source_chain_id,
                "burn_tx_hash": burn_tx_hash,
                "account": account,
                "amount_seconds": amount_seconds,
            }
        )
    )


class BridgeService:
    """Permissioned bridge between VPN-scoped (or global) compute ledgers."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def transfer(
        self,
        *,
        source_network_id: str | None,
        dest_network_id: str | None,
        account: str,
        amount_seconds: float,
        memo: str | None = None,
    ) -> dict[str, Any]:
        if amount_seconds <= 0:
            raise LedgerValidationError("amount_seconds must be positive")
        if source_network_id == dest_network_id and (source_network_id is not None):
            # Allow global↔network; same-network is pointless
            pass
        src = LedgerService(self.db, network_id=source_network_id)
        dst = LedgerService(self.db, network_id=dest_network_id)
        if src.chain_id == dst.chain_id:
            raise LedgerValidationError("Source and destination chains must differ")

        await src.ensure_initialized()
        await dst.ensure_initialized()

        # Check source balance (credits - debits)
        bal = await src.repo.get_balance(src.chain_id, account)
        net = (bal.credit_seconds - bal.debit_seconds) if bal else 0.0
        if net < amount_seconds:
            raise LedgerValidationError(
                f"Insufficient balance on source chain: have {net}, need {amount_seconds}"
            )

        priv, pub = src.validator_keys()
        burn_nonce = (await src.repo.get_max_nonce(src.chain_id, pub)) + 1
        burn_tx = new_signed_transaction(
            private_key_b64=priv,
            tx_type=TxType.BRIDGE_BURN,
            nonce=burn_nonce,
            payload={
                "account": account,
                "amount_seconds": amount_seconds,
                "dest_chain_id": dst.chain_id,
                "dest_network_id": dest_network_id,
                "memo": memo,
                "bridge_id": str(uuid4()),
            },
            sender=pub,
        )
        burn_result = await src.submit_transaction(burn_tx)
        burn_block = burn_result.get("block")
        if not burn_block or burn_block.get("finalized") is not True:
            raise LedgerValidationError(
                "Burn block not finalized; increase quorum cosigners or approve first"
            )

        burn_hash = burn_tx.compute_hash()
        proof = await src.get_inclusion_proof(burn_block["hash"], burn_hash)
        receipt = bridge_receipt_id(
            source_chain_id=src.chain_id,
            burn_tx_hash=burn_hash,
            account=account,
            amount_seconds=amount_seconds,
        )

        # Replay protection: reject if mint already used this receipt on dest
        sealed = await dst.repo.list_sealed_transactions(dst.chain_id, finalized_only=True)
        for row in sealed:
            if (
                row.tx_type.value == TxType.BRIDGE_MINT.value
                and (row.payload or {}).get("receipt_id") == receipt
            ):
                raise LedgerValidationError("Bridge receipt already minted on destination")

        dst_priv, dst_pub = dst.validator_keys()
        mint_nonce = (await dst.repo.get_max_nonce(dst.chain_id, dst_pub)) + 1
        mint_tx = new_signed_transaction(
            private_key_b64=dst_priv,
            tx_type=TxType.BRIDGE_MINT,
            nonce=mint_nonce,
            payload={
                "account": account,
                "amount_seconds": amount_seconds,
                "source_chain_id": src.chain_id,
                "source_network_id": source_network_id,
                "burn_tx_hash": burn_hash,
                "burn_block_hash": burn_block["hash"],
                "burn_block_height": burn_block["height"],
                "receipt_id": receipt,
                "inclusion_proof": proof["proof"],
                "memo": memo,
            },
            sender=dst_pub,
        )

        # Offline-style check before mint
        header = BlockHeader.from_dict(
            {
                "height": burn_block["height"],
                "hash": burn_block["hash"],
                "previous_hash": burn_block["previous_hash"],
                "timestamp": burn_block["timestamp"],
                "transactions_root": burn_block["transactions_root"],
                "state_root": burn_block["state_root"],
                "validator": burn_block["validator"],
                "validator_signature": burn_block["validator_signature"],
                "approvals": burn_block.get("approvals") or [],
                "finalized": bool(burn_block.get("finalized")),
            }
        )
        if not verify_tx_inclusion(header=header, proof=proof["proof"]):
            raise LedgerValidationError("Burn inclusion proof failed verification")

        mint_result = await dst.submit_transaction(mint_tx)
        return {
            "receipt_id": receipt,
            "source_chain_id": src.chain_id,
            "dest_chain_id": dst.chain_id,
            "account": account,
            "amount_seconds": amount_seconds,
            "burn": burn_result,
            "mint": mint_result,
            "inclusion_proof": proof,
        }
