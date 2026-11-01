"""Structural guards for the CLAUDE.md hard rules that can be checked statically."""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_IN_FAST = ("anthropic", "openai", "app.llm", "app.agents")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_llm_on_the_fast_path() -> None:
    """Hard rule 3: the fast engine never imports an LLM client or agent code."""
    for py in (APP / "fast").rglob("*.py"):
        bad = [i for i in _imports(py) if i.startswith(FORBIDDEN_IN_FAST)]
        assert not bad, f"{py} imports {bad}"


def test_no_broker_order_code() -> None:
    """Hard rule 6: no order placement. Order-placing endpoints/names must never appear in app/."""
    forbidden = ("/orders", "/trades/", "place_order", "create_order", "market_order")
    for py in APP.rglob("*.py"):
        src = py.read_text()
        hits = [f for f in forbidden if f in src]
        assert not hits, f"{py} contains {hits}"
