"""Upgrade advisor: ablation-based owned-card swaps. Offline, synthetic."""

from __future__ import annotations

import pytest

from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.ratings import advisor
from mythgauntlet.ratings.analysis import analyze_deck
from mythgauntlet.semantics import tags
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier0 import SimConfig


def test_axis_relevance_and_prioritization(make_card):
    """Candidates are ranked by TARGET-AXIS relevance, not popularity — a Ceiling target
    must front the finisher/combo cards over popular staples (the bug behind 'no owned
    card improved Ceiling' after evaluating 8 popular staples). Sim-free / fast."""
    # A popular ramp staple (ceiling-irrelevant) vs an unpopular scaling-burn finisher.
    rock = make_card("Mana Rock", type_line="Artifact",
                     oracle_text="{T}: Add {C}{C}.", edhrec_rank=100)
    finisher = make_card("Big X Burn", type_line="Sorcery", edhrec_rank=50000,
                         oracle_text="Big X Burn deals X damage to target player.")
    tutor = make_card("Dark Search", type_line="Sorcery",
                      oracle_text="Search your library for a card and put it into your hand.",
                      edhrec_rank=40000)
    # relevance: finisher/tutor score for ceiling, the rock does not.
    assert advisor._axis_relevance(tags.analyze(finisher), "ceiling") > 0
    assert advisor._axis_relevance(tags.analyze(rock), "ceiling") == 0
    # prioritize puts the ceiling-relevant cards ahead of the popular rock.
    ordered = advisor._prioritize([rock, finisher, tutor], "ceiling")
    assert ordered[0].name in {"Big X Burn", "Dark Search"}
    assert ordered[-1].name == "Mana Rock"
    # interaction axis: a removal spell should lead over the same rock.
    removal = make_card("Zap", type_line="Instant",
                        oracle_text="Destroy target creature.", edhrec_rank=99999)
    assert advisor._prioritize([rock, removal], "interaction")[0].name == "Zap"


def test_commander_affinity_kaalia(make_card):
    """Candidate selection respects the commander's mechanic: a Kaalia (cheat
    Angels/Demons/Dragons) deck fronts big cheatable fatties, not cards it can't cheat."""
    kaalia = make_card(
        "Kaalia of the Vast", type_line="Legendary Creature — Human Cleric",
        oracle_text=("Whenever Kaalia of the Vast attacks, you may put an Angel, Demon, "
                     "or Dragon creature card from your hand onto the battlefield "
                     "tapped and attacking."),
    )
    w = advisor.commander_wants([kaalia])
    assert w.cheats_creatures and w.wants_big
    assert w.cheat_types == {"Angel", "Demon", "Dragon"}

    dragon = make_card("Big Dragon", type_line="Creature — Dragon", mana_cost="{6}{R}{R}")
    elf = make_card("Mana Elf", type_line="Creature — Elf", mana_cost="{G}",
                    oracle_text="{T}: Add {G}.")
    rock = make_card("Rock", type_line="Artifact", oracle_text="{T}: Add {C}{C}.")
    assert advisor._commander_affinity(dragon, w) > advisor._commander_affinity(elf, w)
    assert advisor._commander_affinity(elf, w) == 0.0   # can't be cheated -> no boost
    assert advisor._commander_affinity(rock, w) == 0.0
    # In selection, the cheatable dragon leads the non-cheatable elf even for 'speed'
    # (where the elf has some axis relevance) — commander fit + relevance combine.
    ordered = advisor._prioritize([elf, rock, dragon], "ceiling", w)
    assert ordered[0].name == "Big Dragon"


def test_explain_reason(make_card):
    """Each swap carries a short, honest rationale from the add's function + axis."""
    kaalia = make_card("Kaalia", type_line="Legendary Creature — Human",
                       oracle_text=("you may put an Angel, Demon, or Dragon creature card "
                                    "from your hand onto the battlefield"))
    w = advisor.commander_wants([kaalia])
    demon = make_card("Big Demon", type_line="Creature — Demon", mana_cost="{7}{B}{B}")
    assert "cheat into play" in advisor._explain(demon, "ceiling", w)
    removal = make_card("Zap", type_line="Instant", oracle_text="Destroy target creature.")
    assert "removal" in advisor._explain(removal, "interaction", advisor.CommanderWants())
    plain = make_card("Vanilla", type_line="Creature — Bear")
    # No signal -> honest fallback, never empty.
    assert advisor._explain(plain, "speed", advisor.CommanderWants())


def _creature(make_card, name, cost, rank, **kw):
    card = make_card(name, mana_cost=cost, type_line="Creature — Bear",
                     color_identity=("G",), edhrec_rank=rank, **kw)
    card.power, card.toughness = "2", "2"
    return card


@pytest.fixture
def deck(make_card, forest):
    cmdr = make_card("Test Commander", mana_cost="{2}{G}",
                     type_line="Legendary Creature — Elf", color_identity=("G",))
    strong = _creature(make_card, "Popular Bear", "{1}{G}", 500)
    weak = _creature(make_card, "Obscure Bear", "{1}{G}", 90000)   # highest rank -> weakest
    cards = [(forest, 36), (strong, 40), (weak, 23)]
    return ResolvedDeck(deck=Deck(name="t"), commanders=[cmdr], cards=cards, missing=[])


@pytest.fixture
def store(empty_store):
    # NOT `SemanticsStore()` — that resolves MYTHGAUNTLET_STORE and loaded 31,042 CCMs on a
    # dev machine while claiming to be empty. See `empty_store` in conftest.
    return empty_store


# --- pure helpers ------------------------------------------------------------------------


def test_weakest_cut_is_the_least_played_nonland(deck):
    cut = advisor._weakest_cut(deck)
    assert cut is not None and cut.name == "Obscure Bear"  # highest edhrec_rank


def test_swap_variant_preserves_size_and_swaps(deck, make_card):
    add = _creature(make_card, "New Toy", "{G}", 1000)
    cut = advisor._weakest_cut(deck)
    variant = advisor._swap_variant(deck, cut, add)
    assert variant.card_count == deck.card_count          # size preserved
    names = {c.name for c, _ in variant.cards}
    assert "New Toy" in names
    # one copy of the 23-count weak card removed -> still present with 22
    weak = next((n for c, n in variant.cards if c.name == "Obscure Bear"), None)
    assert weak == 22


def test_axis_score_and_weakest_axis(deck, store):
    a = analyze_deck(deck, SimConfig(runs=60, turns=5, seed=1), store)
    assert advisor.weakest_axis(a) in advisor.AXES
    assert isinstance(advisor.axis_score(a, "consistency"), float)


# --- advise() ----------------------------------------------------------------------------


def test_advise_returns_well_formed_report(deck, store, make_card):
    candidates = [
        _creature(make_card, f"Owned {i}", "{1}{G}", 3000 + i * 100) for i in range(6)
    ]
    cfg = SimConfig(runs=60, turns=5, seed=1)
    # cut_pool=1 == the MVP single-global-cut contract.
    rep = advisor.advise(deck, cfg, store, candidates, axis="consistency", top=3,
                         max_eval=5, cut_pool=1)
    assert rep.axis == "consistency"
    assert rep.cut == "Obscure Bear"
    assert rep.cut_pool == 1
    assert rep.evaluated == 5                              # min(candidates, max_eval)
    assert rep.analyses == 5                               # cut_pool=1 -> one sim per candidate
    assert len(rep.suggestions) <= 3
    deltas = [s.delta for s in rep.suggestions]
    assert deltas == sorted(deltas, reverse=True)          # best first
    assert all(s.delta > 0 for s in rep.suggestions)       # only improvements
    assert all(s.cut == "Obscure Bear" for s in rep.suggestions)


def test_suggestions_are_non_overlapping(deck, store, make_card):
    """The package never offers two swaps that share a cut or an add — you can only
    swap a slot once, so '8 replacements for one card' is not useful advice."""
    cands = [_creature(make_card, f"Owned {i}", "{1}{G}", 3000 + i * 50) for i in range(8)]
    rep = advisor.advise(deck, SimConfig(runs=60, turns=5, seed=1), store, cands,
                         axis="consistency", top=5, max_eval=8, cut_pool=2)
    cuts = [s.cut for s in rep.suggestions]
    adds = [s.add for s in rep.suggestions]
    assert len(cuts) == len(set(cuts))   # distinct cuts
    assert len(adds) == len(set(adds))   # distinct adds


def test_weakest_cuts_returns_k_weakest_in_order(deck):
    cuts = advisor._weakest_cuts(deck, 2)
    # weakest (highest edhrec rank) first
    assert [c.name for c in cuts] == ["Obscure Bear", "Popular Bear"]
    assert len(advisor._weakest_cuts(deck, 99)) == 2  # only 2 nonland cards exist


def test_advise_per_swap_cut_multiplies_analyses(deck, store, make_card):
    candidates = [
        _creature(make_card, f"Owned {i}", "{1}{G}", 3000 + i * 100) for i in range(4)
    ]
    cfg = SimConfig(runs=60, turns=5, seed=1)
    rep = advisor.advise(deck, cfg, store, candidates, axis="consistency",
                         max_eval=4, cut_pool=2)
    assert rep.cut is None                 # per-swap mode: no single global cut
    assert rep.cut_pool == 2
    assert rep.evaluated == 4               # candidates considered
    # 4 candidates x 2 cut options, plus one empty-slot run per distinct suggested cut
    assert rep.analyses == 8 + len({s.cut for s in rep.suggestions})
    # every suggested cut is drawn from the deck's cut pool
    pool_names = {c.name for c in advisor._weakest_cuts(deck, 2)}
    assert all(s.cut in pool_names for s in rep.suggestions)


def test_advise_prefers_the_cut_that_improves_the_axis_most(deck, store, make_card):
    """A bigger cut pool can only match or beat the single-cut gain for the same add,
    because per-swap selection keeps the best cut it finds.

    Targets INTERACTION deliberately. The original version asked for `consistency` with a
    {1}{G} 2/2 candidate against a {1}{G} 2/2 cut, in a deck of 36 Forests casting only
    {G}/{1}{G} — consistency is already at its ceiling there and no single swap can move it,
    so `advise` returned nothing, the assert sat behind `if single.suggestions and ...`, and
    the test passed having checked NOTHING (zero suggestions even at min_delta=-999, and
    with a mana rock or a dork substituted for the candidate).

    Interaction fixes both halves: the deck has no removal, so adding a removal spell is a
    real measurable gain, and interaction is computed deterministically (seed-to-seed sd
    0.00, unlike speed 1.73 / ceiling 2.31) so the comparison is not fighting sim noise.
    """
    removal = make_card("Owned Removal", mana_cost="{1}{G}", type_line="Instant",
                        color_identity=("G",), edhrec_rank=4000,
                        oracle_text="Destroy target creature.")
    cfg = SimConfig(runs=80, turns=5, seed=3)
    single = advisor.advise(deck, cfg, store, [removal], axis="interaction", cut_pool=1)
    multi = advisor.advise(deck, cfg, store, [removal], axis="interaction", cut_pool=2)

    # Assert the precondition, so this can never silently go vacuous again.
    assert single.suggestions, "fixture produced no swap; the invariant would go untested"
    assert multi.suggestions, "fixture produced no swap; the invariant would go untested"
    assert single.suggestions[0].after > single.baseline   # the add really does help
    assert multi.suggestions[0].after >= single.suggestions[0].after - 1e-9


def test_advise_auto_picks_an_axis(deck, store, make_card):
    candidates = [_creature(make_card, "Owned A", "{1}{G}", 4000)]
    rep = advisor.advise(deck, SimConfig(runs=60, turns=5, seed=1), store, candidates)
    assert rep.axis in advisor.AXES  # None -> weakest axis chosen


def test_advise_skips_cards_already_in_deck(deck, store, make_card):
    # a candidate already in the deck must not be evaluated
    already = next(c for c, _ in deck.cards if c.name == "Popular Bear")
    extra = _creature(make_card, "Fresh Bear", "{1}{G}", 4000)
    rep = advisor.advise(deck, SimConfig(runs=60, turns=5, seed=1), store,
                         [already, extra], axis="consistency", max_eval=12)
    assert rep.evaluated == 1  # only the not-in-deck candidate


def test_advise_rejects_unknown_axis(deck, store):
    with pytest.raises(ValueError, match="unknown axis"):
        advisor.advise(deck, SimConfig(runs=50, turns=5, seed=1), store, [], axis="bogus")


def test_advisor_never_suggests_a_card_outside_the_colour_identity(make_card, forest, bear):
    """CR 903.4. The advisor had no legality notion at all, so with a collection-shaped
    candidate pool it would tell a mono-green deck to add a blue card — a swap the user
    cannot legally make, listed next to real ones.
    """
    from mythgauntlet.model.deck import Deck, ResolvedDeck
    from mythgauntlet.ratings.advisor import advise
    from mythgauntlet.semantics.store import SemanticsStore
    from mythgauntlet.sim.tier0 import SimConfig

    cmd = make_card("Green Boss", mana_cost="{2}{G}", type_line="Legendary Creature — Elf",
                    colors=("G",), color_identity=("G",))
    cmd.power, cmd.toughness = "3", "3"
    resolved = ResolvedDeck(deck=Deck(name="mono-green"), commanders=[cmd],
                            cards=[(forest, 60), (bear, 39)], missing=[])

    legal = make_card("Green Add", mana_cost="{1}{G}", type_line="Creature — Beast",
                      colors=("G",), color_identity=("G",))
    legal.power, legal.toughness = "4", "4"
    illegal = make_card("Blue Add", mana_cost="{1}{U}", type_line="Creature — Drake",
                        colors=("U",), color_identity=("U",))
    illegal.power, illegal.toughness = "9", "9"          # strictly better, still illegal
    colorless = make_card("Rock", mana_cost="{2}", type_line="Artifact",
                          oracle_text="{T}: Add {C}.")

    report = advise(resolved, SimConfig(turns=8, runs=8, seed=3), SemanticsStore({}),
                    [legal, illegal, colorless], axis="speed", top=5, max_eval=6,
                    min_delta=-999.0)
    named = {s.add for s in report.suggestions}
    assert "Blue Add" not in named
    assert named <= {"Green Add", "Rock"}   # colourless is legal in any identity


def test_gain_floor_never_drops_below_the_axis_noise():
    """A caller may raise the advisor's gain bar; it must not be able to lower it under the
    measured run-to-run noise, because a "gain" smaller than that is re-rolling the RNG.

    Calls the REAL `_noise_floor` rather than re-implementing it — the previous version copied
    the `max(min_delta, ...)` expression into the test, so the two could drift apart silently.
    """
    from mythgauntlet.ratings.advisor import NOISE_REFERENCE_RUNS, _noise_floor

    def effective(min_delta, target, runs=NOISE_REFERENCE_RUNS):
        return max(min_delta, _noise_floor(target, runs))

    # the default cannot buy a sub-noise suggestion on a simulated axis
    assert effective(1.0, "speed") > 1.0
    assert effective(1.0, "ceiling") > 1.0
    # nor can an explicit request for zero
    assert effective(0.0, "speed") > 0.0
    # a caller wanting a stricter bar still gets it
    assert effective(99.0, "speed") == 99.0
    # a genuinely deterministic axis leaves the caller's floor alone
    assert effective(1.0, "interaction") == 1.0


def test_resilience_is_not_a_noise_free_axis():
    """`resilience` was floored at 0.0, and that was an artefact of how it was measured.

    The original sweep called `analyze_deck` WITHOUT `run_resilience`, so resilience was never
    simulated and came back constant — a clean 0.00 that looked like determinism. It is only
    ever simulated when it IS the target axis, which is exactly when the floor is consulted,
    and there its seed-to-seed spread is ~1.24 at runs=150 (~1.9 at runs=60). A floor of zero
    meant every positive resilience delta passed, so resilience advice was unfiltered noise.
    """
    from mythgauntlet.ratings.advisor import _noise_floor

    assert _noise_floor("resilience", 150) > 1.0


def test_the_noise_floor_scales_with_run_count():
    """Simulation noise falls as ~1/sqrt(runs), so a FLAT floor is correct at exactly one run
    count. The constants were measured at 150 while every caller uses 60 — about 1.6x too low,
    admitting precisely the noise the floor exists to exclude.
    """
    import math

    from mythgauntlet.ratings.advisor import NOISE_REFERENCE_RUNS, _noise_floor

    at_ref = _noise_floor("speed", NOISE_REFERENCE_RUNS)
    quarter = _noise_floor("speed", NOISE_REFERENCE_RUNS // 4)
    assert quarter == pytest.approx(at_ref * 2, rel=0.02), "quartering runs doubles the noise"
    assert _noise_floor("speed", NOISE_REFERENCE_RUNS * 4) == pytest.approx(at_ref / 2, rel=0.02)
    # a zero-noise axis stays zero at every run count
    assert _noise_floor("interaction", 10) == 0.0
    assert math.isclose(_noise_floor("speed", 0), _noise_floor("speed", 0))  # no div-by-zero

def test_advisor_never_suggests_a_banned_card(make_card, forest, bear):
    """A collection-shaped candidate pool contains whatever the user owns, including cards
    that are BANNED in Commander (Mana Crypt, Jeweled Lotus, Dockside Extortionist). The
    advisor had no legality data at all and would rank them like anything else — in fact
    higher, since they are strong. `commander_legal` comes from Scryfall's
    legalities.commander via slim schema v3.
    """
    from mythgauntlet.model.deck import Deck, ResolvedDeck
    from mythgauntlet.ratings.advisor import advise
    from mythgauntlet.semantics.store import SemanticsStore
    from mythgauntlet.sim.tier0 import SimConfig

    cmd = make_card("Green Boss", mana_cost="{2}{G}", type_line="Legendary Creature — Elf",
                    colors=("G",), color_identity=("G",))
    cmd.power, cmd.toughness = "3", "3"
    resolved = ResolvedDeck(deck=Deck(name="mono-green"), commanders=[cmd],
                            cards=[(forest, 60), (bear, 39)], missing=[])

    legal = make_card("Fine Rock", mana_cost="{2}", type_line="Artifact",
                      oracle_text="{T}: Add {C}{C}.")
    banned = make_card("Mana Crypt", mana_cost="{0}", type_line="Artifact",
                       oracle_text="{T}: Add {C}{C}.")
    banned.commander_legal = False

    report = advise(resolved, SimConfig(turns=8, runs=8, seed=3), SemanticsStore({}),
                    [legal, banned], axis="speed", top=5, max_eval=6, min_delta=-999.0)
    named = {s.add for s in report.suggestions}
    assert "Mana Crypt" not in named
    assert named <= {"Fine Rock"}


def test_slim_record_carries_commander_legality():
    """Schema v3. Only "legal" is playable: "banned" is the ban list and "not_legal" covers
    cards that were never in the format (acorn/Un-cards, Conspiracy, playtest)."""
    from mythgauntlet.data.scryfall import SLIM_SCHEMA, _card_from_slim, _slim

    assert SLIM_SCHEMA >= 3

    def legality(value):
        return _slim({"name": "X", "type_line": "Artifact", "layout": "normal",
                      "legalities": {"commander": value}})["commander_legal"]

    assert legality("legal") is True
    assert legality("banned") is False
    assert legality("not_legal") is False
    assert legality("restricted") is False
    # a record with no legalities block at all must not claim legality
    assert _slim({"name": "X", "type_line": "Artifact",
                  "layout": "normal"})["commander_legal"] is False
    # the loader round-trips it
    assert _card_from_slim({"name": "X", "commander_legal": False}).commander_legal is False
    assert _card_from_slim({"name": "X", "commander_legal": True}).commander_legal is True


def test_ties_are_not_broken_alphabetically():
    """The Ceiling axis is QUANTISED, so ties are the norm and the tiebreak is the ranking.

    `speed_component` is `(turns - fast_kill_turn) / turns * 55` over an INTEGER kill turn, so
    at the default 8 turns every improvement is a whole-turn step worth exactly 55/8 = 6.875.
    Measured over a real 7-deck pod, **21 of 24 suggestions scored an identical +6.88** and the
    other 3 an identical +6.67 — the deltas carried no ordering at all.

    Sorting those ties by NAME made the advice alphabetical: it came back led by Ancient Brass
    Dragon, Arcane Signet, Arid Mesa and Bloodstained Mire, an artefact of the alphabet
    presented as a ranking. This pins the quantum so the cause stays visible.
    """
    from mythgauntlet.sim.tier0 import SimConfig

    cfg = SimConfig(turns=8, runs=60, seed=1)
    quantum = 55.0 / cfg.turns
    assert round(quantum, 2) == 6.88, (
        "the Ceiling quantum moved — if `speed_component`'s 55.0 weight or the turn count "
        f"changed, the tie-heavy behaviour this guards changes with it (got {quantum})")


def test_advise_sorts_equal_gains_by_relevance_then_popularity():
    """The measured delta is the verdict; this only orders EQUALS.

    Reproduces the sort key `advise` uses so a regression to `(-delta, name)` is caught here
    rather than in a pod report six weeks later.
    """
    # (delta, prior, edhrec_rank, add_name)
    rows = [
        (6.88, 0.0, 5000, "Ancient Brass Dragon"),   # alphabetically first, irrelevant
        (6.88, 3.0, 900, "Zealous Conscripts"),      # relevant to the axis
        (6.88, 3.0, 40, "Craterhoof Behemoth"),      # equally relevant, far more played
    ]
    rows.sort(key=lambda r: (-r[0], -r[1], r[2], r[3]))
    assert [r[3] for r in rows] == [
        "Craterhoof Behemoth", "Zealous Conscripts", "Ancient Brass Dragon"
    ], "equal gains must order by axis relevance, then how played the card is, then name"


@pytest.mark.parametrize("land,text,identity,live", [
    ("Bloodstained Mire", "Search your library for a Swamp or Mountain card", {"G", "U"}, False),
    ("Bloodstained Mire", "Search your library for a Swamp or Mountain card", {"B", "R"}, True),
    ("Misty Rainforest", "Search your library for an Island or Forest card", {"G", "U"}, True),
    # names no basic type -> kept, because the rule must not drop what it fails to understand
    ("Command Tower", "Add one mana of any color in your commander's identity.", {"G"}, True),
    ("Evolving Wilds", "Search your library for a basic land card", {"G"}, True),
])
def test_a_fetchland_that_finds_nothing_here_is_not_a_candidate(land, text, identity, live):
    """A fetchland's colour identity is EMPTY, so the identity check admits every one of them.

    Measured on a real pod, the advisor offered **Bloodstained Mire (Swamp/Mountain) to a Simic
    deck** — a card that finds nothing there and costs a life for the privilege.
    `deck_builder._land_is_castable` already fixed this for the BUILDER and the advisor never
    got the guard: two structures that must agree, only one of which was tested.
    """
    from mythgauntlet.ratings.advisor import _land_is_live

    class _Card:
        type_line = "Land"
        produced_mana = ()

        def __init__(self, name, oracle_text):
            self.name, self.oracle_text = name, oracle_text

    assert _land_is_live(_Card(land, text), identity) is live


# --- the `clock` axis (PLAN_MENTOR_ADHOC D0) ---------------------------------------------


def _stub_analysis(avg_kill_turn, turns=12, *, consistency=70.0, kill_rate=0.9,
                   resilience=80.0, interaction=60.0, ceiling=30.0):
    from types import SimpleNamespace as NS
    return NS(
        report=NS(avg_kill_turn=avg_kill_turn, turns=turns, consistency_score=consistency,
                  goldfish_kill_rate=kill_rate),
        resilience=NS(resilience_score=resilience),
        interaction=NS(score=interaction), ceiling=NS(score=ceiling),
    )


@pytest.mark.parametrize("turn,expected", [
    (1.0, 100.0 * 11 / 12), (6.0, 50.0), (9.32, 100.0 * (12 - 9.32) / 12), (12.0, 0.0),
])
def test_clock_score_is_earliness_of_the_kill(turn, expected):
    """Monotone DEcreasing in avg_kill_turn: 100 * (horizon - avg_kill_turn) / horizon."""
    assert advisor.axis_score(_stub_analysis(turn), "clock") == pytest.approx(expected)


def test_clock_score_edges():
    assert advisor.axis_score(_stub_analysis(None), "clock") == 0.0      # never kills
    assert advisor.axis_score(_stub_analysis(15.0), "clock") == 0.0      # clamped, not negative
    assert advisor.axis_score(_stub_analysis(0.0), "clock") == 100.0
    # horizon-relative: the same turn 6 is a different fraction of an 8-turn horizon
    assert advisor.axis_score(_stub_analysis(6.0, turns=8), "clock") == pytest.approx(25.0)


def test_clock_is_not_speed():
    """The reason the axis exists: speed (kill RATE) can be ~97 while the clock is late."""
    a = _stub_analysis(9.32, kill_rate=0.967)
    assert advisor.axis_score(a, "speed") == pytest.approx(96.7)
    assert advisor.axis_score(a, "clock") < 25.0


def test_weakest_axis_never_returns_clock():
    """Decision (D0): `clock` is a lens for "faster", not a competing profile axis. On this
    scale the median deck scores ~16, so letting it compete would make it the weakest axis
    of nearly every deck. Pinned with a deck whose clock is the lowest number by far."""
    a = _stub_analysis(11.5, consistency=60.0, kill_rate=0.8, resilience=70.0,
                       interaction=65.0, ceiling=50.0)
    assert advisor.axis_score(a, "clock") < min(
        advisor.axis_score(a, ax) for ax in advisor.PROFILE_AXES)
    assert advisor.weakest_axis(a) != "clock"
    assert "clock" not in advisor.PROFILE_AXES
    assert "clock" in advisor.AXES


def test_clock_axis_has_a_measured_noise_floor():
    assert advisor._AXIS_NOISE_FLOOR["clock"] > 0.0
    # scales with the run count like every other measured floor
    assert advisor._noise_floor("clock", 60) > advisor._noise_floor("clock", 150)


def test_advise_targets_clock_and_only_reports_an_earlier_kill(deck, store, make_card):
    candidates = [_creature(make_card, f"Owned {i}", "{G}", 4000 + i) for i in range(4)]
    rep = advisor.advise(deck, SimConfig(runs=60, turns=8, seed=1), store, candidates,
                         axis="clock", max_eval=4)
    assert rep.axis == "clock" and rep.axis_label == "Clock"
    for s in rep.suggestions:
        # A reported "faster" swap must actually kill sooner by its own brief.
        assert s.after > s.before
        assert s.brief.kill_turn_after < s.brief.kill_turn_before


def test_each_suggestion_splits_into_add_value_and_cut_value(deck, store, make_card):
    """add_value - cut_value == delta: the swap separated into what the added card does and
    what the cut card was doing, against an empty slot at the same seeds."""
    removal = make_card("Owned Removal", mana_cost="{1}{G}", type_line="Instant",
                        color_identity=("G",), edhrec_rank=4000,
                        oracle_text="Destroy target creature.")
    rep = advisor.advise(deck, SimConfig(runs=80, turns=5, seed=3), store, [removal],
                         axis="interaction", cut_pool=2)
    assert rep.suggestions, "fixture produced no swap; the invariant would go untested"
    for s in rep.suggestions:
        assert abs((s.add_value - s.cut_value) - s.delta) < 1e-9
        assert s.add_value > 0           # the removal itself is what moves interaction


# --- cross-axis: a target gain must not be bought with a bigger loss elsewhere ------------


def _fake_analysis(*, consistency, interaction, resilience=60.0):
    from types import SimpleNamespace as NS
    return NS(
        report=NS(consistency_score=consistency, goldfish_kill_rate=0.5,
                  avg_kill_turn=9.0, turns=12),
        resilience=NS(resilience_score=resilience),
        interaction=NS(score=interaction),
        ceiling=NS(score=20.0),
        lens=None,
    )


def test_advise_rejects_a_swap_that_leaves_the_deck_worse_overall(
    deck, store, make_card, monkeypatch,
):
    """The reported bug: the advisor read ONLY the target axis, so it would cut another
    axis's best card (The One Ring for Kaldra Compleat) to prop up the weakest one.

    `Greedy Removal` buys +6 Interaction at -15 Consistency: the bigger target gain, and a
    worse deck. `Clean Removal` buys +3 Interaction and costs nothing. Only the clean swap may
    be reported. Before the fix, Greedy ranked FIRST on its raw target delta.
    """
    greedy = make_card("Greedy Removal", mana_cost="{1}{G}", type_line="Instant",
                       color_identity=("G",), oracle_text="Destroy target creature.")
    clean = make_card("Clean Removal", mana_cost="{1}{G}", type_line="Instant",
                      color_identity=("G",), oracle_text="Destroy target artifact.")
    base = dict(consistency=70.0, interaction=10.0)

    def fake_analyze(resolved, cfg, store, **kw):
        names = {c.name for c, _ in resolved.cards}
        if "Greedy Removal" in names:
            return _fake_analysis(consistency=55.0, interaction=16.0)
        if "Clean Removal" in names:
            return _fake_analysis(consistency=70.0, interaction=13.0)
        return _fake_analysis(**base)              # baseline, and the empty-slot split

    monkeypatch.setattr(advisor, "analyze_deck", fake_analyze)
    rep = advisor.advise(deck, SimConfig(runs=150, turns=12, seed=1), store,
                         [greedy, clean], axis="interaction", cut_pool=1)

    assert [s.add for s in rep.suggestions] == ["Clean Removal"]
    s = rep.suggestions[0]
    assert s.net > 0 and s.costs == {}
    assert s.axis_deltas["interaction"] == pytest.approx(3.0)


def test_advise_checks_resilience_on_the_picks_it_did_not_sweep(
    deck, store, make_card, monkeypatch,
):
    """The sweep skips the (expensive) resilience pass unless resilience is the target, so a
    swap could still be buying the target with it. The final picks are re-run with it, and a
    pick whose resilience loss outweighs its gain is dropped."""
    card = make_card("Fragile Removal", mana_cost="{1}{G}", type_line="Instant",
                     color_identity=("G",), oracle_text="Destroy target creature.")

    def fake_analyze(resolved, cfg, store, run_resilience=False, **kw):
        swapped = any(c.name == "Fragile Removal" for c, _ in resolved.cards)
        a = (_fake_analysis(consistency=70.0, interaction=13.0, resilience=40.0) if swapped
             else _fake_analysis(consistency=70.0, interaction=10.0, resilience=60.0))
        if not run_resilience:
            a.resilience = None
        return a

    monkeypatch.setattr(advisor, "analyze_deck", fake_analyze)
    rep = advisor.advise(deck, SimConfig(runs=150, turns=12, seed=1), store, [card],
                         axis="interaction", cut_pool=1)
    assert rep.suggestions == []


def test_auto_advise_falls_back_to_the_next_weak_axis(deck, store, make_card, monkeypatch):
    """2026-11-09, the owner's Y'shtola deck: its weakest axis (ceiling) is fixed by the
    commander's plan, so an auto search found nothing although another weak axis had real
    swaps. With fallback_axes the same re-simulations are read on the next-weakest axes too,
    and each swap names the axis it improves; with the default 0 the search is unchanged."""
    card = make_card("Steady Removal", mana_cost="{1}{G}", type_line="Instant",
                     color_identity=("G",), oracle_text="Destroy target creature.")

    def fake_analyze(resolved, cfg, store, **kw):
        swapped = any(c.name == "Steady Removal" for c, _ in resolved.cards)
        # ceiling (20) is the weakest axis and never moves; interaction (30) gains +6
        return _fake_analysis(consistency=70.0, interaction=36.0 if swapped else 30.0)

    monkeypatch.setattr(advisor, "analyze_deck", fake_analyze)
    cfg = SimConfig(runs=150, turns=12, seed=1)
    plain = advisor.advise(deck, cfg, store, [card], cut_pool=1)
    assert plain.axis == "ceiling" and plain.suggestions == []
    assert plain.searched_axes == ["ceiling"]

    wide = advisor.advise(deck, cfg, store, [card], cut_pool=1, fallback_axes=3)
    assert wide.axis == "ceiling"                     # the report still names the weakest
    assert wide.searched_axes[0] == "ceiling" and "interaction" in wide.searched_axes
    (s,) = wide.suggestions
    assert (s.add, s.axis, s.axis_label) == ("Steady Removal", "interaction", "Interaction")
    assert (s.before, s.after) == (30.0, 36.0)        # on ITS axis, not ceiling
    # an explicit axis never falls back
    assert advisor.advise(deck, cfg, store, [card], axis="ceiling", cut_pool=1,
                          fallback_axes=3).suggestions == []


def test_a_gain_that_only_the_search_seed_saw_is_dropped_and_a_real_one_is_re_measured(
    deck, store, make_card, monkeypatch,
):
    """The winner's curse (measured 2026-11-11, scripts/advise_holdout.py): the search keeps the
    best of many noisy pairings, so its gain overstates. `confirm_seeds` re-measures each pick on
    fresh seeds: "Lucky" gains +8 only on the search seed (1) and is dropped; "Real" gains +6 on
    every seed and is reported at its re-measured value, with no search-seed kill-turn claim."""
    lucky = make_card("Lucky Card", mana_cost="{1}{G}", type_line="Instant", color_identity=("G",))
    real = make_card("Real Card", mana_cost="{1}{G}", type_line="Instant", color_identity=("G",))
    calls = []

    def fake_analyze(resolved, cfg, store, **kw):
        names = {c.name for c, _ in resolved.cards}
        calls.append(cfg.seed)
        if "Real Card" in names:
            return _fake_analysis(consistency=76.0, interaction=10.0)
        if "Lucky Card" in names:
            return _fake_analysis(consistency=78.0 if cfg.seed == 1 else 70.0, interaction=10.0)
        return _fake_analysis(consistency=70.0, interaction=10.0)

    monkeypatch.setattr(advisor, "analyze_deck", fake_analyze)
    cfg = SimConfig(runs=150, turns=12, seed=1)
    off = advisor.advise(deck, cfg, store, [lucky, real], axis="consistency", cut_pool=1)
    # the old behaviour: one cut slot, and the lucky +8 takes it from the real +6
    assert [s.add for s in off.suggestions] == ["Lucky Card"]

    rep = advisor.advise(deck, cfg, store, [lucky, real], axis="consistency", cut_pool=1,
                         confirm_seeds=3)
    assert [s.add for s in rep.suggestions] == ["Real Card"]
    s = rep.suggestions[0]
    assert s.confirmation["seeds"] == advisor.CONFIRM_FINAL_SEEDS and s.confirmation["mean"] == pytest.approx(6.0)
    assert s.delta == pytest.approx(6.0)
    assert any(seed != 1 for seed in calls)                  # fresh seeds really were used
    assert s.brief.kill_turn_before is None                  # search-seed kill turns not cited


def test_a_swap_that_passes_the_three_seed_screen_by_chance_fails_the_eight_seed_check(
    deck, store, make_card, monkeypatch,
):
    """Measured live (Syr Konrad, Infiltration Lens): +2.4 on three confirmation seeds, -0.1 on
    five more. "Chancy" gains +6 on the first three fresh seeds and -2 on the rest, so the cheap
    screen passes it and only the longer re-measure can tell."""
    chancy = make_card("Chancy Card", mana_cost="{1}{G}", type_line="Instant",
                       color_identity=("G",))
    cfg = SimConfig(runs=150, turns=12, seed=1)
    first_three = {cfg.seed + advisor.CONFIRM_SEED_STEP * (i + 1) for i in range(3)}

    def fake_analyze(resolved, cfg2, store, **kw):
        if "Chancy Card" not in {c.name for c, _ in resolved.cards}:
            return _fake_analysis(consistency=70.0, interaction=10.0)
        if cfg2.seed == cfg.seed:                       # the search seed: it looks great
            return _fake_analysis(consistency=78.0, interaction=10.0)
        gain = 6.0 if cfg2.seed in first_three else -2.0
        return _fake_analysis(consistency=70.0 + gain, interaction=10.0)

    monkeypatch.setattr(advisor, "analyze_deck", fake_analyze)
    rep = advisor.advise(deck, cfg, store, [chancy], axis="consistency", cut_pool=1,
                         confirm_seeds=3)
    assert rep.suggestions == []


def test_an_interaction_swap_says_it_is_a_count_not_a_win_rate(deck, store, make_card, monkeypatch):
    """Interaction is closed-form, so it repeats on any seed and proves nothing about winning; a
    pod test (scripts/swap_podcheck.py) found no win-rate change from such swaps. The suggestion
    must say what it is, in the engine's reason and in what the mentor is handed."""
    from mythgauntlet.mentor.tools import _swap_result
    removal = make_card("Clean Removal", mana_cost="{1}{G}", type_line="Instant",
                        color_identity=("G",), oracle_text="Destroy target artifact.")

    def fake_analyze(resolved, cfg, store, **kw):
        has = "Clean Removal" in {c.name for c, _ in resolved.cards}
        return _fake_analysis(consistency=70.0, interaction=13.0 if has else 10.0)

    monkeypatch.setattr(advisor, "analyze_deck", fake_analyze)
    rep = advisor.advise(deck, SimConfig(runs=150, turns=12, seed=1), store, [removal],
                         axis="interaction", cut_pool=1, confirm_seeds=3)
    s = rep.suggestions[0]
    assert advisor.INTERACTION_NOTE in s.reason
    assert s.confirmation == {"closed_form": True, "note": advisor.INTERACTION_NOTE}
    data = {"axis": "interaction", "axis_label": "Interaction", "baseline": 10.0,
            "evaluated": 1, "suggestions": [{"add": s.add, "cut": s.cut, "axis": "interaction",
                                            "brief": None}]}
    out = _swap_result(data).data["suggestions"][0]
    assert "do NOT claim the deck will win more" in out["measurement_note"]


def test_the_baseline_is_averaged_over_extra_seeds(deck, store, make_card, monkeypatch):
    """Every candidate is compared with the baseline, so one seed's luck biases them all the same
    way (Mycotyrant, 2026-11-11: seed-42 consistency 4.6 below its average over other seeds).
    With `baseline_seeds` the baseline the swaps are measured against is the average."""
    seen = []

    def fake_analyze(resolved, cfg, store, **kw):
        seen.append(cfg.seed)
        return _fake_analysis(consistency=60.0 if cfg.seed == 1 else 70.0, interaction=66.0)

    monkeypatch.setattr(advisor, "analyze_deck", fake_analyze)
    cfg = SimConfig(runs=150, turns=12, seed=1)
    one = advisor.advise(deck, cfg, store, [], axis="consistency", cut_pool=1)
    assert one.baseline == pytest.approx(60.0)
    seen.clear()
    avg = advisor.advise(deck, cfg, store, [], axis="consistency", cut_pool=1, baseline_seeds=3)
    assert avg.baseline == pytest.approx(67.5)               # (60 + 3 x 70) / 4
    assert len({s for s in seen if s != 1}) == 3             # three other seeds were simulated
