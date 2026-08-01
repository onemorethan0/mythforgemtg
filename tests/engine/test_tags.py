from mythgauntlet.semantics import tags


def test_mana_rock_counts_produced_mana(sol_ring_like):
    fx = tags.analyze(sol_ring_like)
    assert fx.ramp_sources == 2
    assert not fx.fetches_land


def test_any_color_rock_counts_once(make_card):
    card = make_card(
        "Prism Rock", mana_cost="{3}", type_line="Artifact",
        oracle_text="{T}: Add {W}, {U}, {B}, {R}, or {G}.",
    )
    assert tags.analyze(card).ramp_sources == 1


def test_land_fetch_sorcery_is_ramp_not_tutor(make_card):
    card = make_card(
        "Growth Spell", mana_cost="{1}{G}", type_line="Sorcery",
        oracle_text="Search your library for a basic land card, put that card onto the "
        "battlefield tapped, then shuffle.",
    )
    fx = tags.analyze(card)
    assert fx.fetches_land and fx.ramp_sources == 1
    assert not fx.tutor


def test_draw_counts_words(make_card):
    card = make_card(
        "Insight Spell", mana_cost="{2}{U}", type_line="Sorcery", oracle_text="Draw two cards."
    )
    assert tags.analyze(card).draw_cards == 2


def test_opponent_draw_not_counted(make_card):
    card = make_card(
        "Gift Spell", mana_cost="{U}", type_line="Sorcery",
        oracle_text="Target opponent draws two cards.",
    )
    assert tags.analyze(card).draw_cards == 0


def test_tapland_detected(make_card):
    card = make_card(
        "Slow Caves", mana_cost="", type_line="Land",
        oracle_text="Slow Caves enters the battlefield tapped.\n{T}: Add {B} or {R}.",
        produced_mana=("B", "R"),
    )
    assert tags.analyze(card).enters_tapped


def test_conditional_tapland_treated_untapped(make_card):
    card = make_card(
        "Check Caves", mana_cost="", type_line="Land",
        oracle_text="Check Caves enters the battlefield tapped unless you control a Swamp.",
    )
    assert not tags.analyze(card).enters_tapped


def test_removal_and_counterspell(make_card):
    kill = make_card(
        "Kill Spell", mana_cost="{1}{B}", type_line="Instant",
        oracle_text="Destroy target creature.",
    )
    counter = make_card(
        "Deny Spell", mana_cost="{U}{U}", type_line="Instant",
        oracle_text="Counter target spell.",
    )
    assert tags.analyze(kill).removal == 1
    assert tags.analyze(counter).counterspell


def test_board_wipe(make_card):
    card = make_card(
        "Sweep Spell", mana_cost="{2}{W}{W}", type_line="Sorcery",
        oracle_text="Destroy all creatures.",
    )
    assert tags.analyze(card).board_wipe


def test_nonland_tutor(make_card):
    card = make_card(
        "Dark Tutor", mana_cost="{1}{B}", type_line="Sorcery",
        oracle_text="Search your library for a card, put that card into your hand, then shuffle.",
    )
    fx = tags.analyze(card)
    assert fx.tutor
    assert not fx.fetches_land


def test_impact_prior_from_rank(make_card):
    popular = make_card("Popular Card", edhrec_rank=100)
    obscure = make_card("Obscure Card", edhrec_rank=24_000)
    unranked = make_card("Unranked Card")
    assert tags.analyze(popular).impact > tags.analyze(obscure).impact
    assert 0.0 <= tags.analyze(unranked).impact <= 1.0


# --- storm / spellslinger engine detection (docs/SIMULATION.md) -------------------------


def test_cast_only_burn_detected(make_card):
    # Guttersnipe class: fires on the CAST only -- storm copies do NOT trigger it.
    guttersnipe = make_card(
        "Pinger", type_line="Creature",
        oracle_text="Whenever you cast an instant or sorcery spell, this creature deals "
                    "2 damage to each opponent.",
    )
    fx = tags.analyze(guttersnipe)
    assert fx.cast_damage == 2
    assert fx.magecraft_damage == 0  # not magecraft -> copies don't amplify it


def test_magecraft_burn_amplified_by_copies(make_card):
    # Magecraft fires on cast OR copy, so storm copies each trigger it.
    magecraft = make_card(
        "Spell Sear", type_line="Creature",
        oracle_text="Magecraft -- whenever you cast or copy an instant or sorcery spell, "
                    "this creature deals 1 damage to each opponent.",
    )
    fx = tags.analyze(magecraft)
    assert fx.magecraft_damage == 1
    assert fx.cast_damage == 0


def test_creature_cast_burn_not_counted(make_card):
    # Screamer-Killer / Rakdos class: burn triggered by CASTING CREATURES is not a spellslinger
    # payoff -- it must not read as face burn for the storm engine (real corpus false positive).
    screamer = make_card(
        "Big Bug", type_line="Creature",
        oracle_text="Trample. Whenever you cast a Kindred spell or a creature spell, this "
                    "creature deals 5 damage to any target.",
    )
    fx = tags.analyze(screamer)
    assert fx.cast_damage == 0 and fx.magecraft_damage == 0


def test_creature_only_scaling_burn_not_a_finisher(make_card):
    # Shatterskull Smashing class: X damage that can only hit creatures/planeswalkers is not a
    # player finisher (real corpus false positive).
    shatterskull = make_card(
        "Split Bolt", mana_cost="{X}{R}{R}", type_line="Sorcery",
        oracle_text="Split Bolt deals X damage divided as you choose among up to two target "
                    "creatures and/or planeswalkers.",
    )
    assert tags.analyze(shatterskull).scaling_burn is False


def test_scaling_burn_to_any_target_is_a_finisher(make_card):
    fireball = make_card(
        "Fire Ball", mana_cost="{X}{R}", type_line="Sorcery",
        oracle_text="Fire Ball deals X damage to any target.",
    )
    assert tags.analyze(fireball).scaling_burn is True


def test_prismari_grants_storm(make_card):
    muse = make_card(
        "Storm Muse", mana_cost="{2}{U}{R}", type_line="Legendary Creature",
        oracle_text="Instant and sorcery spells you cast have storm.",
    )
    assert tags.analyze(muse).grants_storm is True


def test_worded_mana_amounts_are_ramp(make_card):
    """"Add one mana of any color" is ramp — the format's most-played acceleration.

    The add-clause regex only matched mana SYMBOLS ("Add {C}{C}"), so every rock and dork
    that spells the amount out in words produced ZERO ramp: 416 cards, including Arcane
    Signet (EDHREC rank 3), Fellwar Stone (17), Birds of Paradise (33) and Commander's
    Sphere (48). Mana available by turn is the quantity Tier-0 runs on, so this
    under-counted the acceleration of essentially every deck.
    """
    signet = make_card(
        "Signet Rock", mana_cost="{2}", type_line="Artifact",
        oracle_text="{T}: Add one mana of any color in your commander's color identity.",
    )
    assert tags.analyze(signet).ramp_sources == 1

    dork = make_card(
        "Paradise Bird", mana_cost="{G}", type_line="Creature — Bird",
        oracle_text="Flying\n{T}: Add one mana of any color.",
    )
    assert tags.analyze(dork).ramp_sources == 1

    lotus = make_card(
        "Golden Lotus", mana_cost="{5}", type_line="Artifact",
        oracle_text="{T}: Add three mana of any one color.",
    )
    assert tags.analyze(lotus).ramp_sources == 3


def test_one_shot_mana_is_not_a_permanent_source(make_card):
    """Mana that is spent by ceasing to exist is not a mana SOURCE.

    Tier-0 models ramp_sources as a permanent that untaps every turn, so a ritual counted
    that way pays out every turn forever — Dark Ritual was worth three permanent sources.
    Tier-2 models the burst separately as ritual_mana.
    """
    ritual = make_card(
        "Dark Rite", mana_cost="{B}", type_line="Instant", oracle_text="Add {B}{B}{B}.",
    )
    fx = tags.analyze(ritual)
    assert fx.ramp_sources == 0
    assert fx.ritual_mana == 2  # three mana for a one-mana spell = net two

    petal = make_card(
        "Petal", mana_cost="{0}", type_line="Artifact",
        oracle_text="{T}, Sacrifice this artifact: Add one mana of any color.",
    )
    assert tags.analyze(petal).ramp_sources == 0


def test_sacrificing_for_a_card_still_taps_for_mana(make_card):
    """Commander's Sphere sacrifices for a CARD and taps for mana repeatably.

    A first attempt at the one-shot guard matched a sacrifice clause anywhere in the
    text, which zeroed it. The sacrifice must be the cost of the MANA ability itself.
    """
    sphere = make_card(
        "Sphere of Command", mana_cost="{3}", type_line="Artifact",
        oracle_text="{T}: Add one mana of any color in your commander's color identity.\n"
                    "Sacrifice this artifact: Draw a card.",
    )
    assert tags.analyze(sphere).ramp_sources == 1


def test_opponent_land_search_is_not_our_ramp(make_card):
    """Path to Exile lets the OPPONENT search; crediting it to us made removal read as
    acceleration. A symmetric "each player searches" does still ramp us."""
    path = make_card(
        "Exile Path", mana_cost="{W}", type_line="Instant",
        oracle_text="Exile target creature. Its controller may search their library for "
                    "a basic land card, put it onto the battlefield tapped, then shuffle.",
    )
    fx = tags.analyze(path)
    assert fx.ramp_sources == 0 and not fx.fetches_land

    symmetric = make_card(
        "Shared Bounty", mana_cost="{2}{G}", type_line="Sorcery",
        oracle_text="Each player searches their library for a basic land card and puts "
                    "it onto the battlefield tapped, then shuffles.",
    )
    assert tags.analyze(symmetric).fetches_land
