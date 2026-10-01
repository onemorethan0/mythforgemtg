"""Gate check 6 (PLAN_MENTOR_ADHOC F1): a reply must not argue against a verdict the engine
measured. Offline and sim-free: the phrase maps in `mentor.verdicts` and the budget plumbing in
`mentor.gate`. Bias under test is UNDER-flagging -- every axis is tried in both directions and
against unrelated prose that merely shares a word with a verdict phrase."""

from __future__ import annotations

import pytest

from mythgauntlet.mentor import gate, verdicts
from mythgauntlet.mentor.tools import ToolResult

RESILIENT = {"resilience": "resilient", "speed": "moderate", "consistency": "moderate",
             "interaction": "moderate", "archetype": "midrange"}


def _reasons(text: str, **measured: str) -> list[str]:
    return verdicts.profile_contradictions(text, {**RESILIENT, **measured})


# -- resilience ------------------------------------------------------------------------

def test_resilient_deck_called_vulnerable_is_flagged():
    assert _reasons("The deck is vulnerable to board wipes.")
    assert _reasons("It folds to a single wrath effect.")


def test_hedged_vulnerable_for_a_resilient_deck_is_flagged():
    """The original inversion: 'somewhat vulnerable' for a deck measured 93/100."""
    assert _reasons("It is somewhat vulnerable to board wipes since it relies on creatures.")


def test_vulnerable_deck_called_resilient_is_flagged():
    assert _reasons("The deck shrugs off board wipes and bounces back.", resilience="vulnerable")
    assert _reasons("It is resilient to wipes.", resilience="vulnerable")


def test_agreeing_resilience_claims_are_not_flagged():
    assert not _reasons("It is resilient to board wipes and recovers quickly.")
    assert not _reasons("It is fairly resilient to wipes.")           # hedged, same direction
    assert not _reasons("It folds to board wipes.", resilience="vulnerable")


def test_a_measured_moderate_band_is_contradicted_by_nothing():
    """Under-flag: the gate only argues with the OPPOSITE end of a measured verdict."""
    assert not _reasons("The deck is resilient to wipes.", resilience="moderate")
    assert not _reasons("The deck is vulnerable to board wipes.", resilience="moderate")


def test_a_negated_claim_is_not_a_claim():
    assert not _reasons("It is not vulnerable to board wipes.")


def test_vulnerable_to_something_else_is_not_a_wipe_claim():
    assert not _reasons("It is vulnerable to flyers and to decks with strong interaction.")
    assert not _reasons("Your creature base is fragile against spot removal.")


def test_moderately_interactive_is_not_a_resilience_claim():
    """The orchestrator's false positive on the Shelob overview: 'moderately' belongs to
    'interactive', not to the wipes two words back."""
    text = ("It's a slow but consistent deck that's resilient to wipes and moderately "
            "interactive, but it lacks a strong finisher.")
    assert verdicts.claimed_resilience(text) == {"resilient"}
    assert not _reasons(text)
    # and in the other order of nouns
    assert verdicts.claimed_resilience(
        "It survives a wipe well and is moderately interactive.") == {"resilient"}


def test_bound_axis_picks_the_nearest_topic_and_declines_a_tie():
    s = "resilient to wipes and moderately interactive"
    m = verdicts.re.search(r"moderately", s)
    assert verdicts.bound_axis(s, m) == "interaction"
    m2 = verdicts.re.search(r"resilient", s)
    assert verdicts.bound_axis(s, m2) == "resilience"
    tie = "wipes moderately interactive"      # one topic word each side, equal distance
    assert verdicts.bound_axis(tie, verdicts.re.search(r"moderately", tie)) is None
    assert verdicts.bound_axis("nothing relevant here", verdicts.re.search(r"here", "x here")) is None


# -- speed -----------------------------------------------------------------------------

def test_fast_claim_on_a_slow_deck_is_flagged():
    for text in ("This is a fast deck that wins early.",
                 "Your deck is already quite fast.",
                 "It kills quickly."):
        assert _reasons(text, speed="slow"), text
        assert _reasons(text, speed="none"), text


def test_slow_claim_on_a_fast_deck_is_flagged():
    assert _reasons("It is a slow deck that grinds.", speed="fast")
    assert _reasons("The deck is very slow.", speed="fast")


def test_speed_agreement_and_moderate_are_not_flagged():
    assert not _reasons("Your deck is already quite fast.", speed="fast")
    assert not _reasons("Your deck is already quite fast.", speed="moderate")
    assert not _reasons("It is a slow deck.", speed="slow")
    assert not _reasons("It is pretty fast.", speed="moderate")


def test_speed_words_in_unrelated_prose_are_not_flagged():
    assert not _reasons("Fast mana like Sol Ring is already quite fast at ramping.", speed="slow")
    assert not _reasons("The commander gets out quickly thanks to the ramp.", speed="slow")
    assert not _reasons("Cultivate is a really quick way to fix colours.", speed="slow")  # no deck topic


# -- consistency -----------------------------------------------------------------------

def test_consistency_both_directions():
    assert _reasons("The deck is inconsistent and clunky.", consistency="consistent")
    assert _reasons("It is a very consistent deck.", consistency="shaky")
    assert not _reasons("It is a very consistent deck.", consistency="consistent")
    assert not _reasons("The deck is inconsistent.", consistency="shaky")
    assert not _reasons("The deck is inconsistent.", consistency="moderate")


def test_consistency_words_in_unrelated_prose_are_not_flagged():
    assert not _reasons("That is consistent with the rules text.", consistency="shaky")
    assert not _reasons("That reading is inconsistent with the rules text.", consistency="consistent")
    assert not _reasons("Rule 704 is unreliable as a source here.", consistency="consistent")


# -- interaction -----------------------------------------------------------------------

def test_interaction_both_directions():
    assert _reasons("The deck has thin interaction.", interaction="deep")
    assert _reasons("It lacks interaction.", interaction="deep")
    assert _reasons("It has deep interaction.", interaction="thin")
    assert not _reasons("It has deep interaction.", interaction="deep")
    assert not _reasons("It has thin interaction.", interaction="thin")
    assert not _reasons("It has thin interaction.", interaction="moderate")


def test_a_specific_gap_is_not_an_interaction_verdict():
    assert not _reasons("It lacks interaction for planeswalkers.", interaction="deep")
    assert not _reasons("Strong interaction and thin interaction are both relative.",
                        interaction="moderate")


# -- archetype -------------------------------------------------------------------------

def test_archetype_label_from_another_family_is_flagged():
    assert _reasons("This is a control deck at heart.", archetype="midrange")
    assert _reasons("It plays like a combo deck.", archetype="go_wide")


def test_compatible_labels_and_bare_words_are_not_flagged():
    assert not _reasons("It is an aggressive deck that goes wide.", archetype="midrange")
    assert not _reasons("It has a few control elements like counterspells.", archetype="midrange")
    assert not _reasons("This is a control deck.", archetype="unknown")


def test_unknown_or_missing_verdicts_skip_the_axis():
    assert not verdicts.profile_contradictions("It is vulnerable to wipes.", {})
    assert not verdicts.profile_contradictions(
        "It is vulnerable to wipes.", {"resilience": "unknown"})


# -- gate wiring -----------------------------------------------------------------------

_PROFILE = {"found": True, "axes": {"resilience": {"score": 93.0}},
            "verdicts": {"resilience": "resilient", "speed": "slow", "consistency": "consistent",
                         "interaction": "moderate", "archetype": "midrange"}}


def test_budget_detects_the_profile_result_by_shape():
    budget = gate.ClaimBudget.from_tool_results([ToolResult(data=_PROFILE)])
    assert budget.profile_verdicts["resilience"] == "resilient"
    assert budget.profile_verdicts["archetype"] == "midrange"
    # a result without the verdicts+axes pair never licenses a verdict check
    assert not gate.ClaimBudget.from_tool_results(
        [ToolResult(data={"found": True, "verdicts": {"resilience": "resilient"}})]).profile_verdicts
    assert not gate.ClaimBudget.from_tool_results([ToolResult(data={"found": False})]).profile_verdicts


def test_check_rejects_a_contradicting_reply_and_names_the_measured_verdict():
    budget = gate.ClaimBudget.from_tool_results([ToolResult(data=_PROFILE)])
    reasons = gate.check("Your deck is somewhat vulnerable to board wipes, which is a concern.", budget)
    assert any("resilience" in r and "resilient" in r for r in reasons)
    reasons = gate.check("Your deck is already quite fast and wins in the early turns.", budget)
    assert any("speed" in r and "slow" in r for r in reasons)


def test_check_passes_a_faithful_reply_and_runs_only_with_the_profile():
    budget = gate.ClaimBudget.from_tool_results([ToolResult(data=_PROFILE)])
    assert not gate.check("It is resilient to wipes, a slow but consistent midrange deck.", budget)
    # without the profile result there is nothing to contradict
    assert not gate.check("Your deck is somewhat vulnerable to board wipes.",
                          gate.ClaimBudget.from_tool_results([]))


def test_the_later_profile_result_wins():
    other = {**_PROFILE, "verdicts": {**_PROFILE["verdicts"], "resilience": "vulnerable"}}
    budget = gate.ClaimBudget.from_tool_results([ToolResult(data=_PROFILE), ToolResult(data=other)])
    assert budget.profile_verdicts["resilience"] == "vulnerable"


@pytest.mark.parametrize("text", [
    "I didn't find a measured improvement from your collection.",
    "Cultivate and Beast Whisperer do the most work.",
    "Your commander comes down on turn six on average.",
])
def test_unrelated_prose_passes(text):
    budget = gate.ClaimBudget.from_tool_results([ToolResult(data=_PROFILE)])
    assert not [r for r in gate.check(text, budget) if "contradicting" in r]
