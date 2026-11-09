"""Go-wide / overrun alpha-strike estimator (sim/overrun.py) + its detection.

The load-bearing properties (docs/SIMULATION.md): a one-shot team pump on a WIDE board reads as a
lethal alpha strike; the SAME wide board with no finisher does NOT; a narrow board with a finisher
does NOT; and a STATIC anthem lord is not mistaken for a one-shot finisher.
"""

from __future__ import annotations

from mythgauntlet.semantics import tags
from mythgauntlet.sim.overrun import alpha_strike_damage, estimate_overrun


def _overrun_spell(make_card, pump="3"):
    return make_card(
        "Team Charge", mana_cost="{2}{G}{G}", type_line="Sorcery",
        oracle_text=f"Creatures you control get +{pump}/+{pump} and gain trample "
                    "until end of turn.",
    )


def _craterhoof(make_card):
    return make_card(
        "Hoof Beast", mana_cost="{5}{G}{G}{G}", type_line="Creature",
        oracle_text="When this creature enters, creatures you control gain trample and get "
                    "+X/+X until end of turn, where X is the number of creatures you control.",
    )


# --- detection ---------------------------------------------------------------------------


def test_flat_overrun_detected(make_card):
    fx = tags.analyze(_overrun_spell(make_card, "3"))
    assert fx.overrun_pump == 3
    assert fx.overrun_scales is False


def test_scaling_overrun_detected(make_card):
    fx = tags.analyze(_craterhoof(make_card))
    assert fx.overrun_scales is True


def test_static_anthem_lord_not_a_finisher(make_card):
    # a permanent anthem (no "until end of turn") is NOT a one-shot alpha-strike finisher.
    lord = make_card(
        "Token Boss", mana_cost="{2}{W}", type_line="Enchantment",
        oracle_text="Creature tokens you control get +1/+1 and have vigilance.",
    )
    fx = tags.analyze(lord)
    assert fx.overrun_pump == 0 and fx.overrun_scales is False


# --- estimator ---------------------------------------------------------------------------


def test_wide_board_plus_pump_is_lethal(make_card):
    cards = [(_overrun_spell(make_card, "3"), 1)]
    # 8 creatures, 16 base power: +3 each -> 16 + 8*3 = 40
    rep = estimate_overrun(cards, board_power=16, board_creatures=8)
    assert rep.can_alpha_strike
    assert rep.alpha_damage >= 40
    assert rep.has_finisher


def test_wide_board_without_finisher_not_lethal(make_card, bear):
    rep = estimate_overrun([(bear, 30)], board_power=16, board_creatures=8)
    assert not rep.can_alpha_strike
    assert not rep.has_finisher
    assert rep.alpha_damage == 16  # no pump -> just the base swing


def test_narrow_board_with_finisher_not_alpha(make_card):
    # a one-shot pump on 2 creatures is not an alpha strike, even if the finisher is present.
    cards = [(_overrun_spell(make_card, "3"), 1)]
    rep = estimate_overrun(cards, board_power=6, board_creatures=2)
    assert not rep.can_alpha_strike
    assert rep.has_finisher


def test_scaling_pump_squares_the_board(make_card):
    # Craterhoof: X = creatures -> each of C creatures gets +C, adding C*C on top of base power.
    assert alpha_strike_damage(0, True, board_power=10, board_creatures=7) == 10 + 7 * 7
    cards = [(_craterhoof(make_card), 1)]
    assert estimate_overrun(cards, board_power=10, board_creatures=7).can_alpha_strike


def test_deterministic(make_card):
    cards = [(_overrun_spell(make_card, "3"), 1)]
    assert estimate_overrun(cards, 16, 8) == estimate_overrun(cards, 16, 8)


# --- per-game availability: the finisher must be DRAWN and castable ----------------------
# A 6-wide board of 2-power creatures from turn 3; a +3/+3 pump makes that 6*2 + 6*3 = 30... so
# use 8 wide: 16 + 24 = 40, exactly lethal.

_POWER = [0, 0, 16, 16, 16, 16]
_WIDTH = [0, 0, 8, 8, 8, 8]


def test_alpha_strike_waits_for_the_game_to_draw_the_finisher(make_card):
    """The reported bug: every simulated game was handed the deck's one Overrun the moment
    its board was wide, so adding a single copy moved ~every game's kill turn."""
    from mythgauntlet.sim.overrun import earliest_alpha_strike_turn
    cards = [(_overrun_spell(make_card), 1)]
    # the old best-case read (no draw info) still fires as soon as the board is wide
    assert earliest_alpha_strike_turn(cards, _POWER, _WIDTH) == 3
    # drawn on turn 5 -> no alpha strike before turn 5
    assert earliest_alpha_strike_turn(cards, _POWER, _WIDTH,
                                      seen_turn={"Team Charge": 5}) == 5
    # never drawn this game -> no alpha strike at all
    assert earliest_alpha_strike_turn(cards, _POWER, _WIDTH, seen_turn={}) is None


def test_alpha_strike_needs_the_mana_to_cast_the_finisher(make_card):
    from mythgauntlet.sim.overrun import earliest_alpha_strike_turn
    cards = [(_overrun_spell(make_card), 1)]          # mana value 4
    assert earliest_alpha_strike_turn(cards, _POWER, _WIDTH, seen_turn={"Team Charge": 0},
                                      mana_by_turn=[1, 2, 3, 3, 4, 5]) == 5


def test_a_commander_finisher_never_needs_drawing(make_card):
    from mythgauntlet.sim.overrun import earliest_alpha_strike_turn
    cards = [(_overrun_spell(make_card), 1)]
    assert earliest_alpha_strike_turn(cards, _POWER, _WIDTH, seen_turn={},
                                      always_available=frozenset({"Team Charge"})) == 3
