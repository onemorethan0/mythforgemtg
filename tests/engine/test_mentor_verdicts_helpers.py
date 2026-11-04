"""Direct tests for mentor/verdicts.py helpers that were only exercised indirectly through the gate:
the band functions, sentence splitting, claim extraction (negation, hedging, opponents), relative-to-
bracket framing, swap-axis families, clock figures and commander aliases.

The claim extractors are deliberately NARROW (they under-flag so the gate never rejects a fair reply),
so these pin the phrasings that must be caught and the ones that must never be."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from mythgauntlet.mentor import verdicts as v


# -- bands -------------------------------------------------------------------------------------------

def test_interaction_band_boundaries():
    assert v.interaction_band(None) == "unknown"
    assert v.interaction_band(v.DEEP_INTERACTION_MIN) == "deep"          # the floor is inclusive
    assert v.interaction_band(v.DEEP_INTERACTION_MIN - 0.01) == "moderate"
    assert v.interaction_band(v.THIN_INTERACTION_MAX) == "moderate"      # the thin ceiling is exclusive
    assert v.interaction_band(v.THIN_INTERACTION_MAX - 0.01) == "thin"
    assert v.interaction_band(0) == "thin" and v.interaction_band(100) == "deep"


def test_table_feel_band_never_says_friendly_for_an_unmeasured_deck():
    assert v.table_feel_band(None) == "unknown"
    assert v.table_feel_band(NS(available=False, band="friendly")) == "unknown"
    assert v.table_feel_band(NS(band="friendly")) == "unknown"            # no `available` attr at all
    assert v.table_feel_band(NS(available=True, band="spicy")) == "spicy"


# -- families / swap axes ------------------------------------------------------------------------------

def test_compatible_families_groups_related_archetypes_and_defaults_to_itself():
    assert {"midrange", "aggro"} <= v.compatible_families("midrange")
    assert v.compatible_families("aggro") == v.compatible_families("midrange")
    assert v.compatible_families("not_a_family") == frozenset({"not_a_family"})


def test_swap_axis_family_maps_clock_to_speed():
    assert v.swap_axis_family("clock") == "speed"
    assert v.swap_axis_family("resilience") == "resilience"
    assert v.swap_axis_family(None) is None and v.swap_axis_family("nonsense") is None


# -- sentences ---------------------------------------------------------------------------------------------

def test_split_sentences_on_terminal_punctuation_and_drops_blanks():
    assert v.split_sentences("It is fast. But not resilient! Is it? Yes.") == [
        "It is fast.", "But not resilient!", "Is it?", "Yes."]
    assert v.split_sentences("") == [] and v.split_sentences("   ") == []


def test_split_sentences_keeps_a_decimal_number_together():
    assert v.split_sentences("It costs 2.5 mana. Fine.") == ["It costs 2.5 mana.", "Fine."]


# -- claim extraction ----------------------------------------------------------------------------------------

def test_resilience_claims_plain_hedged_and_negated():
    assert v.resilience_claims("The deck is very resilient to wipes.") == [("resilient", "plain")]
    assert v.resilience_claims("It is somewhat vulnerable to board wipes.") == [("vulnerable", "hedged")]
    assert v.resilience_claims("Moderate resilience to wipes.") == [("moderate", "plain")]
    assert v.resilience_claims("The deck is quite vulnerable to wipes.") == [("vulnerable", "plain")]
    assert v.resilience_claims("It is not vulnerable to wipes.") == []           # negation cancels it


def test_resilience_claims_need_the_topic_in_the_sentence():
    # 'vulnerable' about a single card and a different threat is not a claim about wipes
    assert v.resilience_claims("Bonecrusher Giant is quite vulnerable to Swords to Plowshares.") == []
    assert v.resilience_claims("Your commander is very vulnerable to removal.") == []
    assert v.resilience_claims("") == []


def test_speed_claims_catch_the_explicit_phrases_and_skip_opponents_and_mana():
    assert v.speed_claims("It kills quickly.") == [("fast", "plain")]
    assert v.speed_claims("This is a very fast deck.") and v.speed_claims("A slow deck that grinds.")
    assert v.speed_claims("Opponents are very fast decks.") == []         # about the other side
    assert v.speed_claims("A fast mana rock helps.") == []                 # 'fast mana' is not a speed claim
    assert v.speed_claims("It is not a fast deck.") == []


def test_speed_claims_intensifier_form_and_hedging():
    plain = v.speed_claims("The deck is really fast.")
    hedged = v.speed_claims("The deck is fairly fast.")
    assert plain == [("fast", "plain")] and hedged == [("fast", "hedged")]
    assert v.claimed_speed("The deck is fairly fast.") == {"moderate"}      # hedged -> moderate
    assert v.claimed_speed("The deck is really slow.") == {"slow"}


def test_consistency_claims():
    assert v.consistency_claims("It is very consistent.") == [("consistent", "plain")]
    assert v.consistency_claims("Consistency is shaky.") == [("shaky", "plain")]
    assert v.consistency_claims("Its consistency is high.") == [("consistent", "plain")]
    assert v.consistency_claims("somewhat inconsistent mana") == [("shaky", "hedged")]
    assert v.consistency_claims("It is not consistent.") == []
    assert v.consistency_claims("Its consistency is not shaky.") == []


# -- relative framing ----------------------------------------------------------------------------------------------------

def test_absolute_claims_text_drops_relative_to_bracket_sentences():
    out = v.absolute_claims_text("It is fast for its bracket. It is resilient. B3 decks are slower.")
    assert out == "It is resilient."
    assert v.absolute_claims_text("Nothing relative here.") == "Nothing relative here."
    assert v.absolute_claims_text("") == ""


# -- clock figures ---------------------------------------------------------------------------------------------------------

def test_clock_figures_collect_scores_to_one_decimal():
    data = {"baseline": 10.04, "current": {"score": 12.0},
            "suggestions": [{"before": 10, "after": 12.349, "brief": {"delta": 2.3}}]}
    scores, kills = v.clock_figures([data])
    assert scores == {10.0, 12.0, 12.3, 2.3}
    assert kills == set()


def test_clock_figures_tolerate_junk_and_empty_input():
    assert v.clock_figures([]) == (set(), set())
    assert v.clock_figures([{}, {"suggestions": ["not a dict", None]}, {"baseline": "n/a"}]) == (set(), set())


# -- commander aliases ----------------------------------------------------------------------------------------------------------

def test_commander_aliases_full_comma_and_first_word_longest_first():
    out = v.commander_aliases(["Thrasios, Triton Hero", "Smaug the Impenetrable"])
    assert "Thrasios" in out and "Thrasios, Triton Hero" in out
    assert "Smaug" in out and "Smaug the Impenetrable" in out
    assert out == sorted(out, key=len, reverse=True)


def test_commander_aliases_skip_articles_short_names_and_junk():
    out = v.commander_aliases(["The Ur-Dragon", "Fire // Ice", "", "x", None, 7])
    assert "The" not in out                      # an article is never an alias
    assert "The Ur-Dragon" in out and "Fire" in out and "Fire // Ice" in out
    assert "x" not in out                        # under three characters
    assert v.commander_aliases(None) == [] and v.commander_aliases([]) == []
