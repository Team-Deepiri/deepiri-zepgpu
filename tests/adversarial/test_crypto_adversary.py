"""Adversarial unit tests — attacks must fail without a database."""

from __future__ import annotations

import pytest

from deepiri_zepgpu.compute_ledger.revolution.adversary import run_cryptographic_adversary_suite
from deepiri_zepgpu.compute_ledger.revolution.golden import (
    build_golden_payload,
    verify_golden_fixture,
)

pytestmark = pytest.mark.revolution


def test_adversary_suite_blocks_all_attacks():
    report = run_cryptographic_adversary_suite()
    assert report.all_blocked, report.to_dict()
    assert report.to_dict()["attack_count"] >= 8


def test_golden_vectors_match_committed_fixture():
    result = verify_golden_fixture()
    assert result["valid"] is True, result.get("mismatches")


def test_golden_payload_is_deterministic():
    a = build_golden_payload()
    b = build_golden_payload()
    assert a["block"]["hash"] == b["block"]["hash"]
    assert a["transaction"]["hash"] == b["transaction"]["hash"]
    assert a["merkle"]["root"] == b["merkle"]["root"]
