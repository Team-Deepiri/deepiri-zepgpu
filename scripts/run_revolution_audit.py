#!/usr/bin/env python3
"""CI helper: run revolution audit and write artifacts."""

from __future__ import annotations

import asyncio
from pathlib import Path


async def _main() -> int:
    from deepiri_zepgpu.compute_ledger.revolution import run_revolution_audit
    from deepiri_zepgpu.compute_ledger.revolution.report import (
        write_audit_json,
        write_audit_markdown,
    )
    from deepiri_zepgpu.database.session import get_db_context

    out = Path("artifacts")
    out.mkdir(parents=True, exist_ok=True)
    async with get_db_context() as db:
        result = await run_revolution_audit(db, include_db=True)
    write_audit_json(result, out / "revolution-audit.json")
    write_audit_markdown(result, out / "revolution-audit.md")
    print(result.to_dict()["headline"])
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
