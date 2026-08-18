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
    assert rep.analyses == 8               # 4 candidates x 2 cut options
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
    """`min_delta=1.0` was documented as filtering sim noise but had never been checked
    against it. Measured seed-to-seed spread (same deck, 8 seeds, runs=150): speed 1.73,
    ceiling 2.31, consistency 0.94, resilience/interaction 0.00. So on the two axes that
    carry it the old default sat BELOW the noise — the advisor reported swaps whose gain is
    smaller than re-rolling the RNG on an unchanged deck.

    A caller may raise the bar; it must not be able to lower it under the noise.
    """
    from mythgauntlet.ratings.advisor import _AXIS_NOISE_FLOOR

    def effective(min_delta, target):
        return max(min_delta, _AXIS_NOISE_FLOOR.get(target, 0.0))

    # the default cannot buy a sub-noise suggestion on a simulated axis
    assert effective(1.0, "speed") == _AXIS_NOISE_FLOOR["speed"] > 1.0
    assert effective(1.0, "ceiling") == _AXIS_NOISE_FLOOR["ceiling"] > 1.0
    # nor can an explicit request for zero
    assert effective(0.0, "speed") > 0.0
    # a caller wanting a stricter bar still gets it
    assert effective(9.0, "speed") == 9.0
    # deterministic axes have no sim variance, so the caller's floor stands
    assert effective(1.0, "resilience") == 1.0
    assert effective(1.0, "interaction") == 1.0
    # the floors are the measured values, not invented ones
    assert _AXIS_NOISE_FLOOR["speed"] == 1.7
    assert _AXIS_NOISE_FLOOR["ceiling"] == 2.3


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
