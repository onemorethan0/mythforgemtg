"""The single-card designer normalises a typed mana cost in the browser (frontend/src/utils/manaCost.js)
so the preview shows what the server will store, and the server normalises it again
(api.cards._normalize_mana_cost). CLAUDE.md says "keep the two in step"; this runs the REAL JS under
Node on the same inputs and fails if they ever disagree. Skipped when Node is not installed."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from api import cards

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "frontend" / "src" / "utils" / "manaCost.js"
NODE = shutil.which("node")

CASES = [
    "2WU", "2 w u", "XRR", "10", "w/u", "2/W", "{2}{W}", "{1}", "", "   ", "hello", "2WQ",
    "  2W  ", "WWW", "1 1", "X", "xyz", "S", "s2", "2\tW", "2\nW", " 2W", "w u b r g", "{",
    "2{W}", "WUBRGC", "CC", "10 10", "00", "2WU2",
]


def _js_results(cases):
    script = (
        "import { normalizeManaCost } from " + json.dumps(JS.as_uri()) + ";\n"
        "const cases = JSON.parse(process.argv[1]);\n"
        "console.log(JSON.stringify(cases.map(c => normalizeManaCost(c))));\n"
    )
    out = subprocess.run([NODE, "--input-type=module", "-e", script, json.dumps(cases)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None or not JS.exists(), reason="node or the JS source is unavailable")
def test_the_browser_and_server_normalisers_agree_on_every_case():
    js = _js_results(CASES)
    py = [cards._normalize_mana_cost(c) for c in CASES]
    mismatches = [(c, j, p) for c, j, p in zip(CASES, js, py) if j != p]
    assert not mismatches, f"browser vs server disagree (input, js, python): {mismatches}"


def test_the_shorthand_pattern_is_textually_the_same():
    """Even without Node: the token regex in both files must be the same pattern."""
    src = JS.read_text(encoding="utf-8")
    line = next(l for l in src.splitlines() if l.strip().startswith("const SHORTHAND_MANA"))
    js_pattern = line.split("/")[1]
    assert js_pattern == cards._SHORTHAND_MANA_RE.pattern
