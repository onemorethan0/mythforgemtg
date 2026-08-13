"""Tests for deck_quality's curve and colour-source measurement.

Self-contained: no data/ directory, no network. CI runs with neither.

Each case pins a regression caught in review:
  * `quantity` is load-bearing — basics aggregate into ONE dict with quantity: 14, so
    len() undercounts the manabase fourfold.
  * The curve AVERAGE must use true mana value; clamping it at 7 (the bucketing value)
    reported a deck of three 9-drops as 7.0, understating exactly the top-heavy decks
    this module exists to detect.
  * colour sources come from produced_mana or an "Add ..." clause, NEVER from bare
    colour words: a non-producer carries produced_mana: [] (falsy), and Nim Deathmantle
    ("...is a black Zombie") was being counted as a black mana source.
  * suggest_cuts must not raise TypeError comparing a None edhrec_rank against int.
"""
import deck_quality as dq


def test_mana_value_hybrid_takes_higher_half():
    # Rule 202.3b: a hybrid's mana value is its highest possible half.
    assert dq.mana_value({"mana_cost": "{2/W}{2/W}"}) == 4
    assert dq.mana_value({"mana_cost": "{W/U}"}) == 1


def test_mana_value_x_is_zero_and_phyrexian_is_one():
    assert dq.mana_value({"mana_cost": "{X}{R}{R}"}) == 2
    assert dq.mana_value({"mana_cost": "{R/P}"}) == 1


def test_pip_counts_hybrid_counts_for_both_colours():
    # Either colour can pay it, so both colours' source counts must satisfy it.
    assert dq.pip_counts({"mana_cost": "{5}{B}{R}"}) == {"B": 1, "R": 1}
    assert dq.pip_counts({"mana_cost": "{B/R}{B}"}) == {"B": 2, "R": 1}


def test_qty_defaults_to_one_and_never_returns_zero():
    assert dq.qty({}) == 1
    assert dq.qty({"quantity": 14}) == 14
    assert dq.qty({"quantity": 0}) == 1


def test_curve_buckets_seven_plus_together():
    deck = [{"name": "Big", "cmc": 9, "type_line": "Sorcery"}]
    assert dq.curve(deck) == {7: 1}


def test_average_uses_true_mana_value_not_the_bucket():
    """Three 9-drops average 9.0, not 7.0. Clamping the average understated the exact
    decks assess_curve is meant to flag as top-heavy."""
    deck = [{"name": f"Big{i}", "cmc": 9, "type_line": "Sorcery"} for i in range(3)]
    assert dq.assess_curve(deck, commander_mv=4).average == 9.0


def test_curve_target_sums_exactly():
    for nonland in (40, 63, 70):
        for cmdr_mv in (2, 4, 7, 12):
            assert sum(dq.curve_target(nonland, cmdr_mv).values()) == nonland


def test_expensive_commander_shifts_the_curve_down():
    t4, t7 = dq.curve_target(63, 4), dq.curve_target(63, 7)
    # Each point of commander MV above 4 moves one slot out of 6 into 2, one out of 7
    # into 3 — a seven-drop commander needs a CHEAPER deck under it, not a heavier one.
    assert t4[6] - t7[6] == 3
    assert t4[7] - t7[7] == 3
    assert t7[2] - t4[2] == 3
    assert t7[3] - t4[3] == 3


def test_colour_sources_are_quantity_weighted():
    mountains = {"name": "Mountain", "type_line": "Basic Land — Mountain",
                 "produced_mana": ["R"], "quantity": 14}
    assert dq.color_sources([mountains]) == {"R": 14}


def test_any_colour_land_counts_for_every_colour():
    tower = {"name": "Command Tower", "type_line": "Land",
             "oracle_text": "{T}: Add one mana of any color in your commander's "
                            "color identity."}
    assert dq.color_sources([tower]) == {c: 1 for c in "WUBRG"}


def test_colour_words_in_rules_text_are_not_mana_sources():
    """Nim Deathmantle carries produced_mana: [] (falsy) and the words 'black Zombie'.
    Counting it as a black source inflates the manabase and reports a broken one as
    fine — the worst possible failure for this module."""
    mantle = {"name": "Nim Deathmantle", "type_line": "Artifact — Equipment",
              "produced_mana": [],
              "oracle_text": "Equipped creature gets +2/+2, has intimidate, and is a "
                             "black Zombie."}
    assert dq.color_sources([mantle]) == {}


def test_assess_colors_counts_the_commander_and_ignores_off_identity_sources():
    commander = {"name": "Cmdr", "mana_cost": "{5}{B}{R}", "cmc": 7,
                 "color_identity": ["B", "R"], "type_line": "Legendary Creature"}
    deck = [{"name": "Mountain", "type_line": "Basic Land — Mountain",
             "produced_mana": ["R"], "quantity": 20},
            {"name": "Swamp", "type_line": "Basic Land — Swamp",
             "produced_mana": ["B"], "quantity": 20},
            # produced_mana lists all five, but it only makes B/R in a Rakdos deck.
            {"name": "Command Tower", "type_line": "Land",
             "produced_mana": ["W", "U", "B", "R", "G"]}]
    v = dq.assess_colors(deck, commander)
    assert set(v.sources) <= {"B", "R"}, v.sources
    assert v.pips == {"B": 1, "R": 1}       # from the commander alone
    assert v.ok is True


def test_suggest_cuts_handles_unranked_cards_without_raising():
    """A None edhrec_rank used to raise TypeError mid-sort, and defaulting it to 0 made
    the least-played card look like the best one in the deck."""
    deck = ([{"name": f"Six{i}", "cmc": 6, "type_line": "Creature", "edhrec_rank": 100}
             for i in range(20)]
            + [{"name": "Obscure", "cmc": 6, "type_line": "Creature",
                "edhrec_rank": None}]
            + [{"name": "Land", "cmc": 0, "type_line": "Basic Land — Mountain",
                "quantity": 36}])
    v = dq.assess_curve(deck, commander_mv=4)
    assert v.verdict == "top-heavy"
    cuts = dq.suggest_cuts(deck, v, limit=3)
    assert cuts and cuts[0]["name"] == "Obscure"        # unranked is most cuttable
    assert not any(dq.is_land(c) for c in cuts)


def test_suggest_cuts_is_empty_when_the_curve_is_fine():
    deck = [{"name": f"C{i}", "cmc": (i % 4) + 1, "type_line": "Creature"}
            for i in range(60)]
    v = dq.assess_curve(deck, commander_mv=3)
    assert dq.suggest_cuts(deck, v) == []


def test_empty_deck_does_not_divide_by_zero():
    v = dq.assess_curve([], commander_mv=4)
    assert v.average == 0.0
    assert dq.required_sources({}, 0) == {}
