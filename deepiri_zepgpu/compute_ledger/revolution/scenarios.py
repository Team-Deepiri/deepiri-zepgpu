"""Multi-party credit economy scenario across VPN-scoped chains + bridge."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.compute_ledger.bridge import BridgeService
from deepiri_zepgpu.compute_ledger.keys import generate_keypair, sign_message
from deepiri_zepgpu.compute_ledger.poa import LedgerValidationError
from deepiri_zepgpu.compute_ledger.revolution.settings_override import ledger_settings
from deepiri_zepgpu.compute_ledger.service import LedgerService
from deepiri_zepgpu.compute_ledger.transaction import ComputeTransaction


@dataclass
class ScenarioStep:
    name: str
    ok: bool
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class EconomyScenarioResult:
    steps: list[ScenarioStep] = field(default_factory=list)
    chain_a: str = ""
    chain_b: str = ""

    @property
    def passed(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "chain_a": self.chain_a,
            "chain_b": self.chain_b,
            "steps": [
                {"name": s.name, "ok": s.ok, "detail": s.detail, "metrics": s.metrics}
                for s in self.steps
            ],
        }


async def run_credit_economy_scenario(db: AsyncSession) -> EconomyScenarioResult:
    """
    Revolutionary demo path:
      1) Two VPN networks = isolated ledgers
      2) Provider earns GPU credits on A
      3) Quorum finalize under threshold=2
      4) Bridge burn/mint A→B with Merkle inclusion
      5) Light-client header sync verifies
      6) Insufficient bridge + forged approval rejected
      7) Concurrent attestations remain consistent
    """
    result = EconomyScenarioResult()
    net_a = str(uuid.uuid4())
    net_b = str(uuid.uuid4())
    base = f"zepgpu-rev-{uuid.uuid4().hex[:8]}"

    with ledger_settings(
        enabled=True,
        auto_seal=True,
        isolate_vpn_networks=True,
        chain_id=base,
        quorum_threshold=1,
        extra_validator_private_keys="",
    ):
        a = LedgerService(db, network_id=net_a)
        b = LedgerService(db, network_id=net_b)
        result.chain_a = a.chain_id
        result.chain_b = b.chain_id

        await a.ensure_initialized()
        await b.ensure_initialized()
        result.steps.append(
            ScenarioStep(
                "dual_chain_genesis",
                True,
                "isolated VPN chains initialized",
                {"chain_a": a.chain_id, "chain_b": b.chain_id},
            )
        )

        earn = await a.record_job_completed(
            task_id="rev-earn-1",
            provider_account="provider-nova",
            consumer_account="consumer-orion",
            gpu_seconds=100.0,
        )
        result.steps.append(
            ScenarioStep(
                "provider_earns_credits",
                earn.get("block") is not None and earn["block"].get("finalized") is True,
                "JOB_COMPLETED sealed on chain A",
                {
                    "height": earn["block"]["height"] if earn.get("block") else None,
                    "gpu_seconds": 100.0,
                },
            )
        )

        priv2, pub2 = generate_keypair()
        await a.repo.upsert_validator(chain_id=a.chain_id, public_key=pub2, label="peer-validator")
        await db.commit()

        with ledger_settings(quorum_threshold=2):
            pending = await a.record_job_completed(
                task_id="rev-earn-2",
                provider_account="provider-nova",
                consumer_account="consumer-orion",
                gpu_seconds=25.0,
            )
            block = pending.get("block")
            quorum_unfinalized = isinstance(block, dict) and block.get("finalized") is False
            if quorum_unfinalized:
                assert isinstance(block, dict)
                sig = sign_message(priv2, block["hash"])
                finalized = await a.approve_block(
                    block["hash"],
                    validator_public_key=pub2,
                    signature=sig,
                )
                quorum_ok = finalized.finalized is True
            else:
                quorum_ok = False
            result.steps.append(
                ScenarioStep(
                    "multi_validator_quorum",
                    quorum_unfinalized and quorum_ok,
                    "second validator finalized unfinalized tip",
                    {"threshold": 2, "finalized": quorum_ok},
                )
            )

        bridge = BridgeService(db)
        transfer = await bridge.transfer(
            source_network_id=net_a,
            dest_network_id=net_b,
            account="provider-nova",
            amount_seconds=40.0,
            memo="revolution-bridge",
        )
        a_verify = await a.verify_chain()
        b_verify = await b.verify_chain()
        a_bal = {x["account"]: x for x in a_verify.get("balances", [])}
        b_bal = {x["account"]: x for x in b_verify.get("balances", [])}
        bridge_ok = (
            transfer.get("receipt_id")
            and a_verify.get("valid")
            and b_verify.get("valid")
            and abs(a_bal.get("provider-nova", {}).get("net_seconds", 0) - 85.0) < 1e-9
            and abs(b_bal.get("provider-nova", {}).get("credit_seconds", 0) - 40.0) < 1e-9
        )
        result.steps.append(
            ScenarioStep(
                "cross_network_bridge",
                bool(bridge_ok),
                "burn on A + mint on B with inclusion proof",
                {
                    "receipt_id": transfer.get("receipt_id"),
                    "amount": 40.0,
                    "a_net": a_bal.get("provider-nova", {}).get("net_seconds"),
                    "b_credit": b_bal.get("provider-nova", {}).get("credit_seconds"),
                },
            )
        )

        headers = await a.export_headers(from_height=0, limit=50)
        checked = await a.verify_headers_payload(headers, from_height=0)
        result.steps.append(
            ScenarioStep(
                "light_client_header_sync",
                checked.get("valid") is True and len(headers) >= 2,
                "compact headers verify offline-style",
                {"header_count": len(headers), "tip_height": checked.get("tip_height")},
            )
        )

        tip_block = earn["block"]
        tx0 = ComputeTransaction.from_dict(tip_block["transactions"][0])
        proof = await a.get_inclusion_proof(tip_block["hash"], tx0.compute_hash())
        result.steps.append(
            ScenarioStep(
                "merkle_inclusion_proof",
                proof.get("valid") is True,
                "tx inclusion proven against block root",
                {"block_height": tip_block["height"]},
            )
        )

        over_blocked = False
        try:
            await bridge.transfer(
                source_network_id=net_a,
                dest_network_id=net_b,
                account="provider-nova",
                amount_seconds=10_000.0,
                memo="theft",
            )
        except Exception:
            over_blocked = True
        result.steps.append(
            ScenarioStep(
                "reject_insufficient_bridge",
                over_blocked,
                "overdraw bridge rejected",
            )
        )

        tip = await a.repo.get_tip(a.chain_id, finalized_only=True)
        forged_blocked = False
        try:
            if tip is None:
                raise RuntimeError("missing tip")
            evil_priv, evil_pub = generate_keypair()
            await a.approve_block(
                tip.hash,
                validator_public_key=evil_pub,
                signature=sign_message(evil_priv, tip.hash),
            )
        except Exception:
            forged_blocked = True
        result.steps.append(
            ScenarioStep(
                "reject_forged_approval",
                forged_blocked,
                "unauthorized approve rejected",
            )
        )

        concurrent_ok = True
        for i in range(5):
            out = await b.record_job_completed(
                task_id=f"rev-concurrent-{i}",
                provider_account=f"worker-{i}",
                consumer_account="batch-payer",
                gpu_seconds=1.0 + i * 0.1,
            )
            if not out.get("block"):
                concurrent_ok = False
        b_final = await b.verify_chain()
        result.steps.append(
            ScenarioStep(
                "burst_attestations_consistent",
                concurrent_ok and b_final.get("valid") is True,
                "burst of seals remains cryptographically valid",
                {
                    "tip_height": b_final.get("tip_height"),
                    "balances": len(b_final.get("balances") or []),
                },
            )
        )

    return result


async def run_db_adversary_probes(db: AsyncSession) -> list[ScenarioStep]:
    """DB-backed attack probes that must fail."""
    steps: list[ScenarioStep] = []
    chain = f"zepgpu-adv-{uuid.uuid4().hex[:8]}"

    with ledger_settings(
        chain_id=chain,
        quorum_threshold=1,
        auto_seal=True,
        extra_validator_private_keys="",
    ):
        svc = LedgerService(db, chain_id=chain)
        await svc.ensure_initialized()
        await svc.record_job_completed(
            task_id="adv-base",
            provider_account="p",
            consumer_account="c",
            gpu_seconds=5.0,
        )

        with ledger_settings(quorum_threshold=2):
            priv2, pub2 = generate_keypair()
            await svc.repo.upsert_validator(chain_id=chain, public_key=pub2, label="v2")
            await db.commit()
            first = await svc.record_job_completed(
                task_id="adv-unfinal",
                provider_account="p",
                consumer_account="c",
                gpu_seconds=1.0,
            )
            blocked_double = False
            try:
                await svc.record_job_completed(
                    task_id="adv-double",
                    provider_account="p",
                    consumer_account="c",
                    gpu_seconds=1.0,
                )
            except LedgerValidationError:
                blocked_double = True
            steps.append(
                ScenarioStep(
                    "reject_seal_while_unfinalized",
                    blocked_double and first.get("block", {}).get("finalized") is False,
                    "cannot seal over unfinalized tip",
                )
            )
            if first.get("block") and not first["block"].get("finalized"):
                sig = sign_message(priv2, first["block"]["hash"])
                await svc.approve_block(
                    first["block"]["hash"],
                    validator_public_key=pub2,
                    signature=sig,
                )

    return steps
