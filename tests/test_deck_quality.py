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
    # CR 202.3f: a hybrid's mana value is its highest possible half.
    assert dq.mana_value({"mana_cost": "{2/W}{2/W}"}) == 4
    assert dq.mana_value({"mana_cost": "{W/U}"}) == 1


def test_mana_value_x_is_zero_and_phyrexian_is_one():
    assert dq.mana_value({"mana_cost": "{X}{R}{R}"}) == 2
    assert dq.mana_value({"mana_cost": "{R/P}"}) == 1


def test_pip_counts_hybrid_counts_for_both_colours():
    # Either colour can pay it, so both colours' source counts must satisfy it.
    assert dq.pip_counts({"mana_cost": "{5}{B}{R}"}) == {"B": 1, "R": 1}
    assert dq.pip_counts({"mana_cost": "{B/R}{B}"}) == {"B": 2, "R": 1}


def test_pip_counts_phyrexian_is_not_a_hard_colour_requirement():
    """{B/P} is payable with 2 life instead of a black source, so it must not feed
    assess_colors' "short on black" diagnostic like a real pip does (Dismember)."""
    assert dq.pip_counts({"mana_cost": "{1}{B/P}{B/P}"}) == {}
    # A genuine hybrid alongside a phyrexian symbol still counts the hybrid's colours.
    assert dq.pip_counts({"mana_cost": "{B/P}{W/U}"}) == {"W": 1, "U": 1}


def test_assess_colors_does_not_flag_phyrexian_mana_in_an_off_colour_deck():
    """Dismember ({1}{B/P}{B/P}) is castable for {3} generic + 4 life in a deck with NO
    black sources at all. Before the fix, its two Phyrexian symbols were credited as
    hard black pips and this deck was reported short on black."""
    commander = {"name": "Cmdr", "mana_cost": "{4}{G}", "cmc": 5,
                 "color_identity": ["G"], "type_line": "Legendary Creature"}
    deck = [{"name": "Dismember", "mana_cost": "{1}{B/P}{B/P}", "cmc": 3,
             "type_line": "Instant"},
            {"name": "Forest", "type_line": "Basic Land — Forest",
             "produced_mana": ["G"], "quantity": 36}]
    v = dq.assess_colors(deck, commander)
    assert "B" not in v.pips
    assert "B" not in v.short
    assert v.ok is True


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


def test_null_commander_identity_falls_back_to_the_decks_own_pips():
    """An imported deck can carry commander={"name": None, "color_identity": None} —
    a 60-card list, or one whose commander zone never resolved. Without a fallback the
    five-colour lands leak through and an Izzet deck reports B/G/W sources."""
    commander = {"name": None, "color_identity": None}
    deck = [{"name": "Izzet Spell", "mana_cost": "{U}{R}", "cmc": 2,
             "type_line": "Instant"},
            {"name": "Command Tower", "type_line": "Land",
             "produced_mana": ["W", "U", "B", "R", "G"]},
            {"name": "Island", "type_line": "Basic Land — Island",
             "produced_mana": ["U"], "quantity": 15},
            {"name": "Mountain", "type_line": "Basic Land — Mountain",
             "produced_mana": ["R"], "quantity": 15}]
    v = dq.assess_colors(deck, commander)
    assert set(v.sources) == {"U", "R"}, v.sources


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


# ── fetchlands are sources ───────────────────────────────────────────────────────

def _land(name, oracle, produced=None):
    return {"name": name, "type_line": "Land", "mana_cost": "", "cmc": 0,
            "oracle_text": oracle, "produced_mana": produced}


def test_a_fetchland_counts_as_a_source_for_what_it_finds():
    """A fetchland produces NO mana of its own, so counting only `produced_mana` scored
    Marsh Flats as neither a white nor a black source. In play it is plainly both. A
    measured Tymna (WB) build had 36 lands and was reported short on black while running
    eight fetches that could each find a Swamp."""
    marsh = _land("Marsh Flats",
                  "{T}, Pay 1 life, Sacrifice this land: Search your library for a "
                  "Plains or Swamp card, put it onto the battlefield, then shuffle.")
    assert dq._fetches(marsh) == {"W", "B"}
    assert dq.color_sources([marsh]) == {"W": 1, "B": 1}


def test_a_fetch_counts_only_for_the_types_it_names():
    misty = _land("Misty Rainforest",
                  "Search your library for a Forest or Island card")
    assert dq._fetches(misty) == {"G", "U"}


def test_an_any_basic_fetch_counts_for_every_colour():
    assert dq._fetches(
        _land("Evolving Wilds", "Search your library for a basic land card")
    ) == set("WUBRG")


def test_a_land_that_produces_mana_is_not_double_counted():
    """`_fetches` must not fire for a card `_produces` already covers."""
    shrine = _land("Godless Shrine", "({T}: Add {W} or {B}.)", produced=["W", "B"])
    assert dq._fetches(shrine) == set()
    assert dq.color_sources([shrine]) == {"W": 1, "B": 1}


def test_a_tutor_that_is_not_a_land_finds_no_colour():
    """"Search your library for a card" names no land type — not a mana source."""
    tutor = {"name": "Demonic Tutor", "type_line": "Sorcery", "mana_cost": "{1}{B}{B}",
             "cmc": 3, "oracle_text": "Search your library for a card, put it into your hand."}
    assert dq._fetches(tutor) == set()


# ── mana base: enough mana AT ALL, which `assess_colors` never asked ─────────────

def _spell(name="Spell", cost="{1}"):
    return {"name": name, "mana_cost": cost, "type_line": "Creature — Human"}


def _basic(name="Forest", n=1):
    return {"name": name, "type_line": "Basic Land — Forest",
            "produced_mana": ["G"], "quantity": n}


def _rock(name="Signet", cost="{2}"):
    """Nets +1: two mana in, one generic + one coloured out."""
    return {"name": name, "mana_cost": cost, "type_line": "Artifact",
            "oracle_text": "{1}, {T}: Add {G}{G}."}


def test_a_low_land_deck_carried_by_ramp_is_not_called_short():
    """The whole point of counting ramp.

    Measured over 459 corpus decks, 10.9% run under 33 lands and 68% of those clear 40
    total sources — a low land count is usually a choice ramp pays for. Calling those
    decks broken would be confidently wrong about a deliberate build.
    """
    deck = [_basic(f"Forest{i}") for i in range(27)]
    deck += [_rock(f"Rock{i}") for i in range(11)]
    v = dq.assess_mana_base(deck)
    assert (v.lands, v.ramp, v.sources) == (27, 11, 38)
    assert v.verdict == dq.MANA_RAMP_DEPENDENT
    assert v.ok is True                      # a description of play, not a fault


def test_a_normal_land_count_with_almost_no_ramp_is_NOT_short():
    """The bug this rule shipped with, caught by running it on real decks.

    35 lands is the 25th percentile of the corpus — an ordinary manabase. Testing the
    source total ALONE flagged it as short merely because the deck runs 2 ramp, but not
    ramping is a playstyle (a low-curve aristocrats list wants spells, not rocks). Both
    halves have to fail, and the land count is what decides it.
    """
    deck = [_basic(f"Forest{i}") for i in range(35)]
    deck += [_rock("Rock1"), _rock("Rock2")]
    v = dq.assess_mana_base(deck)
    assert (v.lands, v.ramp, v.sources) == (35, 2, 37)
    assert v.sources < dq.MIN_SOURCES        # the source total alone WOULD fire...
    assert v.verdict == dq.MANA_OK           # ...and must not
    assert v.notes == []


def test_the_same_land_count_with_no_ramp_IS_short():
    """The pair this measurement exists to tell apart.

    Both decks have 27 lands and `assess_colors` reports them identically; only the
    ramp count separates a deliberate build from one that cannot cast its spells.
    """
    deck = [_basic(f"Forest{i}") for i in range(27)]
    deck += [_spell(f"Spell{i}") for i in range(11)]
    v = dq.assess_mana_base(deck)
    assert (v.lands, v.ramp, v.sources) == (27, 0, 27)
    assert v.lands < dq.LOW_LANDS and v.sources < dq.MIN_SOURCES
    assert v.verdict == dq.MANA_SHORT
    assert v.ok is False
    assert v.notes and "95% of decks" in v.notes[0]


def test_an_ordinary_manabase_is_ok_and_says_nothing():
    """A normal deck must produce NO note — advice that always fires is ignored."""
    deck = [_basic(f"Forest{i}") for i in range(36)]
    deck += [_rock(f"Rock{i}") for i in range(10)]
    v = dq.assess_mana_base(deck)
    assert v.verdict == dq.MANA_OK
    assert v.ok is True and v.notes == []


def test_lands_are_quantity_weighted():
    """An imported deck aggregates its basics into ONE dict carrying quantity."""
    v = dq.assess_mana_base([_basic("Forest", n=36)])
    assert v.lands == 36


def test_a_land_is_never_counted_as_ramp():
    """`classify` legitimately tags a mana land as ramp; double-counting it would
    inflate every deck's source count by most of its manabase."""
    v = dq.assess_mana_base([_basic(f"Forest{i}") for i in range(36)])
    assert v.ramp == 0 and v.sources == 36


def test_a_zero_net_mana_filter_is_not_ramp():
    """`{1},{T}: Add {B}` nets zero. Counting it is the documented `ramp_sources`
    bug from the engine, arriving in a second place."""
    filt = {"name": "Filter", "mana_cost": "{2}", "type_line": "Artifact",
            "oracle_text": "{1}, {T}: Add {B}."}
    assert dq.ramp_count([filt]) == 0


def test_a_stale_stored_quality_block_is_recomputed_on_load():
    """`_backfill_quality` must treat an INCOMPLETE block as stale, not as done.

    It early-returned on any truthy `quality`, so a deck built after `curve`/`colors`
    landed but before `mana` kept its old block forever and the new panel silently never
    rendered for it. Only decks with NO block at all were ever backfilled.
    """
    import server

    deck = [_basic(f"Forest{i}") for i in range(36)] + [_spell(f"S{i}") for i in range(60)]
    data = {"commander": _spell("Cmdr"), "deck": deck,
            "stats": {"quality": {"curve": {}, "colors": {}}}}      # no "mana" — stale
    server._backfill_quality(data)
    assert "mana" in data["stats"]["quality"], "stale block was not recomputed"

    # A COMPLETE block is left exactly as stored — the backfill is not a recompute-always.
    sentinel = {"curve": {"x": 1}, "colors": {}, "mana": {}}
    data2 = {"commander": _spell("Cmdr"), "deck": deck, "stats": {"quality": sentinel}}
    server._backfill_quality(data2)
    assert data2["stats"]["quality"] is sentinel
