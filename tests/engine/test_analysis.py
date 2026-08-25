"""The shared analyze pipeline (used by both the CLI and the API)."""

from mythgauntlet.model.deck import Deck, resolve
from mythgauntlet.ratings.analysis import analyze_deck
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier0 import SimConfig


def _resolved(make_card, forest, bear):
    from mythgauntlet.data.scryfall import CardDb

    cmdr = make_card(
        "Test Commander", mana_cost="{2}{G}", type_line="Legendary Creature — Beast",
        color_identity=("G",),
    )
    cmdr.power, cmdr.toughness = "4", "4"
    db = CardDb([forest, bear, cmdr])
    deck = Deck.parse_text("Commander:\n1 Test Commander\n\nDeck:\n38 Forest\n20 Grizzly Bears\n")
    return resolve(deck, db)


def test_analyze_deck_is_deterministic(make_card, forest, bear, tmp_path):
    resolved = _resolved(make_card, forest, bear)
    store = SemanticsStore(authored=tmp_path / "a", compiled=tmp_path / "c")
    cfg = SimConfig(runs=200, seed=42, turns=8)
    a1 = analyze_deck(resolved, cfg, store)
    a2 = analyze_deck(resolved, cfg, store)
    assert a1.report.consistency_score == a2.report.consistency_score
    assert a1.bracket.bracket == a2.bracket.bracket
    assert a1.interaction.score == a2.interaction.score
    assert a1.ceiling.score == a2.ceiling.score


def test_analyze_deck_covers_all_axes(make_card, forest, bear, tmp_path):
    resolved = _resolved(make_card, forest, bear)
    store = SemanticsStore(authored=tmp_path / "a", compiled=tmp_path / "c")
    a = analyze_deck(resolved, SimConfig(runs=100, seed=1, turns=8), store)
    assert 0 <= a.report.consistency_score <= 100
    assert 0 <= a.interaction.score <= 100
    assert 0 <= a.ceiling.score <= 100
    assert a.resilience is not None and a.wipe_turn is not None
    assert 1 <= a.bracket.bracket <= 5


def test_analyze_deck_can_skip_resilience(make_card, forest, bear, tmp_path):
    resolved = _resolved(make_card, forest, bear)
    store = SemanticsStore(authored=tmp_path / "a", compiled=tmp_path / "c")
    a = analyze_deck(
        resolved, SimConfig(runs=50, seed=1, turns=8), store, run_resilience=False
    )
    assert a.resilience is None and a.wipe_turn is None


def _partner_resolved(make_card, forest):
    """A 2-commander (partner) deck: Tymna-shaped lead + a partner carrying its OWN removal
    text and a distinct color identity, so the test can tell whether the second commander is
    actually reaching the simulation-based axes rather than being silently dropped."""
    from mythgauntlet.data.scryfall import CardDb

    lead = make_card(
        "Test Lead", mana_cost="{1}{W}{B}", type_line="Legendary Creature — Human Cleric",
        color_identity=("W", "B"), oracle_text="Partner",
    )
    lead.power, lead.toughness = "2", "2"
    partner = make_card(
        "Test Partner", mana_cost="{G}{U}", type_line="Legendary Creature — Merfolk Wizard",
        color_identity=("G", "U"), oracle_text="Partner\nDestroy target creature.",
    )
    partner.power, partner.toughness = "1", "1"
    island = make_card(
        "Island", type_line="Basic Land — Island", produced_mana=("U",), color_identity=("U",)
    )
    db = CardDb([forest, island, lead, partner])
    deck = Deck.parse_text(
        "Commander:\n1 Test Lead\n1 Test Partner\n\nDeck:\n30 Forest\n30 Island\n"
    )
    return resolve(deck, db)


def test_analyze_deck_reflects_both_partner_commanders(make_card, forest, tmp_path):
    """The second (partner) commander must not be invisible to the simulation-based axes:
    its own removal text should be counted by Interaction, and the narrative should name
    both commanders -- not just `commanders[0]`."""
    resolved = _partner_resolved(make_card, forest)
    assert len(resolved.commanders) == 2
    store = SemanticsStore(authored=tmp_path / "a", compiled=tmp_path / "c")
    a = analyze_deck(resolved, SimConfig(runs=100, seed=5, turns=8), store)
    # The partner's "Destroy target creature." is now folded into the sim card pool that
    # feeds compute_interaction, so it is counted as spot removal.
    assert a.interaction.spot_removal >= 1
    # The insight narrative names BOTH commanders, not just the lead.
    assert a.insight is not None
    assert "Test Lead" in a.insight.gameplan
    assert "Test Partner" in a.insight.gameplan


def test_combo_gate_flows_through(make_card, forest, bear, tmp_path):
    """two_card_combos + combos_checked reach the bracket estimate (the CLI's --combos path)."""
    resolved = _resolved(make_card, forest, bear)
    store = SemanticsStore(authored=tmp_path / "a", compiled=tmp_path / "c")
    cfg = SimConfig(runs=80, seed=3, turns=8)
    no_combo = analyze_deck(resolved, cfg, store, combos_checked=True)
    with_combo = analyze_deck(resolved, cfg, store, two_card_combos=1, combos_checked=True)
    # 0 Game Changers + a 2-card combo -> floor raised to Bracket 3 (bracket.py gate)
    assert with_combo.bracket.bracket >= 3
    assert with_combo.bracket.bracket >= no_combo.bracket.bracket
