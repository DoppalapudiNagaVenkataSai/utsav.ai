"""The engine must stay pure: no LLM, network or web-framework imports in core/."""

from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "src" / "occasio" / "core"
FORBIDDEN = (
    "occasio.ai",
    "occasio.api",
    "occasio.storage",
    "google",
    "fastapi",
    "httpx",
    "requests",
    "urllib",
    "socket",
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_has_no_forbidden_imports():
    files = list(CORE.glob("*.py"))
    assert files
    for path in files:
        for module in imported_modules(path):
            assert not module.startswith(FORBIDDEN), f"{path.name} imports {module}"
