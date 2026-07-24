"""Integration tests: FastAPI /api/v1/ledger against Postgres."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_api_status_attest_verify_proof(api_client):
    status = await api_client.get("/api/v1/ledger/status")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["enabled"] is True
    assert body["tip_height"] >= 0
    assert body["quorum_threshold"] >= 1

    attest = await api_client.post(
        "/api/v1/ledger/attestations/job-completed",
        json={
            "task_id": "api-task-1",
            "provider_account": "api-provider",
            "consumer_account": "api-consumer",
            "gpu_seconds": 4.0,
        },
    )
    assert attest.status_code == 200, attest.text
    payload = attest.json()
    assert payload["block"] is not None
    block = payload["block"]
    assert block["height"] >= 1
    assert block["finalized"] is True

    verify = await api_client.get("/api/v1/ledger/verify")
    assert verify.status_code == 200
    assert verify.json()["valid"] is True

    balances = await api_client.get("/api/v1/ledger/balances")
    assert balances.status_code == 200
    accounts = {b["account"]: b for b in balances.json()}
    assert accounts["api-provider"]["credit_seconds"] == 4.0

    # Merkle proof for first tx in block
    tx = block["transactions"][0]
    from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction

    tx_hash = ComputeTransaction.from_dict(tx).compute_hash()
    proof = await api_client.get(f"/api/v1/ledger/blocks/hash/{block['hash']}/proof/{tx_hash}")
    assert proof.status_code == 200, proof.text
    assert proof.json()["valid"] is True


@pytest.mark.asyncio
async def test_api_sync_headers_roundtrip(api_client):
    await api_client.post(
        "/api/v1/ledger/attestations/job-completed",
        json={
            "task_id": "sync-1",
            "provider_account": "p",
            "consumer_account": "c",
            "gpu_seconds": 1.0,
        },
    )
    headers_resp = await api_client.get("/api/v1/ledger/sync/headers?from_height=0&limit=50")
    assert headers_resp.status_code == 200, headers_resp.text
    data = headers_resp.json()
    assert data["count"] >= 1

    checked = await api_client.post(
        "/api/v1/ledger/sync/verify-headers",
        json={"headers": data["headers"], "from_height": 0},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["valid"] is True


@pytest.mark.asyncio
async def test_api_bridge_transfer(api_client):
    net_a = "11111111-1111-1111-1111-111111111111"
    net_b = "22222222-2222-2222-2222-222222222222"

    # Seed credits on network A
    seed = await api_client.post(
        f"/api/v1/ledger/attestations/job-completed?network_id={net_a}",
        json={
            "task_id": "bridge-seed",
            "provider_account": "bridge-user",
            "consumer_account": "payer",
            "gpu_seconds": 9.0,
        },
    )
    assert seed.status_code == 200, seed.text

    # Ensure dest chain exists
    dest_status = await api_client.get(f"/api/v1/ledger/status?network_id={net_b}")
    assert dest_status.status_code == 200, dest_status.text

    bridged = await api_client.post(
        "/api/v1/ledger/bridge/transfer",
        json={
            "source_network_id": net_a,
            "dest_network_id": net_b,
            "account": "bridge-user",
            "amount_seconds": 2.5,
            "memo": "api-itest",
        },
    )
    assert bridged.status_code == 200, bridged.text
    body = bridged.json()
    assert body["amount_seconds"] == 2.5
    assert body["receipt_id"]

    src_bal = await api_client.get(f"/api/v1/ledger/balances/bridge-user?network_id={net_a}")
    dst_bal = await api_client.get(f"/api/v1/ledger/balances/bridge-user?network_id={net_b}")
    assert src_bal.status_code == 200
    assert dst_bal.status_code == 200
    assert src_bal.json()["net_seconds"] == 6.5
    assert dst_bal.json()["credit_seconds"] == 2.5
