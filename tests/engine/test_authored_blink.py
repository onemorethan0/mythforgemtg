"""The hand-authored blink CCMs must never execute an exile against an opposing permanent.

The compiler can encode a blink in ways the sim cannot tell from Oblivion Ring (return tagged
zone 'exile', return aimed at 'self', exile and return split across two abilities), so these
four were authored in the plain exile+return shape that `interpreter.is_flicker` recognises.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mythgauntlet.semantics.interpreter import interpret_ability

AUTHORED = Path(__file__).resolve().parents[2] / "ccm" / "authored"
FILES = ["90-blizzard-strix.json", "90-hallowed-respite.json",
         "90-eldrazi-confluence.json", "90-the-shattered-states-era.json"]


@pytest.mark.parametrize("fname", FILES)
def test_no_executable_exile_aimed_at_another_permanent(fname):
    ccm = json.loads((AUTHORED / fname).read_text(encoding="utf-8"))["ccm"]
    for ability in ccm["abilities"]:
        for eff in interpret_ability(ability):
            if eff.op in ("exile", "destroy"):
                target = eff.params.get("target") or {}
                assert target.get("self"), f"{ccm['name']}: {eff.op} would run against another permanent"


@pytest.mark.parametrize("fname", FILES)
def test_authored_file_is_a_rung3_envelope_for_the_named_card(fname):
    env = json.loads((AUTHORED / fname).read_text(encoding="utf-8"))
    assert env["ccm"]["rung"] == 3
    assert env["card"]["name"] == env["ccm"]["name"]
