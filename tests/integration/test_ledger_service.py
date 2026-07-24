"""Integration tests: LedgerService against real Postgres."""

from __future__ import annotations

import pytest

from deepiri_zepgpu.compute_ledger.service import LedgerService
from deepiri_zepgpu.config import settings

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_genesis_attest_verify_merkle(db_session, unique_chain_id):
    settings.ledger.chain_id = unique_chain_id
    settings.ledger.quorum_threshold = 1
    settings.ledger.auto_seal = True

    service = LedgerService(db_session, chain_id=unique_chain_id)
    genesis = await service.ensure_initialized()
    assert genesis.height == 0
    assert genesis.finalized is True

    result = await service.record_job_completed(
        task_id="task-1",
        provider_account="provider-a",
        consumer_account="consumer-b",
        gpu_seconds=12.5,
    )
    assert result["block"] is not None
    assert result["block"]["height"] == 1
    assert result["block"]["finalized"] is True

    verify = await service.verify_chain()
    assert verify["valid"] is True
    assert verify["tip_height"] == 1

    balances = {b["account"]: b for b in verify["balances"]}
    assert balances["provider-a"]["credit_seconds"] == 12.5
    assert balances["consumer-b"]["debit_seconds"] == 12.5

    block = result["block"]
    tx_hash = None
    for tx in block["transactions"]:
        from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction

        ct = ComputeTransaction.from_dict(tx)
        tx_hash = ct.compute_hash()
        break
    assert tx_hash
    proof = await service.get_inclusion_proof(block["hash"], tx_hash)
    assert proof["valid"] is True


@pytest.mark.asyncio
async def test_light_client_header_sync(db_session, unique_chain_id):
    settings.ledger.chain_id = unique_chain_id
    service = LedgerService(db_session, chain_id=unique_chain_id)
    await service.ensure_initialized()
    await service.record_job_completed(
        task_id="t2",
        provider_account="p",
        consumer_account="c",
        gpu_seconds=1.0,
    )

    headers = await service.export_headers(from_height=0, limit=10)
    assert len(headers) >= 2
    checked = await service.verify_headers_payload(headers, from_height=0)
    assert checked["valid"] is True
    assert checked["tip_height"] >= 1


@pytest.mark.asyncio
async def test_quorum_unfinalized_then_approve(db_session, unique_chain_id):
    from deepiri_zepgpu.compute_ledger.keys import generate_keypair, sign_message

    settings.ledger.chain_id = unique_chain_id
    settings.ledger.quorum_threshold = 1
    settings.ledger.auto_seal = True
    settings.ledger.extra_validator_private_keys = ""

    service = LedgerService(db_session, chain_id=unique_chain_id)
    await service.ensure_initialized()

    priv2, pub2 = generate_keypair()
    await service.repo.upsert_validator(chain_id=unique_chain_id, public_key=pub2, label="second")
    await db_session.commit()

    settings.ledger.quorum_threshold = 2
    result = await service.record_job_completed(
        task_id="q1",
        provider_account="prov",
        consumer_account="cons",
        gpu_seconds=3.0,
    )
    block = result["block"]
    assert block is not None
    assert block.get("finalized") is False

    sig = sign_message(priv2, block["hash"])
    finalized = await service.approve_block(
        block["hash"],
        validator_public_key=pub2,
        signature=sig,
    )
    assert finalized.finalized is True
    verify = await service.verify_chain()
    assert verify["valid"] is True

    settings.ledger.quorum_threshold = 1


@pytest.mark.asyncio
async def test_bridge_transfer_between_chains(db_session, unique_chain_id):
    from deepiri_zepgpu.compute_ledger.bridge import BridgeService

    settings.ledger.quorum_threshold = 1
    src_id = f"{unique_chain_id}-src"
    dst_id = f"{unique_chain_id}-dst"

    src = LedgerService(db_session, chain_id=src_id)
    dst = LedgerService(db_session, chain_id=dst_id)
    await src.ensure_initialized()
    await dst.ensure_initialized()

    await src.record_job_completed(
        task_id="earn",
        provider_account="bridger",
        consumer_account="payer",
        gpu_seconds=10.0,
    )

    # BridgeService uses network_id -> chain_id_for_network; for direct chains
    # call burn/mint via two LedgerServices by temporarily using network ids.
    # Use BridgeService with network ids that map to unique chains via settings base.
    settings.ledger.chain_id = unique_chain_id
    net_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    net_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    a = LedgerService(db_session, network_id=net_a)
    b = LedgerService(db_session, network_id=net_b)
    await a.ensure_initialized()
    await b.ensure_initialized()
    await a.record_job_completed(
        task_id="earn2",
        provider_account="bridger",
        consumer_account="payer",
        gpu_seconds=8.0,
    )

    bridge = BridgeService(db_session)
    out = await bridge.transfer(
        source_network_id=net_a,
        dest_network_id=net_b,
        account="bridger",
        amount_seconds=3.0,
        memo="itest",
    )
    assert out["receipt_id"]
    assert out["amount_seconds"] == 3.0

    a_verify = await a.verify_chain()
    b_verify = await b.verify_chain()
    assert a_verify["valid"] and b_verify["valid"]
    a_bal = {x["account"]: x for x in a_verify["balances"]}
    b_bal = {x["account"]: x for x in b_verify["balances"]}
    assert a_bal["bridger"]["net_seconds"] == 5.0  # 8 - 3
    assert b_bal["bridger"]["credit_seconds"] == 3.0

    with pytest.raises(ValueError):
        await bridge.transfer(
            source_network_id=net_a,
            dest_network_id=net_b,
            account="bridger",
            amount_seconds=99.0,
            memo="too-much",
        )
