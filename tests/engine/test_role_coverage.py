"""Role coverage pass (2026-10-18): the classes a real Jeskai artifact-tokens deck (Vraska, Soul
of Stone) exposed when 41 of its 62 nonland cards had NO role and the Deck Mentor reported one
removal spell and one finisher. Every oracle text below is verbatim from the card store.

Each class is pinned with its positives AND the near-misses its gate exists to reject, because
the near-miss is where these patterns have failed before (verb without object, effect without
its cost)."""

import pytest

from mythgauntlet.ratings import redundancy
from mythgauntlet.semantics import tags


def _roles(card):
    return redundancy.card_roles(tags.analyze(card))


# --- removal: an anaphor resolved back to its target -------------------------------------

def test_dispatch_metalcraft_exile_is_removal(make_card):
    card = make_card("Dispatch", mana_cost="{W}", type_line="Instant", oracle_text=(
        "Tap target creature.\nMetalcraft — If you control three or more artifacts, exile "
        "that creature."))
    assert tags.analyze(card).removal == 1
    assert "exile" in tags.interaction_modes(tags._clean_text(card)).spot


def test_edict_by_anaphor_is_removal(make_card):
    card = make_card("Imperial Edict", mana_cost="{1}{B}", type_line="Sorcery",
                     oracle_text="Target opponent chooses a creature they control. Destroy "
                     "that creature.")
    assert tags.analyze(card).removal == 1


@pytest.mark.parametrize("name,text", [
    # the target was PUMPED first: the destroy is a drawback on your own attacker
    ("Berserk", "Cast this spell only before the combat damage step.\nTarget creature gains "
     "trample and gets +X/+0 until end of turn, where X is its power. At the beginning of the "
     "next end step, destroy that creature if it attacked this turn."),
    ("War Barge", "{3}: Target creature gains islandwalk until end of turn. When this artifact "
     "leaves the battlefield this turn, destroy that creature. A creature destroyed this way "
     "can't be regenerated."),
    # combat text with no target at all
    ("Cockatrice", "Flying\nWhenever this creature blocks or becomes blocked by a non-Wall "
     "creature, destroy that creature at end of combat."),
    # own creature
    ("Mogg Cannon", "{T}: Target creature you control gets +1/+0 and gains flying until end "
     "of turn. Destroy that creature at the beginning of the next end step."),
])
def test_anaphoric_kill_near_misses_are_not_removal(make_card, name, text):
    card = make_card(name, mana_cost="{3}", type_line="Artifact", oracle_text=text)
    assert tags.analyze(card).removal == 0


# --- noncreature answers: their own role, never `removal` ---------------------------------

def test_crush_contraband_is_noncreature_removal_not_removal(make_card):
    card = make_card("Crush Contraband", mana_cost="{3}{W}", type_line="Instant", oracle_text=(
        "Choose one or both —\n• Exile target artifact.\n• Exile target enchantment."))
    fx = tags.analyze(card)
    assert fx.removal == 0 and not fx.board_wipe        # tier2 must not spend it as a kill
    assert fx.noncreature_removal
    assert _roles(card) == {"noncreature_removal": 1.0}


def test_a_card_that_also_kills_creatures_is_not_double_counted(make_card):
    card = make_card("Austere Command", mana_cost="{4}{W}{W}", type_line="Sorcery",
                     oracle_text="Choose two —\n• Destroy all artifacts.\n• Destroy all "
                     "enchantments.\n• Destroy all creatures with mana value 3 or less.\n"
                     "• Destroy all creatures with mana value 4 or greater.")
    fx = tags.analyze(card)
    assert fx.board_wipe and not fx.noncreature_removal


@pytest.mark.parametrize("text", [
    "Blightning deals 3 damage to target player or planeswalker. That player or that "
    "planeswalker's controller discards two cards.",       # face burn, not an answer
    "Destroy target land.",                                  # land destruction is excluded
    "Exile target artifact you control, then return it to the battlefield.",   # own flicker
])
def test_noncreature_near_misses(make_card, text):
    card = make_card("X", mana_cost="{2}", type_line="Sorcery", oracle_text=text)
    assert not tags.analyze(card).noncreature_removal


# --- land searches that name a basic TYPE -------------------------------------------------

def test_archaeomancers_map_is_neither_tutor_nor_land_ramp(make_card):
    card = make_card("Archaeomancer's Map", mana_cost="{2}{W}", type_line="Artifact",
                     oracle_text=(
        "When this artifact enters, search your library for up to two basic Plains cards, "
        "reveal them, put them into your hand, then shuffle.\nWhenever a land an opponent "
        "controls enters, if that player controls more lands than you, you may put a land "
        "card from your hand onto the battlefield."))
    fx = tags.analyze(card)
    assert not fx.tutor
    assert not fx.fetches_land      # the search goes to HAND; another ability says battlefield


def test_basic_type_search_to_battlefield_is_ramp(make_card):
    card = make_card("Three Visits", mana_cost="{1}{G}", type_line="Sorcery",
                     oracle_text="Search your library for a Forest card, put it onto the "
                     "battlefield, then shuffle.")
    fx = tags.analyze(card)
    assert fx.fetches_land and fx.ramp_sources == 1 and not fx.tutor


def test_two_sentence_land_search_still_reaches_the_battlefield(make_card):
    card = make_card("Verdant Mastery", mana_cost="{5}{G}", type_line="Sorcery", oracle_text=(
        "You may pay {3}{G} rather than pay this spell's mana cost.\nSearch your library for "
        "up to four basic land cards and reveal them. Put one of them onto the battlefield "
        "tapped under an opponent's control if the {3}{G} cost was paid. Put two of them onto "
        "the battlefield tapped under your control and the rest into your hand. Then shuffle."))
    assert tags.analyze(card).fetches_land


# --- ramp a player counts that the mana-ability regex cannot see --------------------------

def test_magecraft_treasure_is_ramp(make_card):
    card = make_card("Storm-Kiln Artist", mana_cost="{3}{R}", type_line="Creature — Dwarf Shaman",
                     oracle_text=(
        "This creature gets +1/+0 for each artifact you control.\nMagecraft — Whenever you "
        "cast or copy an instant or sorcery spell, create a Treasure token."))
    assert _roles(card).get("ramp") == 1.0


def test_repeatable_treasure_trigger_is_ramp(make_card):
    card = make_card("Pitiless Plunderer", mana_cost="{3}{B}", type_line="Creature — Human",
                     oracle_text="Whenever another creature you control dies, create a "
                     "Treasure token.")
    assert tags.analyze(card).treasure_ramp == 1


@pytest.mark.parametrize("name,type_line,text", [
    # an ETB Treasure is a one-shot, like a ritual
    ("Galazeth-ish", "Creature — Dragon", "When this creature enters, create a Treasure token."),
    # the trigger's event is a price you pay (Nuka-Cola nets -2 mana)
    ("Nuka-Cola Vending Machine", "Artifact", "{1}, {T}: Create a Food token.\nWhenever you "
     "sacrifice a Food, create a tapped Treasure token."),
    # an amplifier is not a source: Xorn makes nothing on its own
    ("Xorn", "Creature — Elemental", "If you would create one or more Treasure tokens, instead "
     "create those tokens plus an additional Treasure token."),
    # somebody else's Treasure
    ("Gift", "Enchantment", "At the beginning of your upkeep, target opponent creates a "
     "Treasure token."),
    # activation that costs what it makes
    ("Forsworn-ish", "Creature — Human", "{1}{B}, {T}, Pay 1 life: Create a Treasure token."),
])
def test_treasure_near_misses(make_card, name, type_line, text):
    card = make_card(name, mana_cost="{3}", type_line=type_line, oracle_text=text)
    assert tags.analyze(card).treasure_ramp == 0


@pytest.mark.parametrize("name,text,n", [
    ("Geist of Saint Thalia", "Flying\nNoncreature spells you cast cost {1} less to cast.", 1),
    ("Semblance Anvil", "Imprint — When this artifact enters, you may exile a nonland card "
     "from your hand.\nSpells you cast that share a card type with the exiled card cost {2} "
     "less to cast.", 2),
    ("Inspiring Statuary", "Nonartifact spells you cast have improvise.", 1),
])
def test_cost_reducers_are_ramp(make_card, name, text, n):
    card = make_card(name, mana_cost="{3}", type_line="Artifact", oracle_text=text)
    assert tags.analyze(card).cost_reduction == n
    assert _roles(card)["ramp"] == float(n)


@pytest.mark.parametrize("text", [
    "This spell costs {2} less to cast if you control an artifact.",          # itself
    "+2: Artifact, instant, and sorcery spells you cast this turn cost {2} less to cast.",
    "Spells you cast that target this creature cost {2} less to cast.",
    "Spells your opponents cast cost {1} more to cast.",
])
def test_cost_reduction_near_misses(make_card, text):
    card = make_card("X", mana_cost="{3}", type_line="Artifact", oracle_text=text)
    assert tags.analyze(card).cost_reduction == 0


# --- draw: a standing permission to cast from the top -------------------------------------

def test_mystic_forge_is_draw(make_card):
    card = make_card("Mystic Forge", mana_cost="{4}", type_line="Artifact", oracle_text=(
        "You may look at the top card of your library any time.\nYou may cast artifact spells "
        "and colorless spells from the top of your library.\n{T}, Pay 1 life: Exile the top "
        "card of your library."))
    assert tags.analyze(card).top_of_library
    assert _roles(card) == {"draw": 1.5}


def test_a_one_turn_window_from_the_top_is_not_an_engine(make_card):
    card = make_card("The Belligerent", mana_cost="{3}{U}{R}", type_line="Artifact — Vehicle",
                     oracle_text=(
        "Whenever The Belligerent attacks, create a Treasure token. Until end of turn, you may "
        "look at the top card of your library any time, and you may play lands and cast spells "
        "from the top of your library."))
    assert not tags.analyze(card).top_of_library


# --- finishers -----------------------------------------------------------------------------

def test_mechanized_production_alt_win_is_a_finisher(make_card):
    card = make_card("Mechanized Production", mana_cost="{2}{U}{U}",
                     type_line="Enchantment — Aura", oracle_text=(
        "Enchant artifact you control\nAt the beginning of your upkeep, create a token that's "
        "a copy of enchanted artifact. Then if you control eight or more artifacts with the "
        "same name as one another, you win the game."))
    assert _roles(card) == {"finisher": 3.0}


@pytest.mark.parametrize("name,text", [
    ("Tempered Steel", "Artifact creatures you control get +2/+2."),
    ("Sentinel Sarah Lyons", "Haste\nAs long as an artifact entered the battlefield under your "
     "control this turn, creatures you control get +2/+2.\nBattalion — Whenever Sentinel "
     "Sarah Lyons and at least two other creatures attack, Sentinel Sarah Lyons deals damage "
     "equal to the number of artifacts you control to target player."),
    ("Intangible Virtue", "Creature tokens you control get +1/+1 and have vigilance."),
])
def test_static_team_anthems_are_finishers(make_card, name, text):
    card = make_card(name, mana_cost="{3}", type_line="Enchantment", oracle_text=text)
    assert tags.analyze(card).team_anthem


@pytest.mark.parametrize("text", [
    "Other Elf creatures you control get +1/+1.",            # a tribal lord is the tribe's plan
    "White creatures you control get +1/+1.",                 # colour lord
    "Creatures you control get +2/+2 until end of turn.",     # a one-shot: `_overrun`'s
    "Creatures you control get +0/+2.",                       # a wall of toughness closes nothing
])
def test_anthem_near_misses(make_card, text):
    card = make_card("X", mana_cost="{3}", type_line="Enchantment", oracle_text=text)
    assert not tags.analyze(card).team_anthem


def test_extra_combat_is_a_finisher(make_card):
    card = make_card("Relentless Assault", mana_cost="{2}{R}{R}", type_line="Sorcery",
                     oracle_text="Untap all creatures that attacked this turn. After this main "
                     "phase, there is an additional combat phase followed by an additional "
                     "main phase.")
    assert _roles(card) == {"finisher": 2.0}


def test_a_lone_scaling_threat_is_not_a_finisher(make_card):
    """Deliberate exclusion: a single big evasive body is a THREAT; the taxonomy has no threat
    role, and counting every fatty as a finisher would put them all in the cut pool."""
    card = make_card("Brotherhood Vertibird", mana_cost="{3}", type_line="Artifact — Vehicle",
                     oracle_text="Flying\nBrotherhood Vertibird's power is equal to the number "
                     "of artifacts you control.\nCrew 2")
    assert _roles(card) == {}


# --- draw: impulse (exile the top, you may play it) ----------------------------------------

def _impulse(card):
    fx = tags.analyze(card)
    return fx.impulse_draw, fx.impulse_engine


def test_light_up_the_stage_is_one_shot_impulse_at_half_weight(make_card):
    card = make_card("Light Up the Stage", mana_cost="{2}{R}", type_line="Sorcery", oracle_text=(
        "Spectacle {R} (You may cast this spell for its spectacle cost rather than its mana cost "
        "if an opponent lost life this turn.)\nExile the top two cards of your library. Until "
        "the end of your next turn, you may play those cards."))
    assert _impulse(card) == (2, 0)
    assert _roles(card) == {"draw": 2 * redundancy.IMPULSE_WEIGHT}
    fx = tags.analyze(card)
    assert fx.draw_cards == 0 and fx.engine_draw == 0   # tier0 never spends it as a card in hand


@pytest.mark.parametrize("name,type_line,text,expected", [
    # a mode bullet behind an ability word, under a recurring trigger
    ("Outpost Siege", "Enchantment", "As this enchantment enters, choose Khans or Dragons.\n"
     "• Khans — At the beginning of your upkeep, exile the top card of your library. Until end "
     "of turn, you may play that card.\n• Dragons — Whenever a creature you control leaves the "
     "battlefield, this enchantment deals 1 damage to any target.", (0, 1)),
    ("Wiccan, Young Avenger", "Legendary Creature — Mutant Warlock Hero", "Whenever you cast a "
     "noncreature spell, exile the top card of your library. Until your next end step, you may "
     "play that card.", (0, 1)),
    # a modal spell's bullet is the spell's own one-shot
    ("Jeska's Will", "Sorcery", "Choose one. If you control a commander as you cast this "
     "spell, you may choose both instead.\n• Add {R} for each card in target opponent's hand.\n"
     "• Exile the top three cards of your library. You may play them this turn.", (3, 0)),
    # +1 repeats; the −7 is spent once and capped at three
    ("Chandra, Fire Artisan", "Legendary Planeswalker — Chandra", "Whenever one or more "
     "loyalty counters are removed from Chandra, she deals that much damage to target opponent "
     "or planeswalker.\n+1: Exile the top card of your library. You may play it this turn.\n"
     "−7: Exile the top seven cards of your library. You may play them this turn.", (3, 1)),
    # a dies trigger is one-shot, and its bullets inherit that
    ("Atsushi, the Blazing Sky", "Legendary Creature — Dragon Spirit", "Flying, trample\nWhen "
     "Atsushi dies, choose one —\n• Exile the top two cards of your library. Until the end of "
     "your next turn, you may play those cards.\n• Create three Treasure tokens.", (2, 0)),
    # "you may exile ... If you do, you may play" is the same ability going ahead
    ("Superior Foes of Spider-Man", "Creature — Human Rogue Villain", "Trample\nWhenever you "
     "cast a spell with mana value 4 or greater, you may exile the top card of your library. If "
     "you do, you may play that card until you exile another card with this creature.", (0, 1)),
    # the upkeep impulse REPLACES the skipped draw: two cards, one of them already ours
    ("Wild Wasteland", "Enchantment", "Skip your draw step.\nAt the beginning of your upkeep, "
     "exile the top two cards of your library. You may play those cards this turn.", (0, 1)),
])
def test_impulse_positives(make_card, name, type_line, text, expected):
    assert _impulse(make_card(name, type_line=type_line, oracle_text=text)) == expected


def test_one_of_those_cards_is_one_card(make_card):
    card = make_card("Jaya, Fiery Negotiator", type_line="Legendary Planeswalker — Jaya",
                     oracle_text=(
        "+1: Create a 1/1 red Monk creature token with prowess.\n−1: Exile the top two cards of "
        "your library. Choose one of them. You may play that card this turn."))
    assert _impulse(card) == (1, 0)


@pytest.mark.parametrize("name,type_line,text", [
    # the permission is somebody else's
    ("Curse of Hospitality", "Enchantment — Aura Curse", "Enchant player\nCreatures attacking "
     "enchanted player have trample.\nWhenever a creature deals combat damage to enchanted "
     "player, that player exiles the top card of their library. Until end of turn, that "
     "creature's controller may play that card and they may spend mana as though it were mana "
     "of any color to cast that spell."),
    ("Expedited Inheritance", "Enchantment", "Whenever a creature is dealt damage, its "
     "controller may exile that many cards from the top of their library. They may play those "
     "cards until the end of their next turn."),
    # a GRANTED ability is the slivers', not this card's
    ("Capricious Sliver", "Creature — Sliver", "Sliver creatures you control have \"Whenever "
     "this creature deals combat damage to a player, exile the top card of your library. You "
     "may play that card this turn.\""),
    # conditional on what was exiled, or type-restricted: how many are castable is unknowable
    ("Chandra, Dressed to Kill", "Legendary Planeswalker — Chandra", "+1: Exile the top card of "
     "your library. If it's red, you may cast it this turn.\n−7: Exile the top five cards of "
     "your library. You may cast red spells from among them this turn."),
    ("Chandra, Hope's Beacon", "Legendary Planeswalker — Chandra", "+1: Exile the top five "
     "cards of your library. Until the end of your next turn, you may cast an instant or "
     "sorcery spell from among those exiled cards."),
    # reveal-until is one free spell (cascade), not a look at N cards
    ("Wanda's Vision", "Enchantment", "Whenever you cast your second spell each turn, exile "
     "cards from the top of your library until you exile a nonland card. You may cast that "
     "card without paying its mana cost."),
    # discard a card to impulse one: a rummage, nets zero
    ("Chase Stein, Runaway", "Legendary Creature — Human Hero", "{T}, Discard a card: Exile the "
     "top card of your library. Until the end of your next turn, you may play that card."),
    # the permission is a separate static with its own condition
    ("Theater of Horrors", "Enchantment", "At the beginning of your upkeep, exile the top card "
     "of your library.\nDuring your turn, if an opponent lost life this turn, you may play lands "
     "and cast spells from among cards exiled with this enchantment."),
])
def test_impulse_near_misses(make_card, name, type_line, text):
    assert _impulse(make_card(name, type_line=type_line, oracle_text=text)) == (0, 0)


# --- none of it reaches the simulator ------------------------------------------------------

def test_role_only_fields_leave_the_sim_fields_alone(make_card):
    card = make_card("Semblance Anvil", mana_cost="{3}", type_line="Artifact",
                     oracle_text="Spells you cast that share a card type with the exiled card "
                     "cost {2} less to cast.")
    fx = tags.analyze(card)
    assert fx.ramp_sources == 0 and fx.spell_cost_reduction == 0   # tier0 / storm untouched


def test_every_role_has_a_target():
    """A role with no target reads as target 0, i.e. every card in it is over-supplied and a
    cut candidate — the new role must be calibrated, not defaulted."""
    probe = tags.EffectVector(
        ramp_sources=1, draw_cards=1, removal=1, noncreature_removal=True, board_wipe=True,
        counterspell=True, tutor=True, alt_win=True)
    assert set(redundancy.card_roles(probe)) <= set(redundancy.ROLE_TARGETS)
