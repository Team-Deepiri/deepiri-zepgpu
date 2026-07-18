"""High-level compute ledger service: genesis, quorum seal, verify, merkle proofs."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.compute_ledger.block import GENESIS_PREV_HASH, ComputeBlock, ValidatorApproval
from deepiri_zepgpu.compute_ledger.chain_id import chain_id_for_network, parse_network_id
from deepiri_zepgpu.compute_ledger.hashing import canonical_json, sha256_hex
from deepiri_zepgpu.compute_ledger.keys import (
    derive_keypair_from_seed,
    public_key_from_private,
    sign_message,
)
from deepiri_zepgpu.compute_ledger.merkle import merkle_proof, verify_merkle_proof
from deepiri_zepgpu.compute_ledger.poa import (
    LedgerValidationError,
    add_approval,
    validate_block,
    validate_transaction,
)
from deepiri_zepgpu.compute_ledger.replay import CreditState, apply_transaction, replay_transactions
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction, TxType
from deepiri_zepgpu.config import settings
from deepiri_zepgpu.database.models.ledger import LedgerTxType
from deepiri_zepgpu.database.repositories.ledger_repository import LedgerRepository

logger = logging.getLogger(__name__)


def _parse_ts(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class LedgerService:
    """Permissioned PoA compute ledger backed by Postgres."""

    def __init__(
        self,
        db: AsyncSession,
        chain_id: str | None = None,
        *,
        network_id: str | None = None,
    ):
        self.db = db
        self.repo = LedgerRepository(db)
        self.network_id = network_id
        self.chain_id = chain_id or chain_id_for_network(network_id)
        if network_id is None:
            self.network_id = parse_network_id(self.chain_id)

    @property
    def quorum_threshold(self) -> int:
        return max(1, int(settings.ledger.quorum_threshold))

    def validator_keys(self) -> tuple[str, str]:
        """Return (private_b64, public_b64) for the relay PoA validator."""
        if settings.ledger.validator_private_key:
            priv = settings.ledger.validator_private_key.strip()
            return priv, public_key_from_private(priv)
        seed = f"{settings.auth.secret_key}:{self.chain_id}:zepgpu-ledger-validator"
        return derive_keypair_from_seed(seed)

    def extra_validator_keys(self) -> list[tuple[str, str]]:
        """Optional extra PoA validators from config (dev/demo quorum)."""
        raw = (settings.ledger.extra_validator_private_keys or "").strip()
        if not raw:
            return []
        pairs: list[tuple[str, str]] = []
        for part in raw.split(","):
            priv = part.strip()
            if not priv:
                continue
            pairs.append((priv, public_key_from_private(priv)))
        return pairs

    async def ensure_initialized(self) -> ComputeBlock:
        """Create genesis + register relay (+ extra) validators if chain empty."""
        tip = await self.repo.get_tip(self.chain_id, finalized_only=False)
        if tip:
            return self._block_to_domain(tip)

        priv, pub = self.validator_keys()
        await self.repo.upsert_validator(
            chain_id=self.chain_id,
            public_key=pub,
            label="relay",
            vpn_network_id=self.network_id,
        )
        for i, (_, extra_pub) in enumerate(self.extra_validator_keys()):
            await self.repo.upsert_validator(
                chain_id=self.chain_id,
                public_key=extra_pub,
                label=f"extra-{i}",
                vpn_network_id=self.network_id,
            )

        genesis_tx = ComputeTransaction(
            tx_type=TxType.VALIDATOR_REGISTERED,
            sender=pub,
            nonce=0,
            payload={"label": "relay", "role": "poa_validator", "network_id": self.network_id},
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
        block.ensure_proposer_approval()
        # Auto-cosign with extra validators so genesis finalizes under higher quorum.
        for extra_priv, extra_pub in self.extra_validator_keys():
            block.approvals.append(
                ValidatorApproval(
                    validator=extra_pub,
                    signature=sign_message(extra_priv, block.hash),
                )
            )
        block.finalized = len(block.approvals) >= self.quorum_threshold

        validators = {v.public_key for v in await self.repo.get_active_validators(self.chain_id)}
        validate_block(
            block,
            authorized_validators=validators,
            expected_previous_hash=GENESIS_PREV_HASH,
            expected_height=0,
            quorum_threshold=self.quorum_threshold if block.finalized else 1,
            require_quorum=block.finalized,
        )
        await self._persist_block(block, state if block.finalized else None)
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
            vpn_network_id=self.network_id,
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
        """Propose/seal pending txs. Finalizes immediately when quorum is met."""
        await self.ensure_initialized()
        unfinalized = await self.repo.get_unfinalized_tip(self.chain_id)
        if unfinalized is not None:
            raise LedgerValidationError(
                "Cannot seal while an unfinalized block awaits quorum approvals"
            )

        pending = await self.repo.list_pending_transactions(self.chain_id)
        if not pending:
            return None

        tip = await self.repo.get_tip(self.chain_id, finalized_only=True)
        if tip is None:
            raise LedgerValidationError("Chain has no finalized tip")

        priv, pub = self.validator_keys()
        validators = {v.public_key for v in await self.repo.get_active_validators(self.chain_id)}
        if pub not in validators:
            await self.repo.upsert_validator(
                chain_id=self.chain_id,
                public_key=pub,
                label="relay",
                vpn_network_id=self.network_id,
            )
            validators.add(pub)

        txs = [self._row_to_tx(row) for row in pending]
        sealed = await self.repo.list_sealed_transactions(self.chain_id, finalized_only=True)
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
        block.ensure_proposer_approval()

        # Dev convenience: auto-cosign with configured extra validators.
        for extra_priv, extra_pub in self.extra_validator_keys():
            if extra_pub in {a.validator for a in block.approvals}:
                continue
            if extra_pub not in validators:
                await self.repo.upsert_validator(
                    chain_id=self.chain_id,
                    public_key=extra_pub,
                    label="extra",
                    vpn_network_id=self.network_id,
                )
                validators.add(extra_pub)
            block.approvals.append(
                ValidatorApproval(
                    validator=extra_pub,
                    signature=sign_message(extra_priv, block.hash),
                )
            )

        block.finalized = len(block.approvals) >= self.quorum_threshold
        validate_block(
            block,
            authorized_validators=validators,
            expected_previous_hash=tip.hash,
            expected_height=tip.height + 1,
            quorum_threshold=self.quorum_threshold if block.finalized else 1,
            require_quorum=block.finalized,
        )
        await self._persist_block(block, state if block.finalized else None)
        await self.db.commit()
        return block

    async def approve_block(
        self,
        block_hash: str,
        *,
        validator_public_key: str,
        signature: str,
    ) -> ComputeBlock:
        """Add a PoA approval; finalize and apply balances when quorum is reached."""
        await self.ensure_initialized()
        row = await self.repo.get_block_by_hash(block_hash)
        if not row or row.chain_id != self.chain_id:
            raise LedgerValidationError("Block not found")
        block = self._block_to_domain(row)
        if block.finalized:
            raise LedgerValidationError("Block already finalized")

        validators = {v.public_key for v in await self.repo.get_active_validators(self.chain_id)}
        add_approval(
            block,
            validator_public_key=validator_public_key,
            signature=signature,
            authorized_validators=validators,
        )
        block.finalized = len(block.approvals) >= self.quorum_threshold

        if block.finalized:
            validate_block(
                block,
                authorized_validators=validators,
                quorum_threshold=self.quorum_threshold,
            )
            sealed = await self.repo.list_sealed_transactions(self.chain_id, finalized_only=True)
            # Include this block's txs (not yet finalized in DB)
            prior = [self._row_to_tx(r) for r in sealed]
            state = replay_transactions(prior + block.transactions)
            await self.repo.update_block_approvals(
                block.id,
                approvals=[a.to_dict() for a in block.approvals],
                finalized=True,
            )
            await self.repo.replace_balances(
                self.chain_id,
                state.to_list(),
                vpn_network_id=self.network_id,
            )
        else:
            await self.repo.update_block_approvals(
                block.id,
                approvals=[a.to_dict() for a in block.approvals],
                finalized=False,
            )
        await self.db.commit()
        return block

    async def approve_block_as_relay(self, block_hash: str) -> ComputeBlock:
        """Convenience: sign approval with the local relay validator key."""
        priv, pub = self.validator_keys()
        sig = sign_message(priv, block_hash)
        return await self.approve_block(block_hash, validator_public_key=pub, signature=sig)

    async def verify_chain(self) -> dict[str, Any]:
        await self.ensure_initialized()
        blocks = await self.repo.list_all_blocks_ascending(self.chain_id)
        validators = {v.public_key for v in await self.repo.get_active_validators(self.chain_id)}

        errors: list[str] = []
        all_txs: list[ComputeTransaction] = []
        prev_hash = GENESIS_PREV_HASH

        for expected_height, row in enumerate(blocks):
            block = self._block_to_domain(row)
            # Finalized history is checked for crypto integrity of its approval set.
            # Current settings.ledger.quorum_threshold applies to new seals, not retroactively.
            if block.finalized:
                effective_quorum = max(1, len(block.approvals))
                require_quorum = True
            else:
                effective_quorum = 1
                require_quorum = False
            try:
                validate_block(
                    block,
                    authorized_validators=validators,
                    expected_previous_hash=prev_hash,
                    expected_height=expected_height,
                    quorum_threshold=effective_quorum,
                    require_quorum=require_quorum,
                )
            except LedgerValidationError as exc:
                errors.append(f"height={expected_height}: {exc}")
            prev_hash = block.hash
            if block.finalized:
                all_txs.extend(block.transactions)

        try:
            state = replay_transactions(all_txs)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"replay failed: {exc}")
            state = CreditState()

        tip = await self.repo.get_tip(self.chain_id, finalized_only=True)
        return {
            "valid": len(errors) == 0,
            "chain_id": self.chain_id,
            "network_id": self.network_id,
            "block_count": len(blocks),
            "tip_height": tip.height if tip else -1,
            "tip_hash": tip.hash if tip else None,
            "quorum_threshold": self.quorum_threshold,
            "state_root": state.state_root(),
            "errors": errors,
            "balances": state.to_list(),
        }

    async def rebuild_balances(self) -> list[dict[str, Any]]:
        sealed = await self.repo.list_sealed_transactions(self.chain_id, finalized_only=True)
        state = replay_transactions([self._row_to_tx(r) for r in sealed])
        await self.repo.replace_balances(
            self.chain_id, state.to_list(), vpn_network_id=self.network_id
        )
        await self.db.commit()
        return state.to_list()

    async def get_inclusion_proof(self, block_hash: str, tx_hash: str) -> dict[str, Any]:
        row = await self.repo.get_block_by_hash(block_hash)
        if not row or row.chain_id != self.chain_id:
            raise LedgerValidationError("Block not found")
        block = self._block_to_domain(row)
        leaves = block.leaf_hashes()
        try:
            index = leaves.index(tx_hash)
        except ValueError as exc:
            raise LedgerValidationError("Transaction not in block") from exc
        proof = merkle_proof(leaves, index)
        return {
            "block_hash": block.hash,
            "block_height": block.height,
            "transactions_root": block.transactions_root,
            "proof": proof.to_dict(),
            "valid": verify_merkle_proof(proof),
        }

    async def export_headers(
        self,
        *,
        from_height: int = 0,
        limit: int = 100,
        finalized_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Export compact headers for light-client sync."""
        from deepiri_zepgpu.compute_ledger.light_client import BlockHeader

        await self.ensure_initialized()
        rows = await self.repo.list_all_blocks_ascending(self.chain_id)
        headers: list[dict[str, Any]] = []
        for row in rows:
            if row.height < from_height:
                continue
            if finalized_only and not bool(getattr(row, "finalized", True)):
                continue
            block = self._block_to_domain(row)
            headers.append(BlockHeader.from_block(block).to_dict())
            if len(headers) >= limit:
                break
        return headers

    async def verify_headers_payload(
        self,
        headers: list[dict[str, Any]],
        *,
        from_height: int | None = None,
    ) -> dict[str, Any]:
        from deepiri_zepgpu.compute_ledger.light_client import BlockHeader, verify_header_chain

        await self.ensure_initialized()
        validators = {v.public_key for v in await self.repo.get_active_validators(self.chain_id)}
        parsed = [BlockHeader.from_dict(h) for h in headers]
        result = verify_header_chain(
            parsed,
            authorized_validators=validators,
            quorum_threshold=self.quorum_threshold,
            from_height=from_height,
        )
        result["chain_id"] = self.chain_id
        result["network_id"] = self.network_id
        return result

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
        sender_private_key: str | None = None,
    ) -> dict[str, Any]:
        await self.ensure_initialized()
        if sender_private_key:
            priv = sender_private_key
            pub = public_key_from_private(priv)
            sender = pub
        elif sign_with_validator:
            priv, pub = self.validator_keys()
            sender = pub
        else:
            raise LedgerValidationError("sender_private_key required when not signing as validator")

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
                "network_id": self.network_id,
            },
        )
        tx.signature = sign_message(priv, canonical_json(tx.signing_payload()))
        return await self.submit_transaction(tx)

    async def submit_peer_attestation(
        self,
        *,
        peer_public_key: str,
        signed_tx: ComputeTransaction,
    ) -> dict[str, Any]:
        """Accept a peer-signed JOB_COMPLETED (sender must match peer_public_key)."""
        if signed_tx.sender != peer_public_key:
            raise LedgerValidationError("Transaction sender must match peer public key")
        if signed_tx.tx_type != TxType.JOB_COMPLETED:
            raise LedgerValidationError("Peer attestation must be JOB_COMPLETED")
        return await self.submit_transaction(signed_tx)

    async def _persist_block(
        self,
        block: ComputeBlock,
        state: CreditState | None,
    ) -> None:
        from sqlalchemy import select

        from deepiri_zepgpu.database.models.ledger import LedgerTransaction
        from deepiri_zepgpu.database.uuid_util import as_uuid

        for tx in block.transactions:
            tx_uuid = as_uuid(tx.id)
            existing = await self.db.execute(
                select(LedgerTransaction).where(LedgerTransaction.id == tx_uuid)
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
                    vpn_network_id=self.network_id,
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
            approvals=[a.to_dict() for a in block.approvals],
            finalized=block.finalized,
            vpn_network_id=self.network_id,
        )
        if state is not None and block.finalized:
            await self.repo.replace_balances(
                self.chain_id, state.to_list(), vpn_network_id=self.network_id
            )

    def _row_to_tx(self, row: Any) -> ComputeTransaction:
        return ComputeTransaction(
            id=str(row.id),
            tx_type=TxType(row.tx_type.value if hasattr(row.tx_type, "value") else row.tx_type),
            sender=row.sender,
            nonce=int(row.nonce),
            timestamp=(
                row.timestamp.isoformat()
                if isinstance(row.timestamp, datetime)
                else str(row.timestamp)
            ),
            payload=dict(row.payload or {}),
            signature=row.signature,
        )

    def _block_to_domain(self, row: Any) -> ComputeBlock:
        txs = [
            self._row_to_tx(t)
            for t in sorted(row.transactions or [], key=lambda x: x.position or 0)
        ]
        approvals_raw = row.approvals or []
        approvals = [
            ValidatorApproval.from_dict(a) if isinstance(a, dict) else a for a in approvals_raw
        ]
        return ComputeBlock(
            id=str(row.id),
            height=row.height,
            previous_hash=row.previous_hash,
            timestamp=(
                row.timestamp.isoformat()
                if isinstance(row.timestamp, datetime)
                else str(row.timestamp)
            ),
            transactions=txs,
            transactions_root=row.transactions_root,
            state_root=row.state_root,
            validator=row.validator_public_key,
            hash=row.hash,
            validator_signature=row.validator_signature,
            approvals=approvals,
            finalized=bool(getattr(row, "finalized", True)),
        )


def new_signed_transaction(
    *,
    private_key_b64: str,
    tx_type: TxType,
    nonce: int,
    payload: dict[str, Any],
    sender: str | None = None,
) -> ComputeTransaction:
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


def hash_result_attestation(
    *,
    task_id: str,
    peer_id: str,
    success: bool,
    execution_time: float,
    result_digest: str | None,
) -> str:
    """Canonical digest peers sign for remote job completion."""
    return sha256_hex(
        canonical_json(
            {
                "task_id": task_id,
                "peer_id": peer_id,
                "success": success,
                "execution_time": execution_time,
                "result_digest": result_digest,
            }
        )
    )
