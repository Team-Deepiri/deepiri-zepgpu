"""AST guard: VPN repositories must not depend on the API server layer."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPOSITORIES = REPO_ROOT / "deepiri_zepgpu" / "vpn" / "repositories.py"
FORBIDDEN_PREFIX = "deepiri_zepgpu.api.server"


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_vpn_repositories_do_not_import_api_server() -> None:
    source = REPOSITORIES.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(REPOSITORIES))
    offenders = sorted(
        module
        for module in _imported_modules(tree)
        if module == FORBIDDEN_PREFIX or module.startswith(f"{FORBIDDEN_PREFIX}.")
    )
    assert not offenders, (
        f"{REPOSITORIES.relative_to(REPO_ROOT)} must not import {FORBIDDEN_PREFIX}; "
        f"found: {offenders}"
    )


def test_vpn_repositories_file_exists() -> None:
    assert REPOSITORIES.is_file()
