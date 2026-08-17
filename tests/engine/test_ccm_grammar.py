"""GBNF grammar for CCM output (offline).

Two things are pinned here:

1. **The grammar is a SUPERSET of what the gates accept**, except where it narrows on
   purpose. If the grammar rejected documents `ccm.validate` accepts, constrained
   decoding would silently discard correct cards — the exact failure the project treats
   as a defect. `test_grammar_accepts_the_whole_store` replays the real store when it is
   present (it is gitignored, so CI runs the hand-built cases instead).
2. **The grammar cannot drift from the schema.** It is generated from the constants in
   `ccm.py`, and the tests below fail if a constant grows a member the grammar does not
   carry.
"""

import glob
import json
from pathlib import Path

import pytest

from mythgauntlet.semantics import ccm_grammar
from mythgauntlet.semantics.ccm import (
    ABILITY_KINDS,
    TARGET_CONTROLLERS,
    _ACTIVATED_COST_KEYS,
    _VARIABLE_QUANTITIES,
)
from mythgauntlet.semantics.ccm_grammar import CCM_GRAMMAR, build_grammar, violations

GOOD = {
    "name": "Insight Spell",
    "ccm_version": 1,
    "cost": {"mana": "{2}{U}"},
    "types": ["sorcery"],
    "abilities": [{"kind": "spell_effect", "effects": [{"op": "draw", "count": 2}]}],
}


# --- the grammar itself ----------------------------------------------------------

def test_grammar_has_a_root_and_every_referenced_rule():
    """A GBNF referencing an undefined rule fails at load time inside llama-server, which
    surfaces as an opaque 500 on every compile. Catch it here instead."""
    defined, referenced = set(), set()
    for line in CCM_GRAMMAR.splitlines():
        line = line.split("#", 1)[0].strip() if not line.startswith("#") else ""
        if "::=" not in line:
            continue
        name, body = line.split("::=", 1)
        defined.add(name.strip())
        # Rule references are bare identifiers; literals live inside double quotes and
        # char classes inside brackets, so strip both before scanning.
        scrubbed = []
        in_str = False
        skip = False
        for ch in body:
            if skip:
                skip = False
                continue
            if ch == "\\":
                skip = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            scrubbed.append(" " if in_str else ch)
        text = "".join(scrubbed)
        while "[" in text and "]" in text:
            start, end = text.index("["), text.index("]")
            if start > end:
                break
            text = text[:start] + " " + text[end + 1:]
        for token in text.replace("(", " ").replace(")", " ").split():
            token = token.strip("*+?|")
            if token and (token[0].isalpha() or token[0] == "_"):
                referenced.add(token)

    assert "root" in defined
    missing = referenced - defined
    assert not missing, f"grammar references undefined rules: {sorted(missing)}"


def test_grammar_is_generated_from_the_schema_constants():
    """Every closed vocabulary the grammar encodes must appear in it verbatim, so adding
    a member to the constant and forgetting the grammar is a test failure, not a silent
    decoding bug."""
    for kind in ABILITY_KINDS:
        assert f'"\\"{kind}\\""' in CCM_GRAMMAR, f"ability kind {kind} missing"
    for key in _ACTIVATED_COST_KEYS:
        assert f'"\\"{key}\\""' in CCM_GRAMMAR, f"activated cost key {key} missing"
    for controller in TARGET_CONTROLLERS:
        assert f'"\\"{controller}\\""' in CCM_GRAMMAR, f"controller {controller} missing"
    for word in _VARIABLE_QUANTITIES:
        assert f'"\\"{word}\\""' in CCM_GRAMMAR, f"variable quantity {word} missing"


def test_build_grammar_is_deterministic():
    """Sorted alternations — a grammar that reshuffles per process would defeat
    llama-server's grammar cache and make A/B runs unreproducible."""
    assert build_grammar() == build_grammar() == CCM_GRAMMAR


def test_grammar_rejects_an_unknown_ability_kind_at_generation_time():
    """`build_grammar` asserts on the exact kind set, because each kind has a hand-written
    rule — a sixth kind must not silently fall through to no rule at all."""
    original = ccm_grammar.ABILITY_KINDS
    try:
        ccm_grammar.ABILITY_KINDS = original | {"delayed_trigger"}
        with pytest.raises(AssertionError):
            build_grammar()
    finally:
        ccm_grammar.ABILITY_KINDS = original


# --- what the grammar allows ------------------------------------------------------

def test_allows_a_good_document():
    assert violations(GOOD) == []


def test_allows_the_tolerance_the_schema_depends_on():
    """The op vocabulary and trigger events stay OPEN. 5,531 of 31,028 stored cards
    (17.8%) carry an op outside OP_SPECS; closing it would force the model to pick a
    wrong-but-legal op instead of an honest unsupported one."""
    doc = dict(GOOD, abilities=[
        {"kind": "spell_effect", "effects": [{"op": "regenerate", "target": {"type": "creature"}}]},
        {"kind": "triggered", "trigger": {"event": "invented_event"},
         "effects": [{"op": "look_at_library", "count": 3}]},
        # A bare descriptive effect with no op at all is legal (33 stored cards).
        {"kind": "spell_effect", "effects": [{"note": "something the ops cannot say"}]},
    ])
    assert violations(doc) == []


def test_allows_compiler_added_keys():
    """`rung`/`provenance`/`unsupported_ops` are written by compile_card AFTER the model
    responds, so a stored envelope carries them and must still check clean."""
    doc = dict(GOOD, rung=2, provenance={"source": "llm_compiled"}, unsupported_ops=["x"])
    assert violations(doc) == []


def test_allows_sub_effects_and_costs_on_unsupported_ops():
    """`{"op": "roll_dice", "effects": [...]}` and `{"op": "pay_mana", "cost": {...}}` are
    legitimate sub-structure (208 and 182 stored cards) — only a nested `kind` is
    leakage."""
    doc = dict(GOOD, abilities=[{"kind": "spell_effect", "effects": [
        {"op": "roll_dice", "die": "d20", "effects": [{"op": "draw", "count": 1}]},
        {"op": "pay_mana", "cost": {"mana": "{1}{R}"}, "optional": True},
    ]}])
    assert violations(doc) == []


# --- what the grammar prevents ----------------------------------------------------

def test_blocks_the_measured_gate_one_buckets():
    """One case per bucket recorded in the ledger, with its size."""
    def only(doc):
        return violations(doc)

    # 97 gate errors: an ability that is not static with no effects to pay for.
    assert only(dict(GOOD, abilities=[{"kind": "activated", "cost": {"mana": "{2}"},
                                       "effects": []}]))
    # 71: a mana ability that also does something else.
    assert only(dict(GOOD, abilities=[{"kind": "mana_ability", "cost": {"tap": True},
                                       "effects": [{"op": "add_mana", "amount": 1},
                                                   {"op": "scry", "count": 1}]}]))
    # 9: an invented activated-cost key instead of "other".
    assert only(dict(GOOD, abilities=[{"kind": "activated",
                                       "cost": {"mana": "{1}", "discard": 1},
                                       "effects": [{"op": "draw", "count": 1}]}]))
    # 219 (largest bucket): a quantity that is neither an integer nor a variable.
    assert only(dict(GOOD, abilities=[{"kind": "spell_effect",
                                       "effects": [{"op": "draw", "count": "a bunch"}]}]))
    # ~70: a target controller outside the closed set.
    assert only(dict(GOOD, abilities=[{"kind": "spell_effect", "effects": [
        {"op": "destroy", "target": {"type": "creature", "controller": "owner"}}]}]))
    # ccm_version drift.
    assert only(dict(GOOD, ccm_version=2))


def test_blocks_a_self_declared_rung():
    """The COMPILER owns the tier. 1,897 compiled cards had claimed rung 3 — the tier
    reserved for hand-authored exemplars — by self-declaring it in the model's output.
    `rung` is allowed on a STORED envelope (compile_card writes it) but the grammar's
    top-level key set is what the model may emit, and 2 is what this path produces."""
    assert violations(dict(GOOD, rung=2)) == []  # compiler-written, fine
    # ...but the grammar has no `rung` production, so the model cannot emit one at all:
    assert '"\\"rung\\""' not in CCM_GRAMMAR


def test_blocks_a_nested_ability_inside_an_effects_list():
    """279 stored cards put `{"kind": "static", "note": ...}` in an effects list and 102
    put a whole triggered ability there. That content belongs in a sibling ability."""
    doc = dict(GOOD, abilities=[{"kind": "spell_effect", "effects": [
        {"kind": "static", "note": "flying"},
    ]}])
    assert any("kind" in v for v in violations(doc))


def test_blocks_a_bare_ability_as_the_whole_document():
    """175 stored documents are an ability where a CCM should be."""
    assert violations({"kind": "triggered", "trigger": {"event": "etb"}, "effects": []})


# --- regression against the real store --------------------------------------------

def _store_files():
    # Ask the compiler where the store is rather than rebuilding the MYTHGAUNTLET_STORE
    # logic here — a private copy of that path silently skipped this whole test.
    from mythgauntlet.semantics.compiler import compiled_dir
    return sorted(glob.glob(str(compiled_dir() / "*.json")))


# The store is gitignored (docs/ENGINE_DATA.md), so this is a local-only regression.
@pytest.mark.skipif(not _store_files(), reason="compiled CCM store not present")
def test_grammar_accepts_the_whole_store():
    """Replay every gate-passing document. The grammar must not block more than the
    narrowings the module docstring accounts for.

    Measured 2026-08-11 over 31,028 documents: 901 blocked (2.90%) — 481 by the
    documented narrowings (prose quantities and stray controllers, all on ops the engine
    does not execute) and 420 as nested-ability leakage. The ceiling below is that
    measurement plus headroom; a jump means a narrowing got wider than intended.
    """
    files = _store_files()
    blocked = [f for f in files if violations(_read(f))]
    share = len(blocked) / len(files)
    assert share < 0.04, (
        f"grammar blocks {len(blocked)}/{len(files)} ({share:.2%}) of the accepted store "
        f"— it must stay a near-superset of the gates. First few: "
        f"{[Path(f).name for f in blocked[:5]]}"
    )


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["ccm"]
