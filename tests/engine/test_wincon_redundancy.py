"""sim/wincon_redundancy — PLAN_CLOCK.md Phase 2 / docs/SPEC_wincon_redundancy.md.

Offline, synthetic, deterministic (invariant #5): every scenario re-derives the exact
behaviour worked out by hand in the spec's gold set, using the same proven fixture shapes
as test_storm.py / test_overrun.py so estimate_go_off / estimate_overrun actually fire.
"""

from __future__ import annotations

from mythgauntlet.sim.wincon_redundancy import analyze_wincon_redundancy

_MANA = [1, 2, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21]
_TURNS = 12


def _granter(make_card, name="Granter"):
    return make_card(
        name, mana_cost="{2}{U}{R}", type_line="Legendary Creature",
        oracle_text="Instant and sorcery spells you cast have storm.",
    )


def _cantrips(make_card, n=14):
    return [(make_card(
        f"Cantrip {i}", mana_cost="{U}", type_line="Instant", oracle_text="Draw a card.",
    ), 1) for i in range(n)]


def _cast_burn_imp(make_card, name, dmg=2):
    return make_card(
        name, type_line="Creature",
        oracle_text=f"Whenever you cast an instant or sorcery spell, it deals {dmg} "
                    "damage to any target.",
    )


def _big_burn(make_card):
    return make_card(
        "Big Burn", mana_cost="{X}{R}", type_line="Sorcery",
        oracle_text="Big Burn deals X damage to any target.",
    )


def test_not_applicable_for_a_vanilla_deck(make_card):
    bear = make_card("Grizzly Bears", mana_cost="{1}{G}", type_line="Creature")
    report = analyze_wincon_redundancy([(bear, 40)], [1, 2, 3], 0, 0, 8)
    assert report.applicable is False
    assert report.roles == ()


def test_two_granters_both_needed_or_combination(make_card):
    """grants_storm is an OR across the deck -- one remaining granter keeps the plan at
    full power, so removing fewer than ALL of them must never disable it."""
    deck = [
        (_granter(make_card, "Granter A"), 1),
        (_granter(make_card, "Granter B"), 1),
        (_cast_burn_imp(make_card, "Imp"), 1),
        *_cantrips(make_card),
        (_big_burn(make_card), 1),
    ]
    report = analyze_wincon_redundancy(deck, _MANA, 0, 0, _TURNS)
    granter_role = next(r for r in report.roles if r.role == "storm_granter")
    assert granter_role.contributing_cards == ("Granter A", "Granter B")
    assert granter_role.pieces_to_disable == 2


def test_a_role_can_report_none_when_a_different_role_is_independently_sufficient(make_card):
    """cast_damage is NOT amplified by storm copies (unlike magecraft), so a lone cast-
    damage payoff can be genuinely optional when the storm-amplified scaling-burn finisher
    already clears lethal on its own -- verified live: granter(s) + 14 cantrips + Big Burn
    with NO payoff at all still goes off (peak_damage=52). Removing the payoff here must
    not report a false '1 piece stops the kill' when it doesn't."""
    deck = [
        (_granter(make_card, "Granter A"), 1),
        (_granter(make_card, "Granter B"), 1),
        (_cast_burn_imp(make_card, "Imp"), 1),
        *_cantrips(make_card),
        (_big_burn(make_card), 1),
    ]
    report = analyze_wincon_redundancy(deck, _MANA, 0, 0, _TURNS)
    payoff_role = next(r for r in report.roles if r.role == "burn_payoff")
    assert payoff_role.pieces_to_disable is None
    finisher_role = next(r for r in report.roles if r.role == "scaling_burn_finisher")
    assert finisher_role.pieces_to_disable is not None


def test_burn_payoff_sorted_biggest_first_and_capped(make_card):
    """cast_damage SUMS then caps -- a plain-damage engine with two payoffs and no granter
    should still register a real (not None) count once combined damage clears lethal."""
    deck = [
        (_granter(make_card), 1),
        (_cast_burn_imp(make_card, "Imp Big", dmg=3), 1),
        (_cast_burn_imp(make_card, "Imp Small", dmg=2), 1),
        *_cantrips(make_card),
    ]
    report = analyze_wincon_redundancy(deck, _MANA, 0, 0, _TURNS)
    payoff_role = next(r for r in report.roles if r.role == "burn_payoff")
    # biggest-first order
    assert payoff_role.contributing_cards[0] == "Imp Big"
    assert payoff_role.pieces_to_disable is not None


def test_overrun_two_finishers_both_needed_when_board_supports_either(make_card):
    craterhoof = make_card(
        "Hoof Beast", mana_cost="{5}{G}{G}{G}", type_line="Creature",
        oracle_text="When this creature enters, creatures you control gain trample and "
                    "get +X/+X until end of turn, where X is the number of creatures "
                    "you control.",
    )
    team_charge = make_card(
        "Team Charge", mana_cost="{2}{G}{G}", type_line="Sorcery",
        oracle_text="Creatures you control get +3/+3 and gain trample until end of turn.",
    )
    # 10 power / 10 creatures: Team Charge alone reaches exactly 40 (10 + 10*3) -- lethal
    # even with Craterhoof gone, so both must be removed.
    deck = [(craterhoof, 1), (team_charge, 1)]
    report = analyze_wincon_redundancy(deck, [], 10, 10, _TURNS)
    finisher_role = next(r for r in report.roles if r.role == "overrun_finisher")
    # scaling (Craterhoof) sorts before flat (Team Charge)
    assert finisher_role.contributing_cards == ("Hoof Beast", "Team Charge")
    assert finisher_role.pieces_to_disable == 2


def test_overrun_not_reported_when_board_is_too_narrow(make_card):
    craterhoof = make_card(
        "Hoof Beast", mana_cost="{5}{G}{G}{G}", type_line="Creature",
        oracle_text="When this creature enters, creatures you control gain trample and "
                    "get +X/+X until end of turn, where X is the number of creatures "
                    "you control.",
    )
    deck = [(craterhoof, 1)]
    report = analyze_wincon_redundancy(deck, [], 5, 2, _TURNS)  # below _MIN_WIDTH
    assert not any(r.role == "overrun_finisher" for r in report.roles)


def test_commander_flag_set_when_commander_is_the_only_granter(make_card):
    deck = [
        (_granter(make_card, "Kalamax the Stormsire"), 1),
        (_cast_burn_imp(make_card, "Imp"), 1),
        *_cantrips(make_card),
        (_big_burn(make_card), 1),
    ]
    report = analyze_wincon_redundancy(
        deck, _MANA, 0, 0, _TURNS, commander_names=frozenset({"Kalamax the Stormsire"}),
    )
    granter_role = next(r for r in report.roles if r.role == "storm_granter")
    assert granter_role.involves_commander is True
    payoff_role = next(r for r in report.roles if r.role == "burn_payoff")
    assert payoff_role.involves_commander is False


def test_a_role_absent_from_the_deck_is_never_reported(make_card):
    deck = [
        (_granter(make_card), 1),
        (_cast_burn_imp(make_card, "Imp"), 1),
        *_cantrips(make_card),
        (_big_burn(make_card), 1),
    ]
    report = analyze_wincon_redundancy(deck, _MANA, 0, 0, _TURNS)
    # no overrun cards in this deck at all -- that role must never appear
    assert not any(r.role == "overrun_finisher" for r in report.roles)
    # big_burn IS a real scaling-burn finisher here, so that role correctly DOES appear
    assert any(r.role == "scaling_burn_finisher" for r in report.roles)


def test_deterministic(make_card):
    deck = [
        (_granter(make_card), 1),
        (_cast_burn_imp(make_card, "Imp"), 1),
        *_cantrips(make_card),
        (_big_burn(make_card), 1),
    ]
    a = analyze_wincon_redundancy(deck, _MANA, 0, 0, _TURNS)
    b = analyze_wincon_redundancy(deck, _MANA, 0, 0, _TURNS)
    assert a == b
