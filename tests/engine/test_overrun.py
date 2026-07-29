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
