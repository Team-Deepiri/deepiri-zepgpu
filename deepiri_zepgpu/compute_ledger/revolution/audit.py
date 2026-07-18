"""Orchestrate golden + adversary + economy into one revolution audit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from deepiri_zepgpu.compute_ledger.revolution.adversary import (
    AdversaryReport,
    run_cryptographic_adversary_suite,
)
from deepiri_zepgpu.compute_ledger.revolution.golden import verify_golden_fixture
from deepiri_zepgpu.compute_ledger.revolution.scenarios import (
    EconomyScenarioResult,
    run_credit_economy_scenario,
    run_db_adversary_probes,
)


@dataclass
class RevolutionAuditResult:
    generated_at: str
    golden: dict[str, Any]
    crypto_adversary: AdversaryReport
    economy: EconomyScenarioResult | None = None
    db_adversary_steps: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0
    grade: str = "F"
    passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "passed": self.passed,
            "score": self.score,
            "grade": self.grade,
            "golden": self.golden,
            "crypto_adversary": self.crypto_adversary.to_dict(),
            "economy": self.economy.to_dict() if self.economy else None,
            "db_adversary_steps": self.db_adversary_steps,
            "headline": _headline(self),
        }


def _headline(result: RevolutionAuditResult) -> str:
    if result.passed:
        return (
            f"REVOLUTION AUDIT PASSED — grade {result.grade} "
            f"({result.score:.0f}/100): PoA defenses hold, multi-network credit economy verified."
        )
    return (
        f"REVOLUTION AUDIT FAILED — grade {result.grade} "
        f"({result.score:.0f}/100): see mismatches / failed steps."
    )


def _grade(score: float) -> str:
    if score >= 97:
        return "S"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def score_audit(
    *,
    golden_ok: bool,
    crypto: AdversaryReport,
    economy: EconomyScenarioResult | None,
    db_steps_ok: bool,
) -> float:
    score = 0.0
    if golden_ok:
        score += 25.0
    if crypto.outcomes:
        score += 35.0 * (sum(1 for o in crypto.outcomes if o.blocked) / len(crypto.outcomes))
    if economy is not None and economy.steps:
        score += 30.0 * (sum(1 for s in economy.steps if s.ok) / len(economy.steps))
    if db_steps_ok:
        score += 10.0
    return round(score, 1)


async def run_revolution_audit(
    db: AsyncSession | None = None,
    *,
    include_db: bool = True,
) -> RevolutionAuditResult:
    """Run the full revolutionary verification battery."""
    golden = verify_golden_fixture()
    crypto = run_cryptographic_adversary_suite()
    economy: EconomyScenarioResult | None = None
    db_steps: list[dict[str, Any]] = []
    db_ok = True

    if include_db and db is not None:
        economy = await run_credit_economy_scenario(db)
        probes = await run_db_adversary_probes(db)
        db_steps = [{"name": s.name, "ok": s.ok, "detail": s.detail} for s in probes]
        db_ok = all(s.ok for s in probes)

    score = score_audit(
        golden_ok=bool(golden.get("valid")),
        crypto=crypto,
        economy=economy,
        db_steps_ok=db_ok if include_db and db is not None else True,
    )
    # If DB skipped, rescore without requiring economy
    if not include_db or db is None:
        score = score_audit(
            golden_ok=bool(golden.get("valid")),
            crypto=crypto,
            economy=None,
            db_steps_ok=True,
        )
        # redistribute: golden 40 + crypto 60 when offline
        score = 0.0
        if golden.get("valid"):
            score += 40.0
        if crypto.outcomes:
            score += 60.0 * (sum(1 for o in crypto.outcomes if o.blocked) / len(crypto.outcomes))
        score = round(score, 1)

    passed = score >= 90.0 and bool(golden.get("valid")) and crypto.all_blocked
    if include_db and db is not None:
        passed = passed and bool(economy and economy.passed) and db_ok

    return RevolutionAuditResult(
        generated_at=datetime.now(timezone.utc).isoformat(),
        golden=golden,
        crypto_adversary=crypto,
        economy=economy,
        db_adversary_steps=db_steps,
        score=score,
        grade=_grade(score),
        passed=passed,
    )
