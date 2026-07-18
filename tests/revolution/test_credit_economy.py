"""Revolutionary DB scenarios: credit economy + adversary probes."""

from __future__ import annotations

import pytest

from deepiri_zepgpu.compute_ledger.revolution.audit import run_revolution_audit
from deepiri_zepgpu.compute_ledger.revolution.scenarios import (
    run_credit_economy_scenario,
    run_db_adversary_probes,
)

pytestmark = [pytest.mark.revolution, pytest.mark.integration]


@pytest.mark.asyncio
async def test_credit_economy_scenario(db_session):
    result = await run_credit_economy_scenario(db_session)
    failed = [s for s in result.steps if not s.ok]
    assert result.passed, [(s.name, s.detail, s.metrics) for s in failed]


@pytest.mark.asyncio
async def test_db_adversary_probes(db_session):
    steps = await run_db_adversary_probes(db_session)
    failed = [s for s in steps if not s.ok]
    assert not failed, [(s.name, s.detail) for s in failed]


@pytest.mark.asyncio
async def test_full_revolution_audit_passes(db_session, tmp_path):
    from deepiri_zepgpu.compute_ledger.revolution.report import (
        write_audit_json,
        write_audit_markdown,
    )

    audit = await run_revolution_audit(db_session, include_db=True)
    write_audit_json(audit, tmp_path / "revolution-audit.json")
    write_audit_markdown(audit, tmp_path / "revolution-audit.md")
    assert (tmp_path / "revolution-audit.md").exists()
    assert audit.passed, audit.to_dict()
    assert audit.score >= 90
    assert audit.grade in {"S", "A"}
