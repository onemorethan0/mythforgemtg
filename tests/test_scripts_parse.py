"""Every script must at least PARSE.

`scripts/` holds the measurement harnesses — `builder_bench`, `advisor_bench`, the calibration
scripts, the offload harness — and nothing in the suite imports them, so a syntax error there
ships silently and is only found when someone runs the tool. That happened: an edit left a
broken f-string in `advisor_bench.py` and the whole suite stayed green.

Parsing is a deliberately low bar. These tools need a live gateway, a semantics store or the
network to run, so importing them here is not an option — but "it is valid Python" is free and
catches the failure that actually occurred.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(p for p in ROOT.glob("scripts/**/*.py") if "__pycache__" not in p.parts)


def test_there_are_scripts_to_check():
    """A glob that silently matches nothing would make this file a no-op."""
    assert len(SCRIPTS) >= 5, f"only found {len(SCRIPTS)} scripts — has the layout moved?"


@pytest.mark.parametrize("path", SCRIPTS, ids=[p.name for p in SCRIPTS])
def test_script_parses(path: Path):
    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source)
    except SyntaxError as exc:
        pytest.fail(f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")
