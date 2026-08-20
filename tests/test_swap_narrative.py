"""The faithfulness gate for generated swap explanations.

Offline and model-free by construction: every test here calls `check`, never `narrate`. The
gate is the contract — the generator behind it is replaceable, and a test that needed a live
LLM could not run in CI (invariant #5).

Each case names the draft it rejects. Most were found by reading real qwen3:32b output rather
than imagined, and the two marked FALSE POSITIVE are the ones that mattered most: a gate that
rejects faithful prose silently starves the corpus of exactly the drafts worth keeping.
"""

from __future__ import annotations

import pytest

import swap_narrative as sn


def brief(**over) -> dict:
    """A measured swap: Jubilation in, An Offer You Can't Refuse out, Ceiling 3.4 -> 6.9.

    The cut's counterspell role is genuinely over-supplied (6.0 against a target of 3), so
    redundancy language is permitted unless a test turns that off.
    """
    base = {
        "axis": "ceiling",
        "axis_label": "Ceiling",
        "before": 3.4,
        "after": 6.9,
        "delta": 3.4,
        "noise_floor": 2.27,
        "commander": "Omo, Queen of Vesuva",
        "archetypes": ["landfall"],
        "add": {"name": "Jubilation", "mana_value": 6, "type_line": "Creature",
                "functions": {"team pump": 2.0}, "edhrec_rank": 6013},
        "cut": {"name": "An Offer You Can't Refuse", "mana_value": 1, "type_line": "Instant",
                "functions": {"counterspell": 1.0}, "edhrec_rank": 35,
                "role": "counterspell", "role_supply": 6.0, "role_target": 3,
                "oversupply": 3.0, "within_role": 4.5, "protected": False,
                "redundancy_backed": True},
        "kill_turn_before": 7.9, "kill_turn_after": 7.9,
        "kill_rate_before": 0.08, "kill_rate_after": 0.04,
        "allowed_card_names": ["Jubilation", "An Offer You Can't Refuse",
                               "Omo, Queen of Vesuva"],
    }
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


FAITHFUL = (
    "Jubilation is a team pump that turns your board into one lethal swing, which is what "
    "this deck's Ceiling was missing. An Offer You Can't Refuse is the cut because "
    "counterspells are the role you are over-supplied in, at 6.0 against a target of 3."
)

DECK = {"Cyclonic Rift", "Sol Ring", "Vesuva", "Azami, Lady of Scrolls"}


def test_a_faithful_draft_passes():
    assert sn.check(FAITHFUL, brief(), deck_card_names=DECK) == []


def test_it_rejects_a_card_the_deck_does_not_contain():
    """The worst failure mode: inventing a card into someone's decklist."""
    text = FAITHFUL + " Cyclonic Rift already covers that role for you."
    reasons = sn.check(text, brief(), deck_card_names=DECK)
    assert any("Cyclonic Rift" in r for r in reasons)


def test_a_card_name_nested_inside_an_allowed_one_is_not_foreign():
    """FALSE POSITIVE, found on real output.

    Magic card names nest: the commander "Omo, Queen of Vesuva" contains "Vesuva", which is
    itself a real card. Scanning the raw text flagged a sentence that only ever named the
    commander, so the allowed names have to be masked out before the foreign-name scan.
    """
    text = ("Jubilation pumps the team, which fits Omo, Queen of Vesuva's land strategy. "
            "An Offer You Can't Refuse is the over-supplied counterspell to cut here.")
    assert sn.check(text, brief(), deck_card_names=DECK) == []


def test_it_rejects_a_number_that_is_not_in_the_brief():
    text = ("Jubilation is a team pump worth roughly 22.4 points of Ceiling here, so An "
            "Offer You Can't Refuse is the natural cut from an over-supplied role.")
    assert any("22.4" in r for r in sn.check(text, brief(), deck_card_names=DECK))


def test_it_rejects_a_function_the_vector_does_not_show():
    text = ("Jubilation is a board wipe that resets the table and lifts your Ceiling. An "
            "Offer You Can't Refuse is over-supplied at 6.0 against a target of 3.")
    reasons = sn.check(text, brief(), deck_card_names=DECK)
    assert any("board wipe" in r and "Jubilation" in r for r in reasons)


def test_a_function_claimed_about_the_add_is_not_charged_to_the_cut():
    """FALSE POSITIVE, and it rejected two of three real drafts before it was fixed.

    English puts the subject before the predicate, so a clause describes the last card named.
    Attributing by nearest-name-in-either-direction charged "team pump" to the CUT, because by
    the time the phrase appears the cut's name is closer than the add's.
    """
    text = ("Adding Jubilation gives the deck a team pump that closes games. Cutting An "
            "Offer You Can't Refuse trims a counterspell role sitting at 6.0 against 3.")
    assert sn.check(text, brief(), deck_card_names=DECK) == []


def test_it_rejects_prose_that_contradicts_the_measured_direction():
    text = ("Jubilation lowers ceiling slightly but is worth it. An Offer You Can't Refuse "
            "is over-supplied at 6.0 against a target of 3 and is the natural cut.")
    assert any("lowers ceiling" in r for r in sn.check(text, brief(), deck_card_names=DECK))


def test_it_rejects_a_claim_about_an_axis_nobody_measured():
    """One axis is measured per swap. "does not hurt consistency" is still a claim.

    The stem matters: real drafts say "more consistent", never "more consistency", and a
    literal match on the noun let every one of them through.
    """
    text = ("Jubilation is a team pump that raises Ceiling, and it makes the deck far more "
            "consistent without giving up anything. An Offer You Can't Refuse is the cut.")
    assert any("consistency" in r for r in sn.check(text, brief(), deck_card_names=DECK))


def test_it_refuses_redundancy_language_when_nothing_is_over_supplied():
    """The S12 guard.

    On 9.0% of corpus decks NO role is over-supplied, `rank_redundant` still owes its caller
    `k` candidates, and it falls through to a least-played tiebreak. Calling that cut
    "redundant" invents the finding the module failed to make.
    """
    unbacked = brief(cut={"redundancy_backed": False, "oversupply": 0.0})
    reasons = sn.check(FAITHFUL, unbacked, deck_card_names=DECK)
    assert any("over-supplies no role" in r for r in reasons)


def test_it_refuses_an_intensifier_the_gap_has_not_earned():
    """"16.5, well over the typical 16" is over by 0.5 — a rounding step read as a verdict.

    The number is true, so the numeric check passes it. Same shape as S3: a
    population-relative reading presented as an absolute one.
    """
    marginal = brief(cut={"oversupply": 0.5, "role_supply": 16.5, "role_target": 16,
                          "role": "draw", "functions": {"repeatable draw": 1.0}})
    text = ("Jubilation is a team pump that raises Ceiling. An Offer You Can't Refuse goes "
            "because card draw is well over the typical count for this archetype.")
    assert any("overstates" in r for r in sn.check(text, marginal, deck_card_names=DECK))


def test_a_marginal_gap_may_still_be_described_honestly():
    """The intensifier rule must not ban saying it at all — only overstating it."""
    marginal = brief(cut={"oversupply": 0.5, "role_supply": 16.5, "role_target": 16,
                          "role": "draw", "functions": {"repeatable draw": 1.0}})
    text = ("Jubilation is a team pump that raises Ceiling. An Offer You Can't Refuse goes "
            "because card draw is slightly over-supplied at 16.5 against 16.")
    assert sn.check(text, marginal, deck_card_names=DECK) == []


@pytest.mark.parametrize("raw,want", [
    ("*Jubilation* is a **team pump** for this deck and it raises the Ceiling nicely.",
     "Jubilation is a team pump for this deck and it raises the Ceiling nicely."),
    ("```\nJubilation is a team pump that raises the deck's Ceiling here.\n```",
     "Jubilation is a team pump that raises the deck's Ceiling here."),
    ("Reason: Jubilation is a team pump that raises the deck's Ceiling here.",
     "Jubilation is a team pump that raises the deck's Ceiling here."),
])
def test_strip_removes_the_wrappers_models_add(raw, want):
    """Markdown is a formatting tic, not a claim — stripped rather than rejected.

    The prompt forbids it and qwen3:32b emits `*Card Name*` on most drafts anyway. Rejecting
    a faithful sentence over asterisks would throw away good corpus rows.
    """
    assert sn._strip(raw) == want


def test_length_bounds_are_enforced():
    assert any("outside" in r for r in sn.check("Too short.", brief()))
    assert any("outside" in r for r in sn.check("word " * 200, brief()))


def test_allowed_numbers_matches_the_engine():
    """LOCK-STEP. The budget is computed twice and the two must not drift.

    `swap_narrative` cannot import the engine — Forge runs without `src/` on its path — so
    `allowed_numbers` is reimplemented over the brief's JSON form. Same duplication, and the
    same pinning, as `test_slug_matches_the_engine_implementation` for the EDHREC slug. A
    drift here silently widens or narrows what a narrative may cite.
    """
    from mythgauntlet.ratings.swap_brief import AddBrief, CutBrief, SwapBrief

    data = brief()
    engine = SwapBrief(
        axis=data["axis"], axis_label=data["axis_label"],
        before=data["before"], after=data["after"], delta=data["delta"],
        noise_floor=data["noise_floor"], commander=data["commander"],
        archetypes=data["archetypes"],
        add=AddBrief(**{k: v for k, v in data["add"].items()}),
        cut=CutBrief(**{k: v for k, v in data["cut"].items()}),
        kill_turn_before=data["kill_turn_before"], kill_turn_after=data["kill_turn_after"],
        kill_rate_before=data["kill_rate_before"], kill_rate_after=data["kill_rate_after"],
        allowed_card_names=data["allowed_card_names"],
    )
    assert sn.allowed_numbers(engine.as_dict()) == engine.allowed_numbers()


def test_the_prompt_carries_every_rule_the_gate_enforces():
    """A rule the gate checks but the prompt never states is a guaranteed rejection.

    Not cosmetic: measured on real output, adding the "only this axis" line took the keep
    rate from 3-of-7 attempts to 3-of-3 first attempts. The gate cannot teach; the prompt has
    to say what the gate will refuse.
    """
    system = sn.build_messages(brief())[0]["content"]
    for required in ("Jubilation", "An Offer You Can't Refuse", "Omo, Queen of Vesuva"):
        assert required in system, "the allowed card names must be stated"
    assert "Ceiling" in system
    for axis in ("consistency", "speed", "resilience", "interaction"):
        assert axis in system.lower(), "the other-axis rule must name them"
    assert "over-supplied" in system, "the redundancy rule must be stated"

    unbacked = sn.build_messages(brief(cut={"redundancy_backed": False}))[0]["content"]
    assert "not call it" in unbacked, "the S12 case needs the forbidding form of the rule"


def test_a_cut_may_be_called_by_the_role_the_engine_gave_it():
    """`card_roles` and `card_functions` speak different vocabularies, and conflating them
    rejects honest prose.

    A role is an aggregate over functions: role `draw` is `draw_cards + 1.5 * engine_draw`, so
    a card whose draw is entirely an ENGINE holds the function "repeatable draw" and no "card
    draw" at all — while the brief still reports its role as `draw`, and any writer will say
    "card draw". The widening applies only to the role the engine already granted.
    """
    engine_only = brief(cut={"role": "draw", "functions": {"repeatable draw": 1.0},
                             "oversupply": 4.0, "role_supply": 20.0, "role_target": 16})
    text = ("Jubilation is a team pump that raises Ceiling. An Offer You Can't Refuse goes "
            "because card draw is over-supplied at 20.0 against a target of 16.")
    assert sn.check(text, engine_only, deck_card_names=DECK) == []


def test_the_role_widening_does_not_license_an_unrelated_function():
    """It widens WITHIN the granted role — it is not a general amnesty."""
    engine_only = brief(cut={"role": "draw", "functions": {"repeatable draw": 1.0},
                             "oversupply": 4.0, "role_supply": 20.0, "role_target": 16})
    text = ("Jubilation is a team pump that raises Ceiling. An Offer You Can't Refuse is a "
            "board wipe the deck no longer needs, with draw over-supplied at 20.0.")
    reasons = sn.check(text, engine_only, deck_card_names=DECK)
    assert any("board wipe" in r for r in reasons)


def test_a_negator_printed_in_a_card_name_is_not_a_negation():
    """"An Offer You Can't Refuse is a board wipe" disarmed the gate.

    The negation guard exists so "does not counter anything" is not read as calling a card a
    counterspell. It looks at the characters just before the claim — which, for this card,
    are its own title. Magic prints plenty of these (Can't, Never, No Mercy), so the swap's
    card names are excluded from the negator scan.
    """
    text = ("Jubilation raises Ceiling. An Offer You Can't Refuse is a board wipe the deck "
            "does not need, with counterspells over-supplied at 6.0 against 3.")
    assert any("board wipe" in r for r in sn.check(text, brief(), deck_card_names=DECK))


def test_a_genuine_negation_is_still_respected():
    """The guard must keep doing its job — this is not a claim about the add."""
    text = ("Jubilation raises Ceiling and is not a board wipe, so the board survives. An "
            "Offer You Can't Refuse is the over-supplied counterspell at 6.0 against 3.")
    assert not any("board wipe" in r for r in sn.check(text, brief(), deck_card_names=DECK))
