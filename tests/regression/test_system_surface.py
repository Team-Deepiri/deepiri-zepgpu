"""Regression: OpenAPI surface + import/migration smoke (no Postgres required)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

EXPECTED_API_PREFIXES = [
    "/api/v1/health",
    "/api/v1/tasks",
    "/api/v1/pipelines",
    "/api/v1/schedules",
    "/api/v1/gang",
    "/api/v1/namespaces",
    "/api/v1/cloud",
    "/api/v1/users",
    "/api/v1/auth",
    "/api/v1/gpu",
    "/api/v1/vpn",
    "/api/v1/ledger",
]


def test_openapi_registers_core_surfaces():
    from deepiri_zepgpu.api.server.main import app

    # Prefer route table over app.openapi() — some FastAPI deps (BackgroundTasks)
    # can break schema generation under pydantic v2 without affecting runtime.
    paths = {
        getattr(route, "path", "")
        for route in app.routes
        if getattr(route, "path", None)
    }
    for prefix in EXPECTED_API_PREFIXES:
        assert any(p.startswith(prefix) for p in paths), f"missing routes under {prefix}"

    assert "/" in paths
    assert "/metrics" in paths
    assert "/api/v1/ledger/status" in paths
    assert "/api/v1/ledger/bridge/transfer" in paths
    assert "/api/v1/ledger/sync/headers" in paths


def test_core_modules_importable():
    import deepiri_zepgpu.compute_ledger  # noqa: F401
    import deepiri_zepgpu.core.executor  # noqa: F401
    import deepiri_zepgpu.core.gpu_manager  # noqa: F401
    import deepiri_zepgpu.core.scheduler  # noqa: F401
    import deepiri_zepgpu.security.access_control  # noqa: F401
    import deepiri_zepgpu.vpn.gpu_pool  # noqa: F401


def test_alembic_revision_chain_is_linear():
    versions = Path("alembic/versions")
    files = sorted(versions.glob("*.py"))
    assert files, "no alembic versions found"

    revisions: dict[str, str | None] = {}
    for path in files:
        text = path.read_text()
        rev = None
        down = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("revision:") or stripped.startswith("revision ="):
                rev = stripped.split("=", 1)[1].strip().strip("'\"")
            if stripped.startswith("down_revision:") or stripped.startswith("down_revision ="):
                raw = stripped.split("=", 1)[1].strip()
                down = None if raw in {"None", "none"} else raw.strip("'\"")
        assert rev, f"missing revision in {path}"
        revisions[rev] = down

    # Exactly one root; every down_revision (except None) must exist
    roots = [r for r, d in revisions.items() if d is None]
    assert len(roots) == 1, f"expected one root revision, got {roots}"
    for rev, down in revisions.items():
        if down is not None:
            assert down in revisions, f"{rev} points at missing down_revision {down}"
