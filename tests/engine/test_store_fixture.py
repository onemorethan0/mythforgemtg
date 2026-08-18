"""The offline invariant, enforced rather than commented.

Invariant #5 says the engine tests are offline and synthetic. `SemanticsStore()` with no
arguments quietly breaks that: it resolves `compiler.compiled_dir()` from
`MYTHGAUNTLET_STORE`, so on any machine where that variable is set it loads the real
compiled store — 31,042 CCMs, 7.5 seconds — while the code using it was commented
"empty -> everything resolves at rung 1 (offline)".

That is not a tidiness complaint. It meant the rung-1 tests ran at rung 2/3, CI and a dev
machine exercised different code paths, and re-reading 31k files per instantiation produced
an intermittent OSError whenever the suite ran alongside another job walking the store.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ENGINE_TESTS = Path(__file__).resolve().parent


def test_the_empty_store_fixture_is_actually_empty(empty_store):
    assert len(empty_store) == 0, (
        f"`empty_store` loaded {len(empty_store)} entries — it is resolving a real store")
    # And it behaves as rung 1, which is what the tests using it assert against.
    assert empty_store.lookup("Sol Ring").rung == 1


def test_no_engine_test_constructs_a_bare_semantics_store():
    """A bare `SemanticsStore()` silently picks up MYTHGAUNTLET_STORE.

    Source-scanned rather than monkeypatched, because the failure is one of INTENT: the call
    works fine, it just does something other than what the surrounding test claims. Use the
    `empty_store` fixture, or pass explicit `authored=` / `compiled=` paths.
    """
    offenders = []
    for path in sorted(ENGINE_TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "SemanticsStore"
                    and not node.args and not node.keywords):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "bare SemanticsStore() resolves MYTHGAUNTLET_STORE and is not empty; "
        f"use the `empty_store` fixture instead: {offenders}")
