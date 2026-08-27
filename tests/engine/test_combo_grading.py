"""Combo grading (Layer 1): metadata-only reliability that refines the bracket combo-gate.

Offline: combos are built through the real Spellbook parser from fixture payloads, never
constructed positionally, so the enrichment fields stay exercised end-to-end.
"""

from mythgauntlet.data.spellbook import (
    assess_combos,
    classify_combo,
    is_terminal_combo,
    parse_response,
)
from mythgauntlet.ratings.bracket import estimate_bracket


def _variant(cards, produces, **extra):
    v = {
        "id": extra.get("id", "x"),
        "uses": [{"card": {"name": c}} for c in cards],
        "produces": [{"feature": {"name": p}} for p in produces],
    }
    v.update({k: val for k, val in extra.items() if k != "id"})
    return v


def _report(*variants):
    return parse_response({"results": {"included": list(variants)}})


# --- enrichment survives parsing --------------------------------------------------------

def test_parse_enriches_mana_and_description():
    r = _report(_variant(
        ["A", "B"], ["Win the game"],
        manaValueNeeded=2, manaNeeded="{1}{U}", description="Cast A. Then B. Win.",
        notablePrerequisites="A on the battlefield.",
    ))
    c = r.included[0]
    assert c.mana_value == 2
    assert c.description.startswith("Cast A")
    assert c.notable_prerequisites == "A on the battlefield."


def test_parse_tolerates_missing_mana_value():
    r = _report(_variant(["A", "B"], ["Win the game"]))  # no manaValueNeeded
    assert r.included[0].mana_value == 0


# --- terminality ------------------------------------------------------------------------

def test_terminal_vs_advantage():
    lethal = _report(_variant(["A", "B"], ["Each opponent loses the game"])).included[0]
    dmg = _report(_variant(["A", "B"], ["Infinite combat damage"])).included[0]
    mana = _report(_variant(["A", "B"], ["Infinite colorless mana"])).included[0]
    tokens = _report(_variant(["A", "B", "C"], ["Infinite creature tokens"])).included[0]
    assert is_terminal_combo(lethal)
    assert is_terminal_combo(dmg)
    assert not is_terminal_combo(mana)  # needs an outlet
    assert not is_terminal_combo(tokens)  # needs the next combat


# --- classification ---------------------------------------------------------------------

def test_fast_win_two_card_terminal():
    combo = _report(_variant(["Thassa's Oracle", "Demonic Consultation"],
                             ["Win the game"], manaValueNeeded=2)).included[0]
    g = classify_combo(combo)
    assert g.terminal and g.reliability == "fast-win"
    assert "fast-win" in g.note


def test_strong_three_card_terminal():
    combo = _report(_variant(["A", "B", "C"], ["Infinite combat damage"],
                             manaValueNeeded=3)).included[0]
    assert classify_combo(combo).reliability == "strong"


def test_slow_when_advantage_only():
    combo = _report(_variant(["A", "B"], ["Infinite creature tokens"])).included[0]
    g = classify_combo(combo)
    assert not g.terminal and g.reliability == "slow"
    assert "needs an outlet" in g.note


def test_commander_dependent_drops_out_of_fast_win():
    combo = _report(_variant(["Aang, the Last Airbender", "B"], ["Win the game"],
                             manaValueNeeded=1)).included[0]
    g = classify_combo(combo, frozenset({"Aang, the Last Airbender"}))
    assert g.needs_commander
    assert g.reliability == "strong"  # terminal but commander-gated -> not fast-win
    assert "commander-dependent" in g.note


def test_high_mana_terminal_is_not_fast_win():
    combo = _report(_variant(["A", "B"], ["Win the game"], manaValueNeeded=6)).included[0]
    assert classify_combo(combo).reliability == "strong"


# --- deck-level assessment --------------------------------------------------------------

def test_assessment_counts_and_signals():
    r = _report(
        _variant(["Thassa's Oracle", "Demonic Consultation"], ["Win the game"],
                 manaValueNeeded=2),
        _variant(["A", "B", "C"], ["Infinite creature tokens"]),  # slow, advantage
        _variant(["X", "Y"], ["Infinite colorless mana"]),  # not winning -> excluded
    )
    a = assess_combos(r)
    assert a.total == 2  # mana-only combo is not game-ending
    assert a.terminal_count == 1
    assert a.advantage_count == 1
    assert a.fast_terminal_two_card
    reason = a.gate_reason()
    assert "fast 2-card terminal" in reason and "min Bracket 3" in reason


def test_assessment_no_fast_signal_when_only_slow():
    r = _report(_variant(["A", "B", "C"], ["Infinite creature tokens"]))
    a = assess_combos(r)
    assert a.total == 1 and not a.fast_terminal_two_card


# --- bracket gate: graded vs counts-only ------------------------------------------------

def test_graded_slow_combo_holds_floor_at_three_with_honest_reason(make_card, forest, bear):
    """A slow, commander-dependent, advantage-only combo still gates to >=3 (per the official
    rules a wincon is a wincon), but the REASON now says it's slow, not a flat count."""
    r = _report(_variant(["Aang, the Last Airbender", "B", "C"],
                         ["Infinite creature tokens"]))
    profile = assess_combos(r, frozenset({"Aang, the Last Airbender"}))
    est = estimate_bracket(
        [(forest, 60), (bear, 39)], [], ceiling=0, speed_kill_rate=0.0,
        combo_profile=profile, combos_checked=True,
    )
    assert est.bracket >= 3
    assert any("slow/needs-outlet" in x for x in est.reasons)


def test_graded_slow_combo_does_not_escalate_to_five(make_card, forest):
    """Even with high ceiling/speed, a slow combo must NOT trigger the 2-card cEDH escalation."""
    def gc(name):
        c = make_card(name, mana_cost="{2}", type_line="Artifact")
        c.game_changer = True
        return c
    cards = [(forest, 40)] + [(gc(f"GC {i}"), 1) for i in range(5)]
    slow = assess_combos(_report(_variant(["A", "B", "C"], ["Infinite creature tokens"])))
    est = estimate_bracket(
        cards, [], ceiling=60, speed_kill_rate=0.5, combo_profile=slow, combos_checked=True,
    )
    assert est.bracket == 4  # slow combo -> no fast-combo push to 5


def test_graded_fast_combo_escalates_to_five(make_card, forest):
    def gc(name):
        c = make_card(name, mana_cost="{2}", type_line="Artifact")
        c.game_changer = True
        return c
    cards = [(forest, 40)] + [(gc(f"GC {i}"), 1) for i in range(5)]
    fast = assess_combos(_report(_variant(["Thassa's Oracle", "Demonic Consultation"],
                                          ["Win the game"], manaValueNeeded=2)))
    est = estimate_bracket(
        cards, [], ceiling=60, speed_kill_rate=0.5, combo_profile=fast, combos_checked=True,
    )
    assert est.bracket == 5


def test_low_combat_reliance_is_the_cedh_signal_not_high(make_card, forest):
    """REVERSED 2026-08-27 (`docs/PLAN_CLOCK.md` Sec 1.5): a real cEDH deck's clock is the
    combo turn, not creatures connecting, so a LOW goldfish combat-kill-rate is the signal
    that beats baseline on the labelled corpus -- not a high one, which the shipped gate
    required until this landed. Ceiling was dropped from the gate entirely (measured
    noise-level at two seeds), so this pins the ONLY remaining condition alongside the
    combo check: a combo deck that ALSO reliably kills via plain combat (kill_rate above
    the threshold) reads as a goodstuff Bracket-4 pile with an incidental combo, not cEDH.
    """
    def gc(name):
        c = make_card(name, mana_cost="{2}", type_line="Artifact")
        c.game_changer = True
        return c
    cards = [(forest, 40)] + [(gc(f"GC {i}"), 1) for i in range(5)]
    fast = assess_combos(_report(_variant(["Thassa's Oracle", "Demonic Consultation"],
                                          ["Win the game"], manaValueNeeded=2)))
    low_combat = estimate_bracket(
        cards, [], ceiling=0, speed_kill_rate=0.1, combo_profile=fast, combos_checked=True,
    )
    assert low_combat.bracket == 5, "low combat reliance + a real combo IS the cEDH signal"
    high_combat = estimate_bracket(
        cards, [], ceiling=100, speed_kill_rate=0.95, combo_profile=fast, combos_checked=True,
    )
    assert high_combat.bracket == 4, (
        "a deck that reliably kills via plain combat reads as B4 goodstuff, "
        "even holding the same real combo"
    )


def test_graded_strong_two_card_combo_also_escalates_to_five(make_card, forest):
    """Widened 2026-08-26 (`docs/PLAN_CLOCK.md` Sec 1.4, measured against 252 real B3/B4/B5
    decks with a live Spellbook lookup): a 2-card TERMINAL combo escalates even when its
    mana cost is too high to earn the "fast-win" grade (here manaValueNeeded=3, so
    classify_combo grades it "strong" per its own mv<=2 cutoff, not "fast-win") — because
    requiring "fast-win" specifically left only 9 of the corpus's real B5 decks even
    eligible for this gate, while dropping just the reliability requirement (keeping
    terminal + <=2 pieces) more than triples that to 28. Contrast with the slow/3-piece
    test above, which correctly still does NOT escalate — this is testing the boundary
    the widening actually moved, not re-testing the old one.
    """
    def gc(name):
        c = make_card(name, mana_cost="{2}", type_line="Artifact")
        c.game_changer = True
        return c
    cards = [(forest, 40)] + [(gc(f"GC {i}"), 1) for i in range(5)]
    strong = assess_combos(_report(_variant(["Thassa's Oracle", "Demonic Consultation"],
                                            ["Win the game"], manaValueNeeded=3)))
    grade = strong.grades[0]
    assert grade.reliability == "strong" and grade.pieces == 2 and grade.terminal, (
        "fixture drifted off the 'strong, not fast-win' precondition this test needs")
    est = estimate_bracket(
        cards, [], ceiling=60, speed_kill_rate=0.5, combo_profile=strong, combos_checked=True,
    )
    assert est.bracket == 5


# --- the two surfaces must agree ---------------------------------------------------------

def test_pod_finisher_agrees_between_cli_and_api_combo_inputs(make_card):
    """analyze_deck's callers hand it combo evidence in two different shapes.

    The CLI counts combos itself and passes `game_ending_combos`; the API passes the whole
    `combo_report` and leaves the counts at 0. `estimate_bracket` reconciles them, but
    `compute_pod`'s `has_finisher` read the raw count only — so over HTTP it was always
    False and the app's pod score never reflected a combo finisher that the CLI did see.
    """
    from mythgauntlet.model.deck import Deck, ResolvedDeck
    from mythgauntlet.ratings.analysis import analyze_deck
    from mythgauntlet.semantics.store import SemanticsStore
    from mythgauntlet.sim.tier0 import SimConfig

    forest = make_card("Forest", type_line="Basic Land - Forest",
                       produced_mana=("G",), color_identity=("G",))
    bear = make_card("Bear", mana_cost="{1}{G}", type_line="Creature - Beast",
                     color_identity=("G",))
    bear.power, bear.toughness = "3", "3"
    cmd = make_card("Cmd", mana_cost="{2}{G}", type_line="Legendary Creature - Elf",
                    color_identity=("G",))
    cmd.power, cmd.toughness = "2", "2"
    resolved = ResolvedDeck(deck=Deck(name="t"), commanders=[cmd],
                            cards=[(forest, 40), (bear, 59)], missing=[])

    cfg = SimConfig(turns=8, runs=8, seed=7)
    store = SemanticsStore({})
    report = _report(_variant(["Bear", "Cmd"], ["Win the game"], id="combo-1"))

    cli_side = analyze_deck(resolved, cfg, store, two_card_combos=1, game_ending_combos=1,
                            combo_report=report, combos_checked=True, run_resilience=False)
    api_side = analyze_deck(resolved, cfg, store, combo_report=report,
                            combos_checked=True, run_resilience=False)

    assert api_side.pod.via_finisher == cli_side.pod.via_finisher
    assert api_side.pod.score == cli_side.pod.score
    assert api_side.bracket.bracket == cli_side.bracket.bracket
