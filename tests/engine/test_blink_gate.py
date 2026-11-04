"""Gate 3 catches a blink compiled without its return, or with gain_control.

A blink ("exile target creature you control, then return it to the battlefield") has no op of
its own: the accepted encoding is `exile` plus a return op, which `interpreter.is_flicker`
recognises and the sim drops. An exile with NO return op, or a blink carrying `gain_control`,
slips past that. Measured on the store 2026-11-04: 17 cards of the first kind (Hallowed
Respite, Mistmeadow Vanisher ...), 25 of the second.
"""
from __future__ import annotations

from mythgauntlet.semantics import ccm, interpreter
from mythgauntlet.semantics.ccm import cross_check

BASE = {"name": "X", "ccm_version": 1, "cost": {"mana": "{1}{W}"}, "types": ["instant"]}


def _doc(*ops):
    return dict(BASE, abilities=[{"kind": "spell_effect", "effects": list(ops)}])


EXILE = {"op": "exile", "target": {"type": "creature", "controller": "any"}}
RETURN = {"op": "return_to_hand", "target": {"type": "creature", "controller": "any"}}
GAIN = {"op": "gain_control", "target": {"type": "creature", "controller": "any"}}

BLINK_TEXT = "Exile target nonlegendary creature, then return it to the battlefield under its owner's control."


def _msgs(make_card, text, doc, **kw):
    card = make_card("X", mana_cost="{1}{W}", type_line=kw.get("type_line", "Instant"), oracle_text=text)
    return [e for e in cross_check(doc, card) if "blink" in e or "gain_control" in e]


def test_exile_without_a_return_is_flagged(make_card):
    errs = _msgs(make_card, BLINK_TEXT, _doc(EXILE))
    assert any("no return op" in e for e in errs)


def test_exile_plus_return_is_the_accepted_blink_encoding(make_card):
    assert _msgs(make_card, BLINK_TEXT, _doc(EXILE, RETURN)) == []


def test_gain_control_in_a_blink_is_flagged(make_card):
    errs = _msgs(make_card, BLINK_TEXT, _doc(EXILE, RETURN, GAIN))
    assert any("gain_control" in e for e in errs)
    assert not any("no return op" in e for e in errs)


def test_sentence_split_blink_is_recognised(make_card):
    text = "Exile up to one target nonland permanent. Return that card to the battlefield under its owner's control at the beginning of the next end step."
    assert any("no return op" in e for e in _msgs(make_card, text, _doc(EXILE)))


def test_plain_removal_is_not_flagged(make_card):
    text = "Exile target creature. Its controller gains life equal to its power."
    assert _msgs(make_card, text, _doc(EXILE)) == []


def test_return_tied_to_leaving_the_battlefield_is_removal_not_a_blink(make_card):
    # Portcullis / Oblivion Ring family: the exile lasts while the permanent stays
    text = "When this enters, exile that creature. Return that card to the battlefield under its owner's control when this leaves the battlefield."
    assert _msgs(make_card, text, _doc(EXILE)) == []


def test_recursion_from_a_graveyard_is_not_a_blink(make_card):
    text = "Exile target creature card from your graveyard, then return it to the battlefield."
    assert _msgs(make_card, text, _doc(EXILE)) == []


def test_reminder_text_does_not_count(make_card):
    text = "Exile target creature. (Then return it to the battlefield.)"
    assert _msgs(make_card, text, _doc(EXILE)) == []


def test_return_op_sets_stay_in_lock_step():
    # ccm cannot import interpreter (cycle), so the set is restated and pinned here
    assert ccm._BLINK_RETURN_OPS == interpreter._RETURN_OPS
