"""A card's primary type is computed twice: by the server (collection_index.primary_type, for the
collection browser) and by the browser (frontend/src/utils/deckGrouping.js, for a deck's tabs and the
themed export). The JS comment says they "agree"; for a modal double-faced card they did not: the
server files "Sorcery // Land" under Sorcery (front face), the browser filed it under Land, and a
Battle was 'Other' in the browser but 'Battle' on the server. This runs the real JS under Node over
a spread of type lines and fails if the two ever disagree. Skipped when Node is not installed."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import collection_index as ci

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "frontend" / "src" / "utils" / "deckGrouping.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None or not JS.exists(), reason="node or the JS source is unavailable")

TYPE_LINES = [
    "Creature — Elf Druid", "Legendary Creature — Angel", "Artifact Creature — Golem",
    "Enchantment Creature — Spirit", "Land Creature — Forest Dryad", "Artifact Land",
    "Basic Land — Island", "Land", "Instant", "Sorcery", "Enchantment — Aura", "Artifact — Equipment",
    "Legendary Planeswalker — Jace", "Planeswalker", "Battle — Siege", "Kindred Instant",
    "Tribal Sorcery — Elf", "Instant — Arcane", "Legendary Artifact", "Token Creature — Goblin",
    # double-faced: the FRONT face decides
    "Sorcery // Land", "Creature — Elf Druid // Land", "Land // Land", "Legendary Creature — Human // Legendary Planeswalker",
    "Artifact // Creature — Golem", "Instant // Instant",
    "", "Something Else",
]


def _js_types(lines):
    script = ("import { primaryType } from " + json.dumps(JS.as_uri()) + ";\n"
              "const lines = JSON.parse(process.argv[1]);\n"
              "console.log(JSON.stringify(lines.map(l => primaryType({ original_type_line: l }))));\n")
    out = subprocess.run([NODE, "--input-type=module", "-e", script, json.dumps(TYPE_LINES)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_browser_and_server_agree_on_every_type_line():
    js = _js_types(TYPE_LINES)
    py = [ci.primary_type(t) for t in TYPE_LINES]
    bad = [(t, j, p) for t, j, p in zip(TYPE_LINES, js, py) if j != p]
    assert not bad, f"browser vs server primary type differ (type_line, js, python): {bad}"


def test_the_type_tab_order_covers_every_type_the_server_can_return():
    script = ("import { TYPE_ORDER, TYPE_PRECEDENCE } from " + json.dumps(JS.as_uri()) + ";\n"
              "console.log(JSON.stringify({order: TYPE_ORDER, precedence: TYPE_PRECEDENCE}));\n")
    out = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    data = json.loads(out.stdout)
    server_types = {ci.primary_type(t) for t in TYPE_LINES} - {"Other"}
    assert server_types <= set(data["order"]), f"types with no tab: {server_types - set(data['order'])}"
    assert set(data["precedence"]) == set(data["order"])        # same vocabulary, different order
