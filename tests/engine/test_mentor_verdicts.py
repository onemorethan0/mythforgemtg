"""mentor.verdicts -- bands, archetype families and the phrase maps the holistic bench and
(later) the gate share. Pure text/number tests: no engine, no model."""

from types import SimpleNamespace

import pytest

from mythgauntlet.mentor import verdicts as v


# ── bands ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("score,band", [
    (93, "resilient"), (65, "resilient"), (64.9, "moderate"), (40, "moderate"),
    (39.9, "vulnerable"), (0, "vulnerable"), (None, "unknown"),
])
def test_resilience_band_thresholds(score, band):
    assert v.resilience_band(score) == band


@pytest.mark.parametrize("turn,rate,band", [
    (5.0, 0.6, "fast"), (6.0, 0.6, "fast"), (7.5, 0.5, "moderate"), (9.0, 0.5, "moderate"),
    (9.4, 0.5, "slow"), (5.0, 0.1, "none"), (None, 0.0, "none"), (5.0, None, "none"),
])
def test_speed_band(turn, rate, band):
    assert v.speed_band(turn, rate) == band


def test_archetype_family_covers_every_insight_spelling():
    assert v.archetype_family("Midrange goodstuff") == "midrange"
    assert v.archetype_family("Ramp / midrange") == "midrange"
    assert v.archetype_family("Spellslinger / storm") == "spellslinger"
    assert v.archetype_family("Go-wide / tokens") == "go_wide"
    assert v.archetype_family("Creature aggro") == "aggro"
    assert v.archetype_family("Control") == "control"
    assert v.archetype_family("Combo") == "combo"
    assert v.archetype_family("something new") == "unknown"
    assert v.archetype_family(None) == "unknown"


def test_archetype_families_match_the_strings_insight_can_emit():
    """Lock-step: every archetype string literally assigned in insight.build_insight must
    be in the family map, or a new archetype silently degrades to "unknown"."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "src" / "mythgauntlet" / "ratings" / "insight.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'archetype = "([^"]+)"', src))
    assert emitted and emitted <= set(v.ARCHETYPE_FAMILIES), emitted - set(v.ARCHETYPE_FAMILIES)


def _analysis(res=93.0, turn=9.0, rate=0.6, cons=82.0, inter=60.0, archetype="Midrange goodstuff"):
    return SimpleNamespace(
        resilience=SimpleNamespace(resilience_score=res) if res is not None else None,
        report=SimpleNamespace(avg_kill_turn=turn, goldfish_kill_rate=rate, consistency_score=cons),
        interaction=SimpleNamespace(score=inter),
        insight=SimpleNamespace(archetype=archetype),
    )


def test_classify_profile_reads_every_measured_field():
    out = v.classify_profile(_analysis())
    assert out == {"resilience": "resilient", "speed": "moderate", "consistency": "consistent",
                   "interaction": "deep", "archetype": "midrange"}


def test_classify_profile_unmeasured_resilience_is_unknown_not_guessed():
    assert v.classify_profile(_analysis(res=None))["resilience"] == "unknown"


# ── resilience phrase map ───────────────────────────────────────────────────────────

def test_plain_resilient_claim():
    assert v.claimed_resilience("This deck is very resilient to board wipes.") == {"resilient"}


def test_plain_vulnerable_claim():
    assert v.claimed_resilience("It is vulnerable to board wipes.") == {"vulnerable"}


def test_hedged_claim_reads_as_moderate():
    assert v.claimed_resilience("It looks somewhat vulnerable to a board wipe.") == {"moderate"}


def test_negated_claim_is_dropped_not_inverted():
    assert v.claimed_resilience("It is not vulnerable to board wipes.") == set()


def test_sentence_must_be_about_wipes_or_resilience():
    # "vulnerable to flyers" is not a wipe-resilience verdict.
    assert v.claimed_resilience("The deck is vulnerable to flyers and small tokens.") == set()


def test_explicit_moderate_words_are_a_moderate_claim():
    assert v.claimed_resilience("Its resilience to a wrath is decent.") == {"moderate"}
    # A moderate word outside a wipe/resilience sentence is not a resilience claim.
    assert v.claimed_resilience("The mana curve is decent.") == set()


def test_resilience_claim_across_sentences_collects_both():
    text = "Against a wrath it holds up well. But creature-reliant lines fold to sweepers."
    assert v.claimed_resilience(text) == {"resilient", "vulnerable"}


# ── speed phrase map ────────────────────────────────────────────────────────────────

def test_speed_claims_are_narrow():
    assert v.claimed_speed("Fast mana helps you ramp out.") == set()
    assert v.claimed_speed("It is a slow deck that grinds value.") == {"slow"}
    assert v.claimed_speed("This is a fast deck.") == {"fast"}


def test_speed_agrees_only_with_a_plain_opposite_claim():
    assert v.speed_agrees("slow", {"slow"})
    assert not v.speed_agrees("slow", {"fast"})
    assert v.speed_agrees("moderate", {"fast"})       # moderate contradicts neither plain claim
    assert v.speed_agrees("fast", {"moderate"})       # hedged claim never contradicts
    assert v.speed_agrees("none", {"slow"})
    assert not v.speed_agrees("none", {"fast"})
    assert v.speed_agrees("fast", set())


# ── archetype labels ────────────────────────────────────────────────────────────────

def test_control_label_contradicts_midrange():
    assert v.archetype_contradictions("It plays as a control deck with powerful finishers.",
                                      "Midrange goodstuff") == ["control"]


def test_combat_family_labels_are_interchangeable():
    assert v.archetype_contradictions("A tokens strategy that goes wide.", "Midrange goodstuff") == []
    assert v.archetype_contradictions("An aggressive build.", "Go-wide / tokens") == []


def test_bare_words_do_not_label_the_deck():
    assert v.archetype_contradictions("It runs a few combo pieces and some control magic.",
                                      "Midrange goodstuff") == []


def test_unknown_archetype_contradicts_nothing():
    assert v.archetype_contradictions("a control deck", "brand new archetype") == []


def test_states_archetype_or_route():
    assert v.states_archetype_or_route("A midrange deck.", "Midrange goodstuff")
    assert v.states_archetype_or_route("It wins by attacking with big creatures.", "Midrange goodstuff")
    assert not v.states_archetype_or_route("It has good cards.", "Midrange goodstuff")
    assert not v.states_archetype_or_route("It attacks with creatures.", "Control")


def test_strength_topic_reads_insight_leads():
    assert v.strength_topic("Consistent engine (82/100) -- commander lands ~T4") == "consistency"
    assert v.strength_topic("Resilient to wipes (93/100)") == "resilience"
    assert v.strength_topic("Deep interaction (9 answers, 3/3 types)") == "interaction"
    assert v.strength_topic("High ceiling (50/100)") == "ceiling"
    assert v.strength_topic("Strong multiplayer closing power (60/100)") == "pod"
    assert v.strength_topic("unrelated") is None


def test_strength_leads_match_insight_source():
    """Lock-step with insight._verdict: every strengths.append lead must map to a topic."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "src" / "mythgauntlet" / "ratings" / "insight.py").read_text(encoding="utf-8")
    leads = re.findall(r'strengths\.append\(\s*f?"([A-Za-z ]+)', src)
    assert leads
    for lead in leads:
        assert v.strength_topic(lead) is not None, lead


def test_verdict_phrase_must_sit_near_the_topic_word():
    # Found live on Shelob: a moderate INTERACTION sentence whose answer list ends in
    # "1 wipes" was read as a moderate wipe-resilience claim.
    text = "The deck has moderate interaction with 4.5 castable answers (4 removal, 0 counters, 1 wipes)."
    assert v.claimed_resilience(text) == set()
    assert v.claimed_resilience("Its resilience to a wipe is moderate.") == {"moderate"}
