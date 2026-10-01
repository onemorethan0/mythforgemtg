"""The holistic bench's hand-written rubrics (scripts/mentor_holistic_rubrics.py), tested
with fake replies/truth so a rubric that false-passes or false-fails is caught offline."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "mentor_holistic_rubrics",
    Path(__file__).resolve().parents[2] / "scripts" / "mentor_holistic_rubrics.py",
)
rub = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rub)

DECK = frozenset({"Shelob, Child of Ungoliant", "Gloomwidow's Feast", "Cultivate", "Sol Ring",
                  "Beast Whisperer"})


def _reply(text, gated=True, trace=(), rejections=()):
    return SimpleNamespace(
        text=text, gated=gated, gate_rejections=list(rejections),
        tool_trace=[SimpleNamespace(name=n, args={}, result_data=d) for n, d in trace],
    )


def _truth(res=93.0, archetype="Midrange goodstuff", strengths=("Resilient to wipes (93/100)",),
           key=(("Ramp", ["Cultivate", "Beast Whisperer"]),), finisher=0.0, identity="BG"):
    return {
        "analysis": SimpleNamespace(
            resilience=SimpleNamespace(resilience_score=res) if res is not None else None,
            report=SimpleNamespace(avg_kill_turn=9.0, goldfish_kill_rate=0.6, consistency_score=82.0),
            interaction=SimpleNamespace(score=60.0),
            insight=SimpleNamespace(
                archetype=archetype, strengths=list(strengths),
                key_cards=[SimpleNamespace(role=r, names=n, more=0) for r, n in key]),
        ),
        "stats": {"roles": {"finisher": {"supply": finisher, "target": 2}}},
        "identity": frozenset(identity),
        "deck_names": DECK,
        "ctx": SimpleNamespace(all_card_names=DECK | {"Lightning Bolt", "Counterspell"}),
        "_swap_cache": {"speed": {"found": True}, "weakest": {"found": True}},
    }


# ── resilience ──────────────────────────────────────────────────────────────────────

def test_resilience_inverted_verdict_fails():
    ok, why = rub.grade("resilience", _reply("It seems somewhat vulnerable to a board wipe."), _truth())
    assert ok is False and "moderate" in why


def test_resilience_matching_verdict_passes():
    ok, _ = rub.grade("resilience", _reply("It is resilient to a board wipe since ramp survives."), _truth())
    assert ok is True


def test_resilience_no_verdict_fails():
    ok, why = rub.grade("resilience", _reply("Wipes are a thing in Commander."), _truth())
    assert ok is False and "no resilience verdict" in why


def test_resilience_opposite_phrase_anywhere_fails():
    text = "It is resilient to a wipe. But it is also vulnerable to sweepers."
    ok, _ = rub.grade("resilience", _reply(text), _truth())
    assert ok is False


# ── overview / wincon ───────────────────────────────────────────────────────────────

def test_overview_passes_with_agreeing_verdict_and_strength_topic():
    ok, _ = rub.grade("overview", _reply("Its mana is consistent and it is resilient to wipes."), _truth())
    assert ok is True


def test_overview_fails_on_inverted_resilience_and_missing_strength():
    ok, why = rub.grade("overview", _reply("It is vulnerable to wipes and lacks counterspells."),
                        _truth(strengths=("Resilient to wipes (93/100)",)))
    assert ok is False and "resilience claimed" in why


def test_wincon_control_label_fails():
    ok, why = rub.grade("wincon", _reply("It is a control deck with powerful late-game finishers."), _truth())
    assert ok is False and "control" in why and "finishers" in why


def test_wincon_combat_route_passes():
    ok, _ = rub.grade("wincon", _reply("It wins by attacking with lots of creatures."), _truth())
    assert ok is True


def test_wincon_negated_finishers_ok():
    ok, _ = rub.grade("wincon", _reply("A midrange deck with no real finishers; it wins in combat."), _truth())
    assert ok is True


# ── cards ───────────────────────────────────────────────────────────────────────────

def test_cards_needs_a_key_card_name():
    assert rub.grade("cards", _reply("The ramp cards are likely the most impactful."), _truth())[0] is False
    assert rub.grade("cards", _reply("Cultivate and Sol Ring do the work."), _truth())[0] is True


# ── faster / weakest ────────────────────────────────────────────────────────────────

_EMPTY_SWAP = ("suggest_swap", {"found": True, "improving_swap_found": False, "suggestions": []})
_REAL_SWAP = ("suggest_swap", {"found": True, "suggestions": [{"add": "Lightning Bolt", "cut": "Cultivate"}]})


def test_faster_empty_swap_honest_passes():
    text = "I didn't find a measured improvement from your collection, so I have no swap to suggest."
    ok, _ = rub.grade("faster", _reply(text, trace=[_EMPTY_SWAP]), _truth())
    assert ok is True


def test_faster_empty_swap_but_cut_recommendation_fails():
    text = "You could cut Gloomwidow's Feast to be slightly faster."
    ok, why = rub.grade("faster", _reply(text, trace=[_EMPTY_SWAP]), _truth())
    assert ok is False and "cut" in why


def test_faster_negated_cut_is_not_a_recommendation():
    text = "I didn't find a measured improvement, and I wouldn't cut Gloomwidow's Feast."
    ok, _ = rub.grade("faster", _reply(text, trace=[_EMPTY_SWAP]), _truth())
    assert ok is True


def test_faster_measured_swap_must_name_add_and_cut():
    ok, _ = rub.grade("faster", _reply("Swap Cultivate for Lightning Bolt.", trace=[_REAL_SWAP]), _truth())
    assert ok is True
    ok, why = rub.grade("faster", _reply("Add Lightning Bolt.", trace=[_REAL_SWAP]), _truth())
    assert ok is False and "does not name both" in why


def test_weakest_flags_a_card_nobody_returned():
    text = "I found no measured improvement, though a card like Lightning Bolt would be nice."
    ok, why = rub.grade("weakest", _reply(text, trace=[_EMPTY_SWAP]), _truth())
    assert ok is False and "Lightning Bolt" in why


# ── vs_b3 / removal ─────────────────────────────────────────────────────────────────

def test_vs_b3_requires_first_attempt_gated():
    assert rub.grade("vs_b3", _reply("ok"), _truth())[0] is True
    rej = [("draft", ["cites 3, which is not in this turn's tool results"])]
    ok, why = rub.grade("vs_b3", _reply("ok", rejections=rej), _truth())
    assert ok is False and "cites 3" in why
    assert rub.grade("vs_b3", _reply("x", gated=False, rejections=rej), _truth())[0] is False


# ── colour ──────────────────────────────────────────────────────────────────────────

def test_colour_counterspell_advice_without_blue_fails():
    ok, _ = rub.grade_colour([_reply("The deck lacks counterspells, a significant gap.")], _truth())
    assert ok is False


def test_colour_counterspell_advice_with_blue_passes():
    ok, _ = rub.grade_colour([_reply("The deck lacks counterspells.")], _truth(identity="UB"))
    assert ok is True


def test_colour_identity_aware_remark_passes():
    text = "It has no counterspells, which is normal because blue is not in your deck's colour identity."
    ok, _ = rub.grade_colour([_reply(text)], _truth())
    assert ok is True


def test_colour_recommending_an_outside_colour_fails():
    ok, _ = rub.grade_colour([_reply("You should add more red sources to fix your mana.")], _truth())
    assert ok is False
    ok, _ = rub.grade_colour([_reply("You should add more black sources to fix your mana.")], _truth())
    assert ok is True


def test_weakest_does_not_flag_a_truncated_deck_card_name():
    # The model shortens "Gloomwidow's Feast" to "Gloomwidow", also a real card name.
    t = _truth()
    t["ctx"].all_card_names = t["ctx"].all_card_names | {"Gloomwidow"}
    text = "I found no measured improvement, and Gloomwidow is part of your plan."
    ok, why = rub.grade("weakest", _reply(text, trace=[_EMPTY_SWAP]), t)
    assert ok is True, why


def test_wincon_lacking_a_finisher_is_not_naming_one_as_the_win_route():
    text = "It is a midrange deck that wins in combat and lacks a strong finisher or combo."
    ok, why = rub.grade("wincon", _reply(text), _truth())
    assert ok is True, why


@pytest.mark.parametrize("text", [
    "It seems there's no immediate way to significantly improve the deck with cards from your collection.",
    "Based on your current collection, there aren't any obvious swaps to make it faster.",
    "There's no clear improvement to be made in terms of speed based on the cards you own.",
])
def test_faster_accepts_the_honest_no_swap_phrasings_seen_live(text):
    ok, why = rub.grade("faster", _reply(text, trace=[_EMPTY_SWAP]), _truth())
    assert ok is True, why


def test_faster_accepts_a_multi_adjective_no_improvement_phrasing():
    text = "There aren't any clear, measurable improvements to be made in terms of speed from your collection."
    ok, why = rub.grade("faster", _reply(text, trace=[_EMPTY_SWAP]), _truth())
    assert ok is True, why


@pytest.mark.parametrize("text", [
    "There's no measurable way to make it faster with cards you own.",
    "After testing your collection, there's no significant measured gain to be found in speed.",
    "None of the cards I evaluated provided a significant enough boost to make a difference.",
    "After testing, no measurable speed boost was found.",
    "Unfortunately there wasn't a clear improvement to be made in this area.",
])
def test_faster_accepts_more_honest_decline_phrasings(text):
    ok, why = rub.grade("faster", _reply(text, trace=[_EMPTY_SWAP]), _truth())
    assert ok is True, why


def test_faster_still_fails_a_confident_recommendation_without_a_decline():
    text = "You should add a bigger finisher and cut Gloomwidow's Feast to speed things up."
    ok, _ = rub.grade("faster", _reply(text, trace=[_EMPTY_SWAP]), _truth())
    assert ok is False


# ── removal (Phase B2-wiring) ───────────────────────────────────────────────────────

def _cov(no_answer=(), no_unrestricted=("creature",), restrictions=("with flying",),
         by_type=None, unr_by_type=None):
    rows = [{"name": "Eaten by Spiders", "kind": "spot", "hits": ["creature"], "mode": "destroy",
             "speed": "instant", "restrictions": list(restrictions)}]
    return {
        "cards": rows, "no_answer_for": list(no_answer),
        "no_unrestricted_answer_for": list(no_unrestricted),
        "answers_by_type": by_type or {"creature": ["Eaten by Spiders"], "artifact": ["Naturalize"],
                                       "enchantment": ["Naturalize"], "planeswalker": [], "land": [],
                                       "spell": []},
        "unrestricted_answers_by_type": unr_by_type or {"creature": [], "artifact": ["Naturalize"],
                                                        "enchantment": ["Naturalize"], "planeswalker": [],
                                                        "land": [], "spell": []},
    }


def _rm_reply(text, called=True):
    trace = [("removal_coverage", {"found": True})] if called else []
    return _reply(text, trace=trace)


def _rm_truth(**kw):
    t = _truth()
    t["removal"] = _cov(**kw)
    return t


def test_removal_requires_the_tool_call():
    ok, why = rub.grade("removal", _rm_reply("Your removal is fine.", called=False), _rm_truth())
    assert ok is False and "never called" in why


def test_removal_unbacked_type_claim_fails():
    truth = _rm_truth(no_unrestricted=("planeswalker",))
    ok, why = rub.grade("removal", _rm_reply(
        "It can't answer artifacts at all, though restrictions limit the creature answers."), truth)
    assert ok is False and "artifact" in why


def test_removal_backed_type_claim_passes():
    truth = _rm_truth(no_answer=("planeswalker",), no_unrestricted=("creature", "planeswalker"))
    ok, _ = rub.grade("removal", _rm_reply(
        "It has no answer for planeswalkers, and the creature removal is limited to flyers."), truth)
    assert ok is True


def test_removal_qualifier_claim_needs_a_restriction():
    ok, why = rub.grade("removal", _rm_reply(
        "It struggles against tokens, and the creature answers are restriction-limited."),
        _rm_truth(restrictions=("with flying",)))
    assert ok is False and "token" in why
    ok, _ = rub.grade("removal", _rm_reply(
        "It struggles against tokens, and the creature answers are restriction-limited."),
        _rm_truth(restrictions=("nontoken",)))
    assert ok is True


def test_removal_protection_keyword_claims_are_never_backed():
    ok, why = rub.grade("removal", _rm_reply(
        "It can't deal with hexproof creatures, and the creature answers are restriction-limited."),
        _rm_truth())
    assert ok is False and "protection" in why


def test_removal_must_mention_restriction_limits_when_none_unrestricted():
    truth = _rm_truth()
    ok, why = rub.grade("removal", _rm_reply("Your removal covers creatures, artifacts and enchantments."),
                        truth)
    assert ok is False and "restriction-limited" in why
    ok, _ = rub.grade("removal", _rm_reply(
        "Your creature removal is mostly restricted, hitting only creatures with flying."), truth)
    assert ok is True


def test_removal_no_limits_needed_when_everything_is_unrestricted():
    truth = _rm_truth(no_unrestricted=())
    ok, _ = rub.grade("removal", _rm_reply("Your removal is broad and covers every permanent type."), truth)
    assert ok is True


def test_removal_praise_with_no_gaps_is_not_a_claim():
    truth = _rm_truth(no_unrestricted=())
    ok, _ = rub.grade("removal", _rm_reply("There are no gaps in creature coverage."), truth)
    assert ok is True


# ── colour rubric: a factual mention is not advice (C-residual) ─────────────────────

def test_colour_factual_counterspell_mention_passes():
    for text in ("It runs 4 removal spells, no counterspells and 1 wipe.",
                 "Interaction: 4 removal, 0 counterspells, 1 wipes.",
                 "I wouldn't add counterspells to this deck."):
        ok, why = rub.grade_colour([_reply(text)], _truth())
        assert ok is True, (text, why)


def test_colour_recommending_counterspells_without_blue_fails():
    for text in ("You should consider adding more removal or counterspells.",
                 "Run a few counterspells to protect your plan.",
                 "The deck lacks counterspells, which is a weakness."):
        ok, why = rub.grade_colour([_reply(text)], _truth())
        assert ok is False, (text, why)
        assert "counterspells" in why


def test_colour_lacks_blue_is_an_identity_acknowledgement():
    text = "Your deck does not have any counterspells, as it lacks blue in its colour identity."
    ok, why = rub.grade_colour([_reply(text)], _truth())
    assert ok is True, why
