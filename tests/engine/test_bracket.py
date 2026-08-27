"""Bracket estimate: the official gate logic (offline, synthetic decks)."""

from mythgauntlet.ratings.bracket import estimate_bracket


def _gc(make_card, name):
    c = make_card(name, mana_cost="{2}", type_line="Artifact")
    c.game_changer = True
    return c


def test_no_game_changers_is_bracket_1_or_2(make_card, forest, bear):
    est = estimate_bracket([(forest, 40), (bear, 59)], [], speed_kill_rate=0.2)
    assert est.bracket == 2
    assert est.game_changers == 0
    # B1 vs B2 is decided by MANA-BASE consistency, not ceiling/speed (measured 2026-07-28:
    # ceiling/speed gave 5.9% B1 recall, i.e. effectively "always B2"). A deck whose colours
    # are well supported stays at Core even with nothing else measured...
    est_ok = estimate_bracket([(forest, 60), (bear, 39)], [], speed_kill_rate=0.0,
                              manabase_consistency=0.95)
    assert est_ok.bracket == 2
    # ...and a thin mana base is what drops it to Exhibition.
    est_low = estimate_bracket([(forest, 60), (bear, 39)], [], speed_kill_rate=0.0,
                               manabase_consistency=0.50)
    assert est_low.bracket == 1


def test_up_to_three_game_changers_is_bracket_3(make_card, forest):
    cards = [(forest, 40), (_gc(make_card, "GC One"), 1), (_gc(make_card, "GC Two"), 1)]
    est = estimate_bracket(cards, [], speed_kill_rate=0.3)
    assert est.bracket == 3
    assert est.game_changers == 2
    assert any("Bracket 3" in r for r in est.reasons)


def test_many_game_changers_is_bracket_4_plus(make_card, forest):
    cards = [(forest, 40)] + [(_gc(make_card, f"GC {i}"), 1) for i in range(6)]
    est = estimate_bracket(cards, [], speed_kill_rate=0.2)
    assert est.bracket == 4  # optimized; not clearly cEDH without meta/fast-combo
    assert est.game_changers == 6


def test_fast_combo_pushes_to_five(make_card, forest):
    cards = [(forest, 40)] + [(_gc(make_card, f"GC {i}"), 1) for i in range(5)]
    est = estimate_bracket(
        cards, [], speed_kill_rate=0.5, two_card_combos=1, combos_checked=True
    )
    assert est.bracket == 5
    assert est.has_verified_combo is True


def test_meta_rating_distinguishes_5(make_card, forest):
    cards = [(forest, 40)] + [(_gc(make_card, f"GC {i}"), 1) for i in range(5)]
    est = estimate_bracket(cards, [], speed_kill_rate=0.1, meta_rating=1700)
    assert est.bracket == 5


def test_two_card_combo_raises_floor_to_three(make_card, forest, bear):
    est = estimate_bracket(
        [(forest, 40), (bear, 59)], [], speed_kill_rate=0.3,
        two_card_combos=1, combos_checked=True,
    )
    assert est.bracket >= 3  # combos not allowed in Brackets 1-2


def test_multi_card_combo_also_raises_floor_to_three(make_card, forest, bear):
    """A 3-card game-ending combo (e.g. Aang's infinite tokens) counts even with 0 two-card:
    a slow, low-ceiling deck that can still just WIN is not Bracket 1."""
    est = estimate_bracket(
        [(forest, 60), (bear, 39)], [], speed_kill_rate=0.0,  # would be B1 alone
        two_card_combos=0, combo_count=2, combos_checked=True,
    )
    assert est.bracket >= 3
    assert any("game-ending combo" in r for r in est.reasons)
    assert est.has_verified_combo is True


def test_has_verified_combo_true_even_when_game_changers_already_raised_the_floor(
    make_card, forest,
):
    """The bug this pins: `reasons` only gets a combo entry when the gate actually
    CHANGES the floor (`if floor < 3:`, i.e. gc == 0) -- a deck that already has Game
    Changers gets no combo reason even while holding a real verified combo, so grepping
    `reasons` for combo text (the only way to observe this before `has_verified_combo`
    existed) silently read False for the entire gc>=1 population.
    """
    cards = [(forest, 40)] + [(_gc(make_card, f"GC {i}"), 1) for i in range(6)]  # gc=6 > 3
    est = estimate_bracket(cards, [], speed_kill_rate=0.2,
                           two_card_combos=1, combos_checked=True)
    assert est.game_changers == 6
    assert not any("in-deck game-ending combo" in r for r in est.reasons), (
        "the reasons list genuinely carries no combo text here -- that's the exact gap "
        "has_verified_combo exists to close, not a mistake in this test"
    )
    assert est.has_verified_combo is True


def test_has_verified_combo_false_when_declared_but_not_verified(make_card, forest, bear):
    """A DECLARED combo count without `combos_checked=True` is not a verified combo --
    `has_verified_combo` must not report one just because the floor still moved on the
    unchecked count."""
    est = estimate_bracket([(forest, 40), (bear, 59)], [], speed_kill_rate=0.1,
                           two_card_combos=1, combos_checked=False)
    assert est.bracket >= 3  # the gate still fires on the declared count
    assert est.has_verified_combo is False


def test_has_verified_combo_false_for_the_go_off_heuristic_alone(make_card, forest, bear):
    """A storm/spellslinger go-off is a real Bracket-3+ escalation but is NOT a
    Spellbook-verified in-deck combo -- the two must not be conflated."""
    est = estimate_bracket([(forest, 60), (bear, 39)], [], speed_kill_rate=0.0,
                           can_go_off=True, combos_checked=True)
    assert est.bracket >= 3
    assert est.has_verified_combo is False


def test_has_verified_combo_false_with_no_combo_at_all(make_card, forest, bear):
    est = estimate_bracket([(forest, 40), (bear, 59)], [], speed_kill_rate=0.1,
                           combos_checked=True)
    assert est.has_verified_combo is False


def test_go_off_raises_floor_to_three(make_card, forest, bear):
    """A storm/spellslinger deck that reaches lethal on its nut draw (an emergent combo-kill the
    combat clock can't see) is at least Bracket 3, like an in-deck game-ending combo."""
    est = estimate_bracket(
        [(forest, 60), (bear, 39)], [], speed_kill_rate=0.0,  # would be B1 alone
        can_go_off=True, combos_checked=True,
    )
    assert est.bracket >= 3
    assert any("go-off" in r for r in est.reasons)


def test_no_go_off_does_not_raise_floor(make_card, forest, bear):
    est = estimate_bracket(
        [(forest, 60), (bear, 39)], [], speed_kill_rate=0.0, can_go_off=False,
        manabase_consistency=0.50,
    )
    assert est.bracket == 1  # no engine -> no bump (the over-fire guard)


def test_fast_go_off_engine_escalates_past_bracket_3(make_card, forest, bear):
    """A genuine engine (`can_go_off`) that converts on a REALIZED average turn under six
    cannot honestly claim Bracket 3's own promise ("at least six turns before you win or
    lose"). Real numbers: a live Archidekt decklist this rule was written for measures
    avg_kill_turn 4.73 / kill_rate 1.0 / zero Game Changers and its playgroup places it at
    Bracket 4 on exactly that basis — this is that case, not an invented number."""
    est = estimate_bracket(
        [(forest, 60), (bear, 39)], [], speed_kill_rate=1.0,
        can_go_off=True, avg_kill_turn=4.73, combos_checked=True,
    )
    assert est.bracket == 4
    assert any("min Bracket 4" in r for r in est.reasons)


def test_slow_go_off_engine_stays_at_bracket_3(make_card, forest, bear):
    """The three real corpus anchors that go off at all are all >= six turns average
    (7.98 / 8.00 / 10.17) and stay at Bracket 3 (or wherever an unrelated gate places
    them) — the escalation must not fire just because `can_go_off` is true."""
    est = estimate_bracket(
        [(forest, 60), (bear, 39)], [], speed_kill_rate=1.0,
        can_go_off=True, avg_kill_turn=7.98, combos_checked=True,
    )
    assert est.bracket == 3
    assert not any("min Bracket 4" in r for r in est.reasons)


def test_fast_go_off_does_not_override_a_higher_gate(make_card, forest):
    """A deck already at Bracket 4+ from Game Changers/combos/MLD is untouched — this rule
    only ever RAISES a gc<=3 deck past its fixed Bracket-3 point, never lowers or re-derives
    a verdict a stronger gate already set."""
    cards = [(forest, 40)] + [(_gc(make_card, f"GC {i}"), 1) for i in range(6)]
    est = estimate_bracket(
        cards, [], speed_kill_rate=0.2, can_go_off=True, avg_kill_turn=3.0,
        combos_checked=True,
    )
    assert est.bracket == 4  # unchanged from test_many_game_changers_is_bracket_4_plus
    assert not any("min Bracket 4" in r for r in est.reasons)  # the GC gate already did it


def test_missing_avg_kill_turn_does_not_crash_or_escalate(make_card, forest, bear):
    """`avg_kill_turn=None` (a caller that doesn't measure it) must degrade to the
    pre-existing floor-3 behaviour, not raise or silently misbehave."""
    est = estimate_bracket(
        [(forest, 60), (bear, 39)], [], speed_kill_rate=1.0,
        can_go_off=True, avg_kill_turn=None, combos_checked=True,
    )
    assert est.bracket == 3


def test_mass_land_denial_raises_to_four(make_card, forest):
    arma = make_card("Wipe Lands", mana_cost="{3}{W}", type_line="Sorcery",
                     oracle_text="Destroy all lands.")
    est = estimate_bracket([(forest, 40), (arma, 59)], [], speed_kill_rate=0.05)
    assert est.bracket >= 4
    assert est.mass_land_denial_cards == 59


def test_mass_land_denial_does_not_fire_on_nonland_wraths(make_card, forest, bear):
    """A wrath that spares lands is not land denial.

    `_MLD_RES` used to be `each player sacrifices? .*?lands?` with no word boundary,
    so "sacrifices all NONLAND permanents" matched the "land" inside "nonland" — and
    because a single match sets floor=4, one Tragic Arrogance reported an ordinary
    casual deck as Bracket 4 "Optimized". Real oracle text, verbatim.
    """
    tragic = make_card(
        "Tragic Arrogance", mana_cost="{2}{W}{W}", type_line="Sorcery",
        oracle_text=(
            "For each player, you choose from among the permanents that player controls "
            "an artifact, a creature, an enchantment, and a planeswalker. Each player "
            "sacrifices all nonland permanents except the chosen ones."
        ),
    )
    est = estimate_bracket([(forest, 40), (bear, 58), (tragic, 1)], [],
                           speed_kill_rate=0.05, manabase_consistency=0.95)
    assert est.mass_land_denial_cards == 0
    assert est.bracket == 2


def test_mass_land_denial_ignores_sweepers_that_spare_lands(make_card, forest, bear):
    """"Destroy all permanents EXCEPT ... lands" keeps every land on the battlefield."""
    for name, text in [
        ("Scourglass", "Destroy all permanents except for artifacts and lands."),
        ("Elspeth Tirel", "Destroy all other permanents except for lands and tokens."),
        # Graveyard hate, not land denial.
        ("Haunting Echoes", "Exile all cards from target player's graveyard other than basic land cards."),
    ]:
        card = make_card(name, mana_cost="{4}", type_line="Sorcery", oracle_text=text)
        est = estimate_bracket([(forest, 40), (bear, 58), (card, 1)], [],
                               speed_kill_rate=0.05, manabase_consistency=0.95)
        assert est.mass_land_denial_cards == 0, name
        assert est.bracket == 2, name


def test_mass_land_denial_catches_multi_type_sweepers(make_card, forest):
    """The literal "destroy all lands" appears in almost no real MLD card."""
    for name, text in [
        ("Jokulhaups", "Destroy all artifacts, creatures, and lands. They can't be regenerated."),
        ("Obliterate", "This spell can't be countered. Destroy all artifacts, creatures, and lands."),
        ("Devastation", "Destroy all creatures and lands."),
        ("Death Cloud", "Each player loses X life, discards X cards, sacrifices X creatures "
                        "of their choice, then sacrifices X lands of their choice."),
        ("Realm Razer", "When this creature enters, exile all lands."),
    ]:
        card = make_card(name, mana_cost="{4}{R}{R}", type_line="Sorcery", oracle_text=text)
        est = estimate_bracket([(forest, 59), (card, 40)], [], speed_kill_rate=0.05)
        assert est.mass_land_denial_cards == 40, name
        assert est.bracket >= 4, name


def test_extra_turn_chain_raises_to_four(make_card, forest):
    time = make_card("Time Loop", mana_cost="{4}{U}{U}", type_line="Sorcery",
                     oracle_text="Take an extra turn after this one.")
    est = estimate_bracket([(forest, 40), (time, 59)], [], speed_kill_rate=0.05)
    assert est.bracket >= 4
    assert est.extra_turn_cards == 59


def test_extra_turn_name_fallback_catches_blank_oracle_text(make_card, forest):
    """A KNOWN extra-turn card (by name) must still be flagged even when its oracle text is
    missing/blank -- the regex alone would silently miss it, which is worse than a
    duplicated-effort under-count. "Time Walk" is in root bracket.py's EXTRA_TURN_CARDS."""
    time_walk = make_card("Time Walk", mana_cost="{1}{U}", type_line="Sorcery", oracle_text="")
    est = estimate_bracket([(forest, 40), (time_walk, 59)], [], speed_kill_rate=0.05)
    assert est.extra_turn_cards == 59
    assert est.bracket >= 4


def test_mass_land_denial_name_fallback_catches_blank_oracle_text(make_card, forest):
    """Same fallback for MLD: "Armageddon" is in root bracket.py's MASS_LAND_DESTRUCTION_CARDS."""
    armageddon = make_card("Armageddon", mana_cost="{2}{W}", type_line="Sorcery", oracle_text="")
    est = estimate_bracket([(forest, 40), (armageddon, 59)], [], speed_kill_rate=0.05)
    assert est.mass_land_denial_cards == 59
    assert est.bracket >= 4


def test_confidence_lower_without_combo_check(make_card, forest, bear):
    checked = estimate_bracket([(forest, 40), (bear, 59)], [], combos_checked=True)
    unchecked = estimate_bracket([(forest, 40), (bear, 59)], [], combos_checked=False)
    assert unchecked.confidence < checked.confidence
    assert 0.2 <= unchecked.confidence <= 0.95


# --- B2/B3 boundary banner (plays_up) ---
# The banner no longer claims to DETECT upper-Core tuning per deck. Measured 2026-07-28 on
# 120 zero-Game-Changer anchors, the old ceiling/speed/interaction gate fired on 33% of
# author-labeled Upgraded decks and 37% of Core ones — more often on the decks it was meant
# to leave alone. Nothing measurable separates that population, so the flag now states a
# calibration fact that holds for every deck in the band instead of a false per-deck reading.


def test_plays_up_flags_the_whole_unresolvable_band(forest, bear):
    """Any zero-GC deck capped at Core carries the banner — the boundary is unresolvable."""
    for kwargs in (
        {"speed_kill_rate": 0.1},                       # was "high ceiling"
        {"speed_kill_rate": 0.9, "avg_kill_turn": 9.0},  # was "fast clock"
        {"speed_kill_rate": 0.5, "interaction": 70.0},   # was "plain Core"
    ):
        est = estimate_bracket([(forest, 40), (bear, 59)], [],
                               manabase_consistency=0.95, **kwargs)
        assert est.bracket == 2, kwargs
        assert est.plays_up is True, kwargs
        assert any("Upgraded" in r for r in est.reasons), kwargs


def test_plays_up_also_claimed_for_exhibition(forest, bear):
    """A deck placed at Bracket 1 via a thin manabase is STILL in the unresolvable band.

    Reversed 2026-08-24: the prior version of this test asserted `plays_up is False` here
    on the stated assumption "a deck placed at Bracket 1 isn't at the Core/Upgraded boundary
    at all." That was never measured. Checked against the full 297-deck corpus
    (scripts/bracket_accuracy.py --json): 14.1% (10/71) of decks landing at Bracket 1 via
    this exact path are called Upgraded (Bracket 3) by their own builder anyway. A thin
    manabase measures consistency, not power, and the Game Changer gate is silent on power
    either way once GC == 0.
    """
    est = estimate_bracket([(forest, 40), (bear, 59)], [], manabase_consistency=0.50)
    assert est.bracket == 1
    assert est.plays_up is True
    assert any("Upgraded" in r for r in est.reasons)


def test_plays_up_only_in_the_gc0_band(make_card, forest):
    """The banner is for gc==0/no-combo decks only; an escalated deck never gets it."""
    cards = [(forest, 57)] + [(_gc(make_card, f"GC{i}"), 1) for i in range(2)]
    est = estimate_bracket(cards, [], speed_kill_rate=0.9, avg_kill_turn=6.0)
    assert est.bracket == 3  # 2 Game Changers -> floor 3
    assert est.plays_up is False


def test_exhibition_deck_still_plays_up_regardless_of_axes(forest, bear):
    """The banner is a calibration fact about the GC==0 gate, not a per-deck power reading —
    it fires the same whether the deck's other axes look strong or, as here, uniformly weak."""
    est = estimate_bracket([(forest, 60), (bear, 39)], [], speed_kill_rate=0.0,
                           manabase_consistency=0.50)
    assert est.bracket == 1
    assert est.plays_up is True


def test_an_unverified_combo_count_is_not_reported_as_unchecked(forest, bear):
    """The note contradicted the gate sitting two lines above it.

    A caller may supply a combo COUNT without having run a verified check — the engine
    accepts that and docks confidence. But it then appended "combos not checked", which reads
    as "no combo information was used" while the gate had already promoted the deck to
    Bracket 3 on that very count. Confidence is not in the reason list, so the dock was
    invisible and the two visible lines simply disagreed.

    Found while scoring the estimator against the corpus labels: a harness passed a count by
    mistake and the contradictory pair is what exposed it.
    """
    from mythgauntlet.ratings.bracket import estimate_bracket

    declared = estimate_bracket([(forest, 40), (bear, 59)], [],
                                two_card_combos=2, combos_checked=False)
    notes = [r for r in declared.reasons if r.startswith("note:")]
    assert notes, "an unverified run must still carry a note"
    assert "DECLARED but not verified" in notes[0]
    assert declared.bracket >= 3, "the gate still fires on the supplied count"

    silent = estimate_bracket([(forest, 40), (bear, 59)], [],
                              two_card_combos=0, combos_checked=False)
    quiet = [r for r in silent.reasons if r.startswith("note:")]
    assert quiet and "not checked" in quiet[0], "no count -> the plain note is still right"
    assert "DECLARED" not in quiet[0]
