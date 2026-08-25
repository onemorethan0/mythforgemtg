from mythgauntlet.model.card import ManaCost


def test_simple_cost():
    cost = ManaCost.parse("{2}{G}{G}")
    assert cost.generic == 2
    assert len(cost.pips) == 2
    assert all(pip == frozenset({"G"}) for pip in cost.pips)
    assert cost.mana_value == 4


def test_empty_and_none():
    assert ManaCost.parse("").mana_value == 0
    assert ManaCost.parse(None).mana_value == 0


def test_x_counts_zero_toward_mana_value():
    cost = ManaCost.parse("{X}{R}")
    assert cost.x_count == 1
    assert cost.mana_value == 1
    assert cost.pips == (frozenset({"R"}),)


def test_hybrid_pip_accepts_either_color():
    cost = ManaCost.parse("{G/U}")
    assert cost.pips == (frozenset({"G", "U"}),)
    assert cost.mana_value == 1


def test_monocolor_hybrid_treated_as_color():
    cost = ManaCost.parse("{2/W}")
    assert cost.pips == (frozenset({"W"}),)


def test_monocolor_hybrid_mana_value_is_the_larger_half():
    # CR 202.3f: "use the largest component of each hybrid symbol." Verified against
    # the live Comprehensive Rules corpus 2026-08-24 -- {2/B}{2/B}{2/B} is 6 in the
    # rules' own worked example. `pips` still records only the color half (payment
    # stays a documented simplification, see the ManaCost docstring); mana_value must
    # not inherit that undercount.
    assert ManaCost.parse("{2/W}").mana_value == 2
    assert ManaCost.parse("{2/B}{2/B}{2/B}").mana_value == 6
    assert ManaCost.parse("{1}{W/U}{W/U}").mana_value == 3


def test_phyrexian_treated_as_color():
    cost = ManaCost.parse("{G/P}")
    assert cost.pips == (frozenset({"G"}),)


def test_colorless_pip_is_distinct_from_generic():
    cost = ManaCost.parse("{C}{1}")
    assert cost.generic == 1
    assert cost.pips == (frozenset({"C"}),)


def test_snow_treated_as_generic():
    cost = ManaCost.parse("{S}{S}")
    assert cost.generic == 2
    assert cost.pips == ()
