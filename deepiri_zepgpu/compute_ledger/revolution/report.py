"""Render revolution audit as Markdown + JSON artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deepiri_zepgpu.compute_ledger.revolution.audit import RevolutionAuditResult


def write_audit_json(result: RevolutionAuditResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2, default=str) + "\n")
    return path


def write_audit_markdown(result: RevolutionAuditResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    d = result.to_dict()
    lines: list[str] = [
        "# ZepGPU Revolution Audit",
        "",
        f"**{d['headline']}**",
        "",
        f"- Generated: `{d['generated_at']}`",
        f"- Score: **{d['score']}/100** (grade **{d['grade']}**)",
        f"- Passed: **{d['passed']}**",
        "",
        "## Golden cryptographic vectors",
        "",
        f"- Valid: `{d['golden'].get('valid')}`",
        f"- Fixture: `{d['golden'].get('fixture')}`",
    ]
    mismatches = d["golden"].get("mismatches") or []
    if mismatches:
        lines.append("- Mismatches:")
        for m in mismatches[:20]:
            lines.append(f"  - `{m}`")
    else:
        lines.append("- Mismatches: none")

    lines.extend(
        [
            "",
            "## Adversarial defense (in-memory)",
            "",
            f"- Attacks blocked: **{d['crypto_adversary']['blocked_count']}"
            f"/{d['crypto_adversary']['attack_count']}**",
            "",
            "| Attack | Blocked | Detail |",
            "|---|---|---|",
        ]
    )
    for o in d["crypto_adversary"]["outcomes"]:
        lines.append(
            f"| `{o['name']}` | {'✅' if o['blocked'] else '❌'} | {o['detail'][:80]} |"
        )

    if d.get("economy"):
        lines.extend(
            [
                "",
                "## Multi-network credit economy",
                "",
                f"- Chain A: `{d['economy']['chain_a']}`",
                f"- Chain B: `{d['economy']['chain_b']}`",
                f"- Scenario passed: **{d['economy']['passed']}**",
                "",
                "| Step | OK | Detail |",
                "|---|---|---|",
            ]
        )
        for s in d["economy"]["steps"]:
            lines.append(
                f"| `{s['name']}` | {'✅' if s['ok'] else '❌'} | {s['detail'][:80]} |"
            )

    if d.get("db_adversary_steps"):
        lines.extend(["", "## DB-backed adversary probes", "", "| Probe | OK | Detail |", "|---|---|---|"])
        for s in d["db_adversary_steps"]:
            lines.append(
                f"| `{s['name']}` | {'✅' if s['ok'] else '❌'} | {s['detail'][:80]} |"
            )

    lines.extend(
        [
            "",
            "## Why this matters",
            "",
            "This is not a coin. It is a **permissioned compute ledger** for GPU-pool",
            "attestation, quorum finality, Merkle inclusion, light-client sync, and",
            "cross-network credit settlement — verified under adversarial pressure.",
            "",
        ]
    )
    path.write_text("\n".join(lines))
    return path


def render_console_summary(result: RevolutionAuditResult) -> str:
    d = result.to_dict()
    return (
        f"{d['headline']}\n"
        f"golden={d['golden'].get('valid')} "
        f"adversary={d['crypto_adversary']['blocked_count']}/{d['crypto_adversary']['attack_count']} "
        f"economy={None if not d.get('economy') else d['economy']['passed']}"
    )
