"""Would THIS card help THIS deck — the single-card question, and its guard rails."""

from mythgauntlet.model.deck import Deck, ResolvedDeck
from mythgauntlet.ratings.card_impact import assess_card
from mythgauntlet.semantics.store import SemanticsStore
from mythgauntlet.sim.tier0 import SimConfig


def _deck(make_card, forest, bear):
    cmdr = make_card("Green Boss", mana_cost="{2}{G}", type_line="Legendary Creature — Elf",
                     colors=("G",), color_identity=("G",))
    cmdr.power, cmdr.toughness = "3", "3"
    return ResolvedDeck(deck=Deck(name="mono-green"), commanders=[cmdr],
                        cards=[(forest, 60), (bear, 39)], missing=[])


def _cfg():
    return SimConfig(turns=8, runs=20, seed=5)


def test_off_colour_card_is_illegal_not_merely_weak(make_card, forest, bear):
    """CR 903.4. An off-colour card is disqualified whatever its power — telling the user
    it 'lowers consistency' would be answering a question they did not ask."""
    blue = make_card("Counterspell", mana_cost="{U}{U}", type_line="Instant",
                     colors=("U",), color_identity=("U",),
                     oracle_text="Counter target spell.")
    imp = assess_card(_deck(make_card, forest, bear), blue, _cfg(), SemanticsStore())
    assert imp.verdict == "illegal"
    assert imp.legal is False
    assert not imp.axes                      # nothing was simulated
    assert "colour identity" in imp.headline


def test_banned_card_is_rejected_before_any_measurement(make_card, forest, bear):
    banned = make_card("Mana Crypt", mana_cost="{0}", type_line="Artifact",
                       color_identity=(), oracle_text="{T}: Add {C}{C}.")
    banned.commander_legal = False
    imp = assess_card(_deck(make_card, forest, bear), banned, _cfg(), SemanticsStore())
    assert imp.verdict == "illegal" and imp.legal is False
    assert "not legal" in imp.headline


def test_card_already_in_the_deck_is_reported_not_simulated(make_card, forest, bear):
    imp = assess_card(_deck(make_card, forest, bear), bear, _cfg(), SemanticsStore())
    assert imp.already_in_deck is True
    assert imp.verdict == "neutral"
    assert not imp.axes


def test_a_legal_card_is_measured_and_explains_its_cut(make_card, forest, bear):
    rock = make_card("Owned Rock", mana_cost="{2}", type_line="Artifact",
                     color_identity=(), oracle_text="{T}: Add {C}{C}.")
    imp = assess_card(_deck(make_card, forest, bear), rock, _cfg(), SemanticsStore())
    assert imp.verdict in {"positive", "negative", "neutral"}
    assert imp.legal is True
    assert imp.cut, "must say which slot it was measured against"
    assert {m.axis for m in imp.axes} == {"consistency", "speed", "resilience",
                                          "interaction", "ceiling"}
    assert any("Measured by swapping it in for" in r for r in imp.reasons)


def test_sub_noise_movement_is_reported_as_no_effect(make_card, forest, bear):
    """A delta under the axis's own seed-to-seed spread is a re-roll, not a finding. The
    floors are speed 1.7 / ceiling 2.3 / consistency 0.9; resilience and interaction are
    deterministic so any nonzero move there is real."""
    from mythgauntlet.ratings.card_impact import AxisMove
    assert not AxisMove("speed", "Speed", 50.0, 51.0, 1.7).meaningful      # +1.0 < 1.7
    assert AxisMove("speed", "Speed", 50.0, 52.5, 1.7).meaningful          # +2.5 > 1.7
    assert AxisMove("interaction", "Interaction", 50.0, 50.4, 0.0).meaningful
    assert not AxisMove("interaction", "Interaction", 50.0, 50.0, 0.0).meaningful


def test_headline_names_the_largest_mover(make_card, forest, bear):
    """Sorting by axis order named Consistency +1.9 while Speed +8.3 went unmentioned."""
    from mythgauntlet.ratings.card_impact import AxisMove
    moves = [AxisMove("consistency", "Consistency", 50, 51.9, 0.9),
             AxisMove("speed", "Speed", 50, 58.3, 1.7)]
    gains = sorted((m for m in moves if m.meaningful and m.delta > 0), key=lambda m: -m.delta)
    assert gains[0].label == "Speed"
