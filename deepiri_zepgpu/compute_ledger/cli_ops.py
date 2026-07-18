"""CLI helpers for compute ledger status / verify / sync (async)."""

from __future__ import annotations

import json

from deepiri_zepgpu.compute_ledger.service import LedgerService
from deepiri_zepgpu.database.session import get_db_context


async def ledger_status(network_id: str | None = None) -> dict:
    async with get_db_context() as db:
        service = LedgerService(db, network_id=network_id)
        await service.ensure_initialized()
        tip = await service.repo.get_tip(service.chain_id, finalized_only=True)
        pending = await service.repo.list_pending_transactions(service.chain_id)
        unfinalized = await service.repo.get_unfinalized_tip(service.chain_id)
        _, pub = service.validator_keys()
        return {
            "chain_id": service.chain_id,
            "network_id": service.network_id,
            "tip_height": tip.height if tip else -1,
            "tip_hash": tip.hash if tip else None,
            "pending_count": len(pending),
            "unfinalized": bool(unfinalized),
            "quorum_threshold": service.quorum_threshold,
            "validator_public_key": pub,
        }


async def ledger_verify(network_id: str | None = None) -> dict:
    async with get_db_context() as db:
        service = LedgerService(db, network_id=network_id)
        return await service.verify_chain()


async def ledger_sync_headers(
    network_id: str | None = None,
    from_height: int = 0,
    limit: int = 100,
) -> dict:
    async with get_db_context() as db:
        service = LedgerService(db, network_id=network_id)
        headers = await service.export_headers(from_height=from_height, limit=limit)
        return {
            "chain_id": service.chain_id,
            "network_id": service.network_id,
            "from_height": from_height,
            "count": len(headers),
            "headers": headers,
        }


async def ledger_revolution_audit(*, include_db: bool = True) -> dict:
    """Run golden + adversary + multi-network economy audit."""
    from deepiri_zepgpu.compute_ledger.revolution import run_revolution_audit

    if not include_db:
        result = await run_revolution_audit(None, include_db=False)
        return result.to_dict()
    async with get_db_context() as db:
        result = await run_revolution_audit(db, include_db=True)
        return result.to_dict()


def dump_json(obj: dict) -> None:
    print(json.dumps(obj, indent=2, default=str))
