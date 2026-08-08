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


def test_cheat_into_play_requires_putting_a_CREATURE(make_card):
    """`cheats_creatures` drives tier0's Kaalia model, which pulls the biggest stranded
    creature out of hand and swings with it that turn. The tag was the bare substring
    "from your hand onto the battlefield", which says nothing about WHAT is put — so land
    ramp read as a creature cheat. Of 164 cards matching it in the 34,179-card store, only
    91 can put a creature; 50 put a land.

    Controlled measurement on a slow 8-drop ramp deck, one copy, 500 runs: with the old
    tag a single Burgeoning moved goldfish kill rate 0.536 -> 0.612 and avg kill turn
    12.05 -> 10.75. Sakura-Tribe Scout produced identical numbers, confirming it was the
    tag flipping rather than anything about the card. With the fix both match the control
    deck exactly.
    """
    def fx(name, type_line, text):
        return tags.analyze(make_card(name, mana_cost="{2}{G}", type_line=type_line,
                                      oracle_text=text)).cheats_creatures

    # Land ramp — reads identically to a cheat enabler, is not one.
    assert not fx("Burgeoning", "Enchantment",
                  "Whenever an opponent plays a land, you may put a land card from your "
                  "hand onto the battlefield.")
    assert not fx("Sakura-Tribe Scout", "Creature — Human Scout",
                  "{T}: You may put a land card from your hand onto the battlefield.")
    assert not fx("Growth Spiral", "Instant",
                  "Draw a card. You may put a land card from your hand onto the battlefield.")
    # Not creatures either.
    assert not fx("Planebound Accomplice", "Creature — Human",
                  "{R}: You may put a planeswalker card from your hand onto the battlefield.")
    assert not fx("Stoneforge Mystic", "Creature — Kor Artificer",
                  "When this creature enters, you may put an Equipment card from your hand "
                  "onto the battlefield.")
    # A self-put cannot cheat in the fatty stranded beside it — not an enabler.
    assert not fx("Talon Gates of Madara", "Land",
                  "You may put this card from your hand onto the battlefield.")

    # The real Kaalia class must still fire.
    assert fx("Sneak Attack", "Enchantment",
              "{R}: You may put a creature card from your hand onto the battlefield. "
              "It gains haste.")
    assert fx("Elvish Piper", "Creature — Elf",
              "{G}, {T}: You may put a creature card from your hand onto the battlefield.")
    assert fx("Quicksilver Amulet", "Artifact",
              "{4}, {T}: You may put a creature card from your hand onto the battlefield.")
    assert fx("Kaalia of the Vast", "Legendary Creature — Angel",
              "Whenever Kaalia of the Vast attacks, you may put an Angel, Demon, or Dragon "
              "creature card from your hand onto the battlefield tapped and attacking.")
    # "permanent card" can be a creature, so it counts.
    assert fx("Thran Temporal Gateway", "Artifact",
              "{4}, {T}: You may put a historic permanent card from your hand onto the "
              "battlefield.")


def test_board_wipe_requires_sweeping_CREATURES(make_card):
    """`p.wipe` makes tier2 call `_wipe_table`, so the pattern must mean creatures.

    "destroy all"/"exile all" matched 632 cards in the 34,179-card store; only 458 can
    touch a creature. Gating the swept OBJECT dropped 174 and added none.
    """
    def w(text):
        return tags.analyze(make_card("X", mana_cost="{2}", type_line="Sorcery",
                                      oracle_text=text)).board_wipe

    assert w("Destroy all creatures. They can't be regenerated.")
    assert w("Exile all nonland permanents that are white.")
    assert w("Pyroclasm deals 2 damage to each creature.")
    # A modal card only needs ONE creature mode; the earlier modes name other types.
    assert w("Choose two — Destroy all artifacts. Destroy all enchantments. "
             "Destroy all creatures with mana value 3 or less.")

    assert not w("Destroy all artifacts you don't control.")            # Vandalblast
    assert not w("Destroy all artifacts and enchantments.")             # Fracturing Gust
    assert not w("Destroy all lands.")                                  # Armageddon
    assert not w("When this enchantment enters, exile all graveyards.")  # Rest in Peace
    # A creature CARD lives in a zone; a creature is a battlefield permanent.
    assert not w("Exile all creature cards from target player's graveyard.")
    # The creature here is only where the Equipment is attached.
    assert not w("Whenever this creature blocks, destroy all Equipment attached to that creature.")
    # A power-only debuff has never killed anything.
    assert not w("All creatures get -2/-0 until end of turn.")           # Marsh Gas
    assert w("All creatures get -2/-2 until end of turn.")               # Biting Rain


def test_removal_requires_hitting_a_CREATURE(make_card):
    """Each point of `p.removal` kills the opponent's biggest creature in tier2.

    "destroy target"/"exile target"/damage matched 2,971 cards; 895 of them cannot touch a
    creature at all — a Reclamation Sage or a Stone Rain was eating a fatty every cast.
    """
    def r(text):
        return tags.analyze(make_card("X", mana_cost="{2}", type_line="Instant",
                                      oracle_text=text)).removal

    assert r("Destroy target creature.")
    assert r("Destroy target nonland permanent.")
    assert r("This spell deals 3 damage to any target.")

    assert not r("Destroy target artifact.")                    # Naturalize
    assert not r("Destroy target land.")                        # Stone Rain
    assert not r("Destroy target enchantment.")
    assert not r("Exile target creature card from a graveyard.")  # zone, not battlefield
    assert not r("This spell deals 3 damage to target player.")   # Lava Spike


def test_ramp_is_net_of_the_activation_cost(make_card):
    """`ramp_sources` is spent by tier0 as that many extra mana EVERY turn, so it has to
    be NET. Counting only the produced symbols made an Azorius Signet worth +2 when it
    nets +1, and made a pure colour filter ("{1}, {T}: Add {B}") worth a full mana per
    turn when it nets zero. 49 mana abilities in the compiled store cost mana.
    """
    def ramp(text, type_line="Artifact"):
        return tags.analyze(make_card("R", mana_cost="{2}", type_line=type_line,
                                      oracle_text=text)).ramp_sources

    assert ramp("{T}: Add {C}{C}.") == 2                       # Sol Ring
    assert ramp("{1}, {T}: Add {W}{U}.") == 1                  # Azorius Signet: 2 - 1
    assert ramp("{T}: Add one mana of any color.") == 1        # Arcane Signet
    assert ramp("{T}: Add three mana of any one color.") == 3  # Gilded Lotus
    assert ramp("{1}, {T}: Add {B}.") == 0                     # filter, nets nothing
    assert ramp("{2}, {T}: Add {W}{U}.") == 0                  # filter, nets nothing
    # {T} is not mana and must never be charged as part of the cost.
    assert ramp("{T}: Add {G}.", "Creature — Elf Druid") == 1  # Llanowar Elves
