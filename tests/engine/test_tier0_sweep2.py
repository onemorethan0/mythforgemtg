"""Second unmodeled-mechanics sweep in the goldfish sim (tier0 + sim/tier0_readers.py).

Reader gold sets use the real cards' printed text; the in-play tests check each mechanic moves
the clock the right way and that every point of damage / poison is still credited to a card."""
from __future__ import annotations

from mythgauntlet.sim import tier0_readers as R
from mythgauntlet.sim.tier0 import SimConfig, _effect_makers, simulate

CFG = SimConfig(turns=12, runs=150, seed=7)


# --- reader gold sets -------------------------------------------------------------------------

def test_var_power_gold():
    assert R.var_power("Ashaya, Soul of the Wild", "Legendary Creature — Elemental",
                       "Ashaya's power and toughness are each equal to the number of lands you "
                       "control.\nNontoken creatures you control are Forest lands in addition to "
                       "their other types.") == R.VarPower("land", 1)
    assert R.var_power("Kiyomaro, First to Stand", "Legendary Creature — Spirit",
                       "Kiyomaro's power and toughness are each equal to the number of cards in "
                       "your hand.") == R.VarPower("hand", 1)
    assert R.var_power("Nim Grotesque", "Creature — Zombie",
                       "This creature gets +1/+0 for each artifact you control.") == R.VarPower(
        "artifact", 1)
    # counts tier0 does not track are not read
    assert R.var_power("Avalanche of Sector 7", "Creature",
                       "Avalanche of Sector 7's power is equal to the number of artifacts your "
                       "opponents control.") is None
    assert R.var_power("Caller of the Hunt", "Creature",
                       "Caller of the Hunt's power and toughness are each equal to the number of "
                       "creatures of the chosen type on the battlefield.") is None


def test_enters_counters_gold():
    assert R.enters_counters("Kalonian Hydra", "Trample\nThis creature enters with four +1/+1 "
                             "counters on it.\nWhenever this creature attacks, double the number "
                             "of +1/+1 counters on each creature you control.") == (4, 0)
    assert R.enters_counters("Endless One", "This creature enters with X +1/+1 counters on "
                             "it.") == (0, 1)
    assert R.enters_counters("Skyclave Sentinel", "Kicker {1}{U}\nIf this creature was kicked, "
                             "it enters with two +1/+1 counters on it.") == (0, 0)
    assert R.enters_counters("Towering Titan", "This creature enters with X +1/+1 counters on "
                             "it, where X is the total toughness of other creatures you "
                             "control.") == (0, 0)


def test_sinks_gold():
    assert R.sinks("Shivan Dragon", "Flying\n{R}: This creature gets +1/+0 until end of "
                   "turn.") == (R.Sink("{r}", 1, False),)
    # once a turn, an extra rider, a tap cost: not read
    assert R.sinks("Azimaet Drake", "Flying\n{U}: This creature gets +1/+0 until end of turn. "
                   "Activate only once each turn.") == ()
    assert R.sinks("Stormcloud Djinn", "{R}{R}: This creature gets +2/+0 until end of turn and "
                   "deals 1 damage to you.") == ()
    assert R.sinks("Hangarback Walker", "{1}, {T}: Put a +1/+1 counter on this creature.") == ()
    assert R.sinks("Restless Apparition", "{W/B}{W/B}{W/B}: This creature gets +3/+3 until end "
                   "of turn.") == (R.Sink("{w/b}{w/b}{w/b}", 3, False),)


def test_replacements_gold():
    assert R.token_doubler("Anointed Procession", "If an effect would create one or more tokens "
                           "under your control, it creates twice that many of those tokens "
                           "instead.") == "all"
    assert R.token_doubler("Kaya, Geist Hunter", "−2: Until end of turn, if one or more tokens "
                           "would be created under your control, twice that many of those "
                           "tokens are created instead.") is None
    assert R.counter_mod("Hardened Scales", "If one or more +1/+1 counters would be put on a "
                         "creature you control, that many plus one +1/+1 counters are put on it "
                         "instead.") == "plus"
    assert R.counter_mod("Doubling Season", "If an effect would create one or more tokens under "
                         "your control, it creates twice that many of those tokens instead.\nIf "
                         "an effect would put one or more counters on a permanent you control, "
                         "it puts twice that many of those counters on that permanent "
                         "instead.") == "twice"
    assert R.counter_mod("Mauhúr, Uruk-hai Captain", "If one or more +1/+1 counters would be put "
                         "on an Army, Goblin, or Orc you control, that many plus one +1/+1 "
                         "counters are put on it instead.") is None


def test_extra_combat_gold():
    assert R.extra_combat("Relentless Assault", "Sorcery", "Untap all creatures that attacked "
                          "this turn. After this main phase, there is an additional combat "
                          "phase followed by an additional main phase.") == "spell"
    assert R.extra_combat("Aurelia, the Warleader", "Legendary Creature — Angel",
                          "Flying, vigilance, haste\nWhenever Aurelia attacks for the first time "
                          "each turn, untap all creatures you control. After this phase, there "
                          "is an additional combat phase.") == "attack"
    # an activated extra combat and one with no untap are not read
    assert R.extra_combat("Aggravated Assault", "Enchantment", "{3}{R}{R}: Untap all creatures "
                          "you control. After this main phase, there is an additional combat "
                          "phase followed by an additional main phase. Activate only as a "
                          "sorcery.") is None
    assert R.extra_combat("All-Out Assault", "Enchantment", "When this enchantment enters, if "
                          "it's your main phase, there is an additional combat phase after this "
                          "phase followed by an additional main phase.") is None


def test_life_and_death_gold():
    assert R.gain_drain("Sanguine Bond", "Whenever you gain life, target opponent loses that "
                        "much life.") == 0
    assert R.gain_drain("Starscape Cleric", "Whenever you gain life, each opponent loses 1 "
                        "life.") == 1
    assert R.death_drain("Zulaport Cutthroat", "Whenever this creature or another creature you "
                         "control dies, each opponent loses 1 life and you gain 1 life.") == 1
    assert R.death_drain("Blood Artist", "Whenever this creature or another creature dies, "
                         "target player loses 1 life and you gain 1 life.") == 1
    assert R.death_drain("Boggart Mischief", "Whenever a Goblin creature you control dies, each "
                         "opponent loses 1 life and you gain 1 life.") == 0
    assert R.free_sac_outlet("Viscera Seer", "Sacrifice a creature: Scry 1.")
    assert not R.free_sac_outlet("Gobbling Ooze", "{G}, Sacrifice another creature: Put a +1/+1 "
                                 "counter on this creature.")
    # a fixed life gain is read as an effect (it only matters to a gain_drain payoff)
    assert [(e.kind, e.amount) for e in _effect_makers(
        "Healer", "Creature", "When this creature enters, you gain 3 life.")] == [("gain", 3)]


def test_misc_gold():
    assert R.is_clone("Clone", "Creature — Shapeshifter",
                      "You may have this creature enter as a copy of any creature on the "
                      "battlefield.")
    assert not R.is_clone("Sculpting Steel", "Artifact", "You may have this artifact enter as a "
                          "copy of any artifact on the battlefield.")
    assert R.one_shot_mana("Lotus Petal", "{T}, Sacrifice this artifact: Add one mana of any "
                           "color.") == 1
    assert R.one_shot_mana("Chromatic Sphere", "{1}, {T}, Sacrifice this artifact: Add one mana "
                           "of any color. Draw a card.") == 0
    assert R.aura_ramp("Utopia Sprawl", "Enchantment — Aura",
                       "Enchant Forest\nAs this Aura enters, choose a color.\nWhenever enchanted "
                       "Forest is tapped for mana, its controller adds an additional one mana of "
                       "the chosen color.") == (1, frozenset("WUBRG"))
    assert R.aura_ramp("Overgrowth", "Enchantment — Aura", "Enchant land\nWhenever enchanted "
                       "land is tapped for mana, its controller adds an additional {G}{G}.") == (
        2, frozenset("G"))
    assert R.var_draw("Collective Unconscious", "Sorcery",
                      "Draw a card for each creature you control.") == "creature"
    assert R.affinity_artifacts("Frogmite", "Affinity for artifacts (This spell costs {1} less "
                                "to cast for each artifact you control.)")
    assert R.flashback_cost("Lingering Souls", "Sorcery", "Create two 1/1 white Spirit creature "
                            "tokens with flying.\nFlashback {1}{B}") == "{1}{b}"
    assert R.flashback_cost("Deep Analysis", "Sorcery", "Target player draws two cards.\n"
                            "Flashback—{1}{U}, Pay 3 life.") is None
    assert R.cascade("Bloodbraid Elf", "Haste\nCascade (When you cast this spell, ...)") == 1
    assert R.prowess("Monastery Swiftspear", "Haste\nProwess (Whenever you cast ...)") == 1
    assert R.exalted("Rafiq of the Many", "Exalted (Whenever a creature ...)\nWhenever a "
                     "creature you control attacks alone, it gains double strike until end of "
                     "turn.") == 1
    assert R.extort("Basilica Guards", "Defender\nExtort (Whenever you cast a spell, ...)") == 1
    assert R.convoke("Conclave Tribunal", "Convoke (Your creatures can help ...)\nWhen this "
                     "enchantment enters, exile target nonland permanent.")


# --- in play ----------------------------------------------------------------------------------

def _land(make_card, color="G", name=None):
    names = {"G": "Forest", "R": "Mountain", "B": "Swamp", "W": "Plains", "U": "Island"}
    n = name or names[color]
    return make_card(n, type_line=f"Basic Land — {n}", produced_mana=(color,),
                     color_identity=(color,))


def _creature(make_card, name, cost, power, text="", tl="Creature — Beast"):
    c = make_card(name, mana_cost=cost, type_line=tl, oracle_text=text)
    c.power, c.toughness = str(power), str(power) if power != "*" else "*"
    if power == "0":
        c.toughness = "0"
    return c


def _sums(runs):
    for r in runs:
        total = r.damage_by_turn[-1] if r.damage_by_turn else 0
        assert sum(r.damage_by_card.values()) == total
        assert sum(r.damage_by_source.values()) == total
        assert sum(r.poison_by_card.values()) == (r.poison_by_turn[-1] if r.poison_by_turn else 0)


def _dealt(runs, name):
    return sum(r.damage_by_card.get(name, 0) for r in runs)


def _total(runs):
    return sum(r.damage_by_turn[-1] for r in runs)


def test_var_power_creature_attacks_for_its_count(make_card):
    ash = _creature(make_card, "Landbeast", "{2}{G}", "*",
                    "Landbeast's power and toughness are each equal to the number of lands you "
                    "control.")
    runs = simulate([(_land(make_card), 45), (ash, 54)], None, CFG)
    _sums(runs)
    assert _dealt(runs, "Landbeast") > 0


def test_hydra_cast_with_x_and_counters(make_card):
    hydra = _creature(make_card, "Ooze X", "{X}{G}", "0",
                      "This creature enters with X +1/+1 counters on it.")
    runs = simulate([(_land(make_card), 45), (hydra, 54)], None, CFG)
    _sums(runs)
    assert _dealt(runs, "Ooze X") > 0
    scales = make_card("Scales", mana_cost="{G}", type_line="Enchantment",
                       oracle_text="If one or more +1/+1 counters would be put on a creature you "
                                   "control, that many plus one +1/+1 counters are put on it "
                                   "instead.")
    with_s = simulate([(_land(make_card), 45), (hydra, 44), (scales, 10)], None, CFG)
    _sums(with_s)
    dud = make_card("Scales", mana_cost="{G}", type_line="Enchantment")
    without = simulate([(_land(make_card), 45), (hydra, 44), (dud, 10)], None, CFG)
    assert _dealt(with_s, "Ooze X") > _dealt(without, "Ooze X")


def test_firebreathing_spends_spare_mana(make_card):
    breather = _creature(make_card, "Breather", "{1}{R}", 1,
                         "{R}: This creature gets +1/+0 until end of turn.")
    plain = _creature(make_card, "Breather", "{1}{R}", 1)
    w = simulate([(_land(make_card, "R"), 60), (breather, 39)], None, CFG)
    wo = simulate([(_land(make_card, "R"), 60), (plain, 39)], None, CFG)
    _sums(w)
    assert _total(w) > _total(wo)


def test_prowess_and_exalted(make_card):
    monk = _creature(make_card, "Monk", "{R}", 1, "Prowess")
    bolt = make_card("Spark", mana_cost="{R}", type_line="Instant", oracle_text="Scry 1.")
    w = simulate([(_land(make_card, "R"), 45), (monk, 1), (bolt, 53)], None, CFG)
    plain = _creature(make_card, "Monk", "{R}", 1)
    wo = simulate([(_land(make_card, "R"), 45), (plain, 1), (bolt, 53)], None, CFG)
    _sums(w)
    assert _dealt(w, "Monk") > _dealt(wo, "Monk")
    knight = _creature(make_card, "Knight", "{3}{W}", 3)
    ex = make_card("Exalter", mana_cost="{W}", type_line="Enchantment", oracle_text="Exalted")
    dud = make_card("Exalter", mana_cost="{W}", type_line="Enchantment")
    w = simulate([(_land(make_card, "W"), 45), (knight, 1), (ex, 53)], None, CFG)
    wo = simulate([(_land(make_card, "W"), 45), (knight, 1), (dud, 53)], None, CFG)
    _sums(w)
    assert _dealt(w, "Knight") > _dealt(wo, "Knight")


def test_token_doubler(make_card):
    maker = make_card("Spirits", mana_cost="{2}{W}", type_line="Sorcery",
                      oracle_text="Create two 1/1 white Spirit creature tokens with flying.")
    proc = make_card("Procession", mana_cost="{3}{W}", type_line="Enchantment",
                     oracle_text="If an effect would create one or more tokens under your "
                                 "control, it creates twice that many of those tokens instead.")
    dud = make_card("Procession", mana_cost="{3}{W}", type_line="Enchantment")
    w = simulate([(_land(make_card, "W"), 45), (maker, 44), (proc, 10)], None, CFG)
    wo = simulate([(_land(make_card, "W"), 45), (maker, 44), (dud, 10)], None, CFG)
    _sums(w)
    assert _dealt(w, "Spirits token") > _dealt(wo, "Spirits token")


def test_flashback_recasts_from_graveyard(make_card):
    souls = make_card("Souls", mana_cost="{2}{W}", type_line="Sorcery",
                      oracle_text="Create two 1/1 white Spirit creature tokens with flying.\n"
                                  "Flashback {1}{W}")
    plain = make_card("Souls", mana_cost="{2}{W}", type_line="Sorcery",
                      oracle_text="Create two 1/1 white Spirit creature tokens with flying.")
    w = simulate([(_land(make_card, "W"), 50), (souls, 4)], None, CFG)
    wo = simulate([(_land(make_card, "W"), 50), (plain, 4)], None, CFG)
    _sums(w)
    assert sum(r.spells_cast for r in w) > sum(r.spells_cast for r in wo)


def test_cascade_casts_a_cheaper_spell_free(make_card):
    elf = _creature(make_card, "Cascader", "{3}{G}", 3, "Cascade")
    plain = _creature(make_card, "Cascader", "{3}{G}", 3)
    bear = _creature(make_card, "Bear", "{1}{G}", 2)
    w = simulate([(_land(make_card), 40), (elf, 20), (bear, 39)], None, CFG)
    wo = simulate([(_land(make_card), 40), (plain, 20), (bear, 39)], None, CFG)
    _sums(w)
    assert sum(r.spells_cast for r in w) > sum(r.spells_cast for r in wo)


def test_extra_combat_doubles_the_swing(make_card):
    bear = _creature(make_card, "Bear", "{1}{R}", 2)
    assault = make_card("Assault", mana_cost="{2}{R}{R}", type_line="Sorcery",
                        oracle_text="Untap all creatures that attacked this turn. After this "
                                    "main phase, there is an additional combat phase followed "
                                    "by an additional main phase.")
    dud = make_card("Assault", mana_cost="{2}{R}{R}", type_line="Sorcery", oracle_text="Scry 1.")
    w = simulate([(_land(make_card, "R"), 45), (bear, 40), (assault, 14)], None, CFG)
    wo = simulate([(_land(make_card, "R"), 45), (bear, 40), (dud, 14)], None, CFG)
    _sums(w)
    assert _dealt(w, "Bear") > _dealt(wo, "Bear")


def test_lifelink_into_sanguine_bond(make_card):
    lifer = _creature(make_card, "Lifer", "{1}{B}", 2, "Lifelink")
    bond = make_card("Bond", mana_cost="{3}{B}{B}", type_line="Enchantment",
                     oracle_text="Whenever you gain life, target opponent loses that much life.")
    runs = simulate([(_land(make_card, "B"), 45), (lifer, 44), (bond, 10)], None, CFG)
    _sums(runs)
    assert _dealt(runs, "Bond") > 0


def test_extort_and_aristocrats_finisher(make_card):
    guard = _creature(make_card, "Guard", "{2}{B}", 1, "Defender\nExtort")
    filler = make_card("Filler", mana_cost="{B}", type_line="Sorcery", oracle_text="Scry 1.")
    runs = simulate([(_land(make_card, "B"), 45), (guard, 20), (filler, 34)], None, CFG)
    _sums(runs)
    assert _dealt(runs, "Guard") > 0
    seer = _creature(make_card, "Seer", "{B}", 1, "Sacrifice a creature: Scry 1.")
    artist = _creature(make_card, "Artist", "{1}{B}", 0,
                       "Whenever this creature or another creature dies, target player loses 1 "
                       "life and you gain 1 life.")
    artist.toughness = "1"
    token = make_card("Fodder", mana_cost="{1}{B}", type_line="Sorcery",
                      oracle_text="Create three 1/1 black Rat creature tokens.")
    runs = simulate([(_land(make_card, "B"), 40), (seer, 10), (artist, 10), (token, 39)],
                    None, SimConfig(turns=14, runs=150, seed=7))
    _sums(runs)
    assert _dealt(runs, "Artist") > 0


def test_clone_and_affinity_and_petal(make_card):
    big = _creature(make_card, "Big", "{4}{U}", 6)
    clone = _creature(make_card, "Copier", "{3}{U}", "0",
                      "You may have this creature enter as a copy of any creature on the "
                      "battlefield.")
    runs = simulate([(_land(make_card, "U"), 45), (big, 20), (clone, 34)], None, CFG)
    _sums(runs)
    assert _dealt(runs, "Copier") > 0
    rock = make_card("Bauble", mana_cost="{0}", type_line="Artifact", oracle_text="Scry 1.")
    frog = make_card("Frog", mana_cost="{4}", type_line="Artifact Creature — Frog",
                     oracle_text="Affinity for artifacts")
    frog.power, frog.toughness = "2", "2"
    plain = make_card("Frog", mana_cost="{4}", type_line="Artifact Creature — Frog")
    plain.power, plain.toughness = "2", "2"
    w = simulate([(_land(make_card, "U"), 40), (rock, 30), (frog, 29)], None, CFG)
    wo = simulate([(_land(make_card, "U"), 40), (rock, 30), (plain, 29)], None, CFG)
    _sums(w)
    first = lambda rs: sum(r.played_turn.get("Frog", 99) for r in rs)  # noqa: E731
    assert first(w) < first(wo)


def test_board_wipe_runs_stay_consistent(make_card):
    """Every new pool is taken off the board by a wipe without breaking the attribution sums."""
    hydra = _creature(make_card, "Ooze X", "{X}{G}", "0",
                      "This creature enters with X +1/+1 counters on it.")
    breather = _creature(make_card, "Breather", "{1}{G}", 1,
                         "{G}: Put a +1/+1 counter on this creature.")
    lifer = _creature(make_card, "Lifer", "{1}{G}", 2, "Lifelink\nExalted")
    runs = simulate([(_land(make_card), 45), (hydra, 18), (breather, 18), (lifer, 18)], None,
                    CFG, board_wipe_turn=6)
    _sums(runs)


# --- third sweep ------------------------------------------------------------------------------

def test_sweep3_readers_gold():
    assert R.haste_gear("Lightning Greaves", "Artifact — Equipment",
                        "Equipped creature has haste and shroud.\nEquip {0}") == "{0}"
    assert R.haste_gear("Swiftfoot Boots", "Artifact — Equipment",
                        "Equipped creature has hexproof and haste.\nEquip {1}") == "{1}"
    assert R.haste_gear("Loxodon Warhammer", "Artifact — Equipment",
                        "Equipped creature gets +3/+0 and has trample and lifelink.\n"
                        "Equip {3}") is None
    assert R.team_haste("Fires of Yavimaya", "Creatures you control have haste.\nSacrifice "
                        "Fires of Yavimaya: Target creature gets +2/+2 until end of turn.") == "all"
    assert R.team_haste("Regisaur Alpha", "Other Dinosaurs you control have haste.") is None
    assert R.storm("Grapeshot", "Grapeshot deals 1 damage to any target.\nStorm") == 1
    assert R.storm_damage("Grapeshot", "Grapeshot deals 1 damage to any target.\nStorm") == 1
    assert R.pump_spell("Giant Growth", "Instant",
                        "Target creature gets +3/+3 until end of turn.") == 3
    assert R.pump_spell("Untamed Might", "Instant",
                        "Target creature gets +X/+X until end of turn.") == 0
    assert R.pump_spell("Take Heart", "Instant", "Target creature gets +2/+2 until end of turn. "
                        "You gain 1 life for each attacking creature you control.") == 0
    assert R.fabricate("Marionette Master", "Fabricate 3\nWhenever an artifact you control is "
                       "put into a graveyard from the battlefield, target opponent loses life "
                       "equal to Marionette Master's power.") == 3
    assert R.living_weapon("Batterskull", "Living weapon\nEquipped creature gets +4/+4 and has "
                           "vigilance and lifelink.\n{3}: Return Batterskull to its owner's "
                           "hand.\nEquip {5}")
    assert R.combat_counter("Luminarch Aspirant", "At the beginning of combat on your turn, put "
                            "a +1/+1 counter on target creature you control.") == 1
    assert R.sinks("Fleecemane Lion", "{3}{G}{W}: Monstrosity 1.\nAs long as Fleecemane Lion is "
                   "monstrous, it has hexproof and indestructible.") == (
        R.Sink("{3}{g}{w}", 1, True, True),)


def test_haste_gear_and_team_haste_speed_the_clock(make_card):
    beast = _creature(make_card, "Beast", "{3}{R}", 4)
    greaves = make_card("Greaves", mana_cost="{2}", type_line="Artifact — Equipment",
                        oracle_text="Equipped creature has haste and shroud.\nEquip {0}")
    dud = make_card("Greaves", mana_cost="{2}", type_line="Artifact — Equipment",
                    oracle_text="Equipped creature has shroud.\nEquip {0}")
    w = simulate([(_land(make_card, "R"), 42), (beast, 47), (greaves, 10)], None, CFG)
    wo = simulate([(_land(make_card, "R"), 42), (beast, 47), (dud, 10)], None, CFG)
    _sums(w)
    assert _total(w) > _total(wo)
    fires = make_card("Fires", mana_cost="{1}{R}", type_line="Enchantment",
                      oracle_text="Creatures you control have haste.")
    w = simulate([(_land(make_card, "R"), 42), (beast, 47), (fires, 10)], None, CFG)
    _sums(w)
    assert _total(w) > _total(wo)


def test_storm_copies_and_pump_spells(make_card):
    shot = make_card("Shot", mana_cost="{1}{R}", type_line="Sorcery",
                     oracle_text="Shot deals 1 damage to any target.\nStorm")
    ritual = make_card("Ritual", mana_cost="{R}", type_line="Instant", oracle_text="Scry 1.")
    runs = simulate([(_land(make_card, "R"), 40), (shot, 20), (ritual, 39)], None, CFG)
    _sums(runs)
    assert _dealt(runs, "Shot") > 0
    bear = _creature(make_card, "Bear", "{1}{G}", 2)
    growth = make_card("Growth", mana_cost="{G}", type_line="Instant",
                       oracle_text="Target creature gets +3/+3 until end of turn.")
    dud = make_card("Growth", mana_cost="{G}", type_line="Instant", oracle_text="Scry 1.")
    w = simulate([(_land(make_card), 45), (bear, 34), (growth, 20)], None, CFG)
    wo = simulate([(_land(make_card), 45), (bear, 34), (dud, 20)], None, CFG)
    _sums(w)
    assert _dealt(w, "Bear") > _dealt(wo, "Bear")


def test_living_weapon_monstrosity_and_combat_counters(make_card):
    skull = make_card("Skull", mana_cost="{5}", type_line="Artifact — Equipment",
                      oracle_text="Living weapon\nEquipped creature gets +4/+4 and has "
                                  "vigilance and lifelink.\nEquip {5}")
    runs = simulate([(_land(make_card), 45), (skull, 54)], None, CFG)
    _sums(runs)
    assert _dealt(runs, "Skull") > 0
    lion = _creature(make_card, "Lion", "{1}{G}", 3, "{3}{G}: Monstrosity 2.")
    plain = _creature(make_card, "Lion", "{1}{G}", 3)
    w = simulate([(_land(make_card), 55), (lion, 44)], None, CFG)
    wo = simulate([(_land(make_card), 55), (plain, 44)], None, CFG)
    _sums(w)
    assert _dealt(w, "Lion") > _dealt(wo, "Lion")
    asp = _creature(make_card, "Aspirant", "{1}{W}", 1,
                    "At the beginning of combat on your turn, put a +1/+1 counter on target "
                    "creature you control.")
    plain = _creature(make_card, "Aspirant", "{1}{W}", 1)
    w = simulate([(_land(make_card, "W"), 45), (asp, 54)], None, CFG)
    wo = simulate([(_land(make_card, "W"), 45), (plain, 54)], None, CFG)
    _sums(w)
    assert _total(w) > _total(wo)


def test_commander_growth_survives_removal_bookkeeping(make_card):
    """A commander that grew (+1/+1 counters, monstrosity) and is then answered and recast keeps
    the board-power pool consistent: the horizon board is never negative."""
    from mythgauntlet.sim.tier0 import simulate as sim
    cmd = _creature(make_card, "Boss", "{1}{G}", 2, "{G}: Put a +1/+1 counter on this creature.",
                    tl="Legendary Creature — Beast")
    deck = [(_land(make_card), 45), (_creature(make_card, "Bear", "{1}{G}", 2), 54)]
    for runs in (sim(deck, cmd, CFG, commander_removals=2),
                 sim(deck, cmd, CFG, board_wipe_turn=6),
                 sim(deck, cmd, CFG, board_wipe_turn=6, commander_survives_wipe=True)):
        _sums(runs)
        assert all(r.final_board_power >= 0 for r in runs)
        assert all(min(r.board_power_by_turn) >= 0 for r in runs)


def test_typed_lords_gold_and_in_play(make_card):
    """Type-restricted anthems (2026-11-09 mentor review: Tempered Steel and Locutus read as
    do-nothing cards in a Borg Queen deck, so Advise cut them and the verdicts called them weak)."""
    (steel,) = R.typed_anthems("Tempered Steel", "Artifact creatures you control get +2/+2.")
    assert (steel.kind, steel.power, steel.others) == ("artifact", 2, False)
    assert R.type_matches(steel, "Artifact Creature — Construct")
    assert not R.type_matches(steel, "Creature — Bear")
    (champ,) = R.typed_anthems("Elvish Champion", "Other Elves you control get +1/+1 and have "
                               "forestwalk.")
    assert champ.others and R.type_matches(champ, "Creature — Elf Warrior")
    assert R.type_matches(champ, "Creature — Shapeshifter", keywords=("Changeling",))
    (mik,) = R.typed_anthems("Mikaeus, the Unhallowed", "Other non-Human creatures you control "
                             "get +1/+1.")
    assert R.type_matches(mik, "Creature — Zombie") and not R.type_matches(mik, "Creature — Human")
    assert R.typed_anthems("Glorious Anthem", "Creatures you control get +1/+1.") == ()
    assert R.typed_anthems("Balefire Liege", "Other red creatures you control get +1/+1.") == ()
    assert R.typed_anthems("Wanderglyph", "Other artifact creatures you control get +2/+2 as long "
                           "as you have the city's blessing.") == ()

    golem = make_card("Golem", mana_cost="{2}", type_line="Artifact Creature — Golem")
    golem.power, golem.toughness = "2", "2"
    steel_c = make_card("Steel", mana_cost="{1}{W}{W}", type_line="Enchantment",
                        oracle_text="Artifact creatures you control get +2/+2.")
    dud = make_card("Steel", mana_cost="{1}{W}{W}", type_line="Enchantment")
    w = simulate([(_land(make_card, "W"), 45), (golem, 44), (steel_c, 10)], None, CFG)
    wo = simulate([(_land(make_card, "W"), 45), (golem, 44), (dud, 10)], None, CFG)
    _sums(w)
    assert _total(w) > _total(wo)


def test_creature_mana_grants_replicate_and_charge_engines(make_card):
    """2026-11-10 (owner's Borg Queen deck): Ambulatory Reactor-class grants let able artifact
    creatures tap for mana (and sit out combat), Hugh's replicate copies an artifact spell from
    spare mana, Maturation Chamber turns its counters into tokens."""
    assert R.creature_mana("Ambulatory Reactor", 'Artifact creatures you control have "{T}: '
                           'Add {C}. Spend this mana only to cast an artifact spell or activate '
                           'an ability of an artifact source."') == R.CreatureMana(
        "artifact_creatures", 1, True)
    assert R.creature_mana("Cryptolith Rite", 'Creatures you control have "{T}: Add one mana of '
                           'any color."') == R.CreatureMana("creatures", 1, False)
    assert R.creature_mana("Sorcerer Class", 'Creatures you control have "{T}: Add {U} or {R}. '
                           'Spend this mana only to cast an instant or sorcery spell or to gain '
                           'a Class level."') is None
    assert R.replicate_grant("Hugh, First of Many", "Artifact spells you cast have replicate "
                             "{2}{U}.") == "{2}{u}"
    assert R.charge_engine("Maturation Chamber", "Whenever you cast an artifact spell, put a "
                           "charge counter on this artifact.\n{4}, {T}: Create a 1/1 colorless "
                           "Borg artifact creature token for each charge counter on this "
                           "artifact. Activate only as a sorcery.") == R.ChargeEngine(
        "artifact", "{4}", 1, True, True)

    drone = make_card("Drone", mana_cost="{2}", type_line="Artifact Creature — Construct")
    drone.power, drone.toughness = "1", "1"
    golem = make_card("Golem", mana_cost="{7}", type_line="Artifact Creature — Golem")
    golem.power, golem.toughness = "9", "9"
    reactor = make_card("Reactor", mana_cost="{1}{U}", type_line="Artifact Creature — Borg",
                        oracle_text='Artifact creatures you control have "{T}: Add {C}. Spend '
                                    'this mana only to cast an artifact spell or activate an '
                                    'ability of an artifact source."')
    reactor.power, reactor.toughness = "1", "1"
    plain = make_card("Reactor", mana_cost="{1}{U}", type_line="Artifact Creature — Borg")
    plain.power, plain.toughness = "1", "1"
    first = lambda rs: sum(r.played_turn.get("Golem", 99) for r in rs)  # noqa: E731
    w = simulate([(_land(make_card, "U"), 38), (drone, 30), (golem, 20), (reactor, 11)], None, CFG)
    wo = simulate([(_land(make_card, "U"), 38), (drone, 30), (golem, 20), (plain, 11)], None, CFG)
    _sums(w)
    assert first(w) < first(wo)                        # the 7-drop comes down sooner

    chamber = make_card("Chamber", mana_cost="{1}{U}", type_line="Artifact",
                        oracle_text="Whenever you cast an artifact spell, put a charge counter "
                                    "on this artifact.\n{4}, {T}: Create a 1/1 colorless Borg "
                                    "artifact creature token for each charge counter on this "
                                    "artifact. Activate only as a sorcery.")
    runs = simulate([(_land(make_card, "U"), 45), (drone, 44), (chamber, 10)], None, CFG)
    _sums(runs)
    assert _dealt(runs, "Chamber token") > 0


def test_owner_deck_engines(make_card):
    """2026-11-10, from the owner's saved decks: granted combat-damage triggers (Locutus of Borg),
    'choose a creature type' cards read for the deck's own most common type, every-turn modal
    engines (Black Market Connections), Helm of the Host, and a bought extra combat."""
    assert R.granted_hit("Locutus of Borg", 'Lifelink\nArtifact creatures you control have '
                         '"Whenever this creature deals combat damage to a player, create a 1/1 '
                         'colorless Borg artifact creature token."') == R.GrantedHit(
        "artifact_creatures", "token", 1, "colorless borg artifact")
    assert R.chosen_type("Patchwork Banner", "As this artifact enters, choose a creature type.\n"
                         "Creatures you control of the chosen type get +1/+1.\n{T}: Add one mana "
                         "of any color.") == R.ChosenType("anthem", 1)
    assert R.main_phase_modes("Black Market Connections", "At the beginning of your first main "
                              "phase, choose one or more —\n• Sell Contraband — Create a Treasure "
                              "token. You lose 1 life.\n• Buy Information — Draw a card. You lose "
                              "2 life.\n• Hire a Mercenary — Create a 3/2 colorless Shapeshifter "
                              "creature token with changeling. You lose 3 life.") == (
        ("treasure", 1), ("draw", 1), ("token", 1, 3, "colorless shapeshifter"))
    assert R.bought_combat("Aggravated Assault", "{3}{R}{R}: Untap all creatures you control. "
                           "After this main phase, there is an additional combat phase followed "
                           "by an additional main phase. Activate only as a sorcery.") == "{3}{r}{r}"

    drone = make_card("Drone", mana_cost="{2}", type_line="Artifact Creature — Borg")
    drone.power, drone.toughness = "2", "2"
    locutus = make_card("Collective", mana_cost="{1}{U}", type_line="Artifact Creature — Borg",
                        oracle_text='Artifact creatures you control have "Whenever this creature '
                                    'deals combat damage to a player, create a 1/1 colorless '
                                    'Borg artifact creature token."')
    locutus.power, locutus.toughness = "1", "1"
    w = simulate([(_land(make_card, "U"), 45), (drone, 44), (locutus, 10)], None, CFG)
    _sums(w)
    assert _dealt(w, "Collective token") > 0

    elf = _creature(make_card, "Elf", "{1}{G}", 1, tl="Creature — Elf Warrior")
    banner = make_card("Banner", mana_cost="{3}", type_line="Artifact",
                       oracle_text="As this artifact enters, choose a creature type.\n"
                                   "Creatures you control of the chosen type get +1/+1.")
    dud = make_card("Banner", mana_cost="{3}", type_line="Artifact")
    w = simulate([(_land(make_card), 45), (elf, 44), (banner, 10)], None, CFG)
    wo = simulate([(_land(make_card), 45), (elf, 44), (dud, 10)], None, CFG)
    _sums(w)
    assert _dealt(w, "Elf") > _dealt(wo, "Elf")

    bmc = make_card("Connections", mana_cost="{2}{B}", type_line="Enchantment",
                    oracle_text="At the beginning of your first main phase, choose one or more "
                                "—\n• Sell Contraband — Create a Treasure token. You lose 1 life.\n"
                                "• Hire a Mercenary — Create a 3/2 colorless Shapeshifter "
                                "creature token with changeling. You lose 3 life.")
    runs = simulate([(_land(make_card, "B"), 45), (bmc, 54)], None, CFG)
    _sums(runs)
    assert _dealt(runs, "Connections token") > 0
