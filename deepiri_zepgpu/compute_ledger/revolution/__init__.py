"""Revolutionary verification: adversarial defense, multi-party economy, audit reports."""

from __future__ import annotations

from deepiri_zepgpu.compute_ledger.revolution.audit import (
    RevolutionAuditResult,
    run_revolution_audit,
)
from deepiri_zepgpu.compute_ledger.revolution.report import (
    write_audit_json,
    write_audit_markdown,
)

__all__ = [
    "RevolutionAuditResult",
    "run_revolution_audit",
    "write_audit_json",
    "write_audit_markdown",
]
