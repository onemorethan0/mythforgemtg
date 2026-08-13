"""Gold-set tests for collection_pool's local role classification.

Strict "build only from cards I own" has no Scryfall search, so these classifications ARE
the deck. Every fixture below carries VERBATIM Scryfall oracle text — retyping it from
memory is how a classifier ends up tuned to text that does not exist.

Deliberately self-contained: no data/ directory, no network. CI runs with neither.

Each case here pins a regression that actually shipped and was caught in review:
  * "Draw two cards" — oracle text spells card counts as WORDS; a \\d+ pattern
    silently dropped Seize the Spoils, Laughing Mad and Dangerous Wager.
  * "{1}, {T}: Add {B}" — nets ZERO mana. A broad "{T}: Add {" pattern matched the
    substring inside it and returned ramp before the net-mana gate could reject it.
  * Blasphemous Act says "each creature" — SINGULAR, twice. A "creatures" plural gate
    blocked the very wipe patterns it wrapped.
  * Lightning Bolt deals damage "to any target", not "to target".
  * Smaug HAS indestructible; that protects only itself, and is not a protection slot.
  * Painful Truths draws "X cards"; X is unknown but positive, not zero.
"""
import collection_pool as cp


def card(name, text, type_line="Sorcery", **kw):
    c = {"name": name, "oracle_text": text, "type_line": type_line,
         "color_identity": kw.pop("ci", []), "legalities": {"commander": "legal"}}
    c.update(kw)
    return c


# (fixture, roles that MUST be present, roles that MUST NOT be present)
GOLD = [
    (card("Sol Ring", "{T}: Add {C}{C}.", "Artifact"), {"ramp"}, {"draw", "wipe"}),
    (card("Arcane Signet",
          "{T}: Add one mana of any color in your commander's color identity.",
          "Artifact"), {"ramp"}, set()),
    (card("Springleaf Drum",
          "{T}, Tap an untapped creature you control: Add one mana of any color.",
          "Artifact"), {"ramp"}, set()),
    (card("Mind Stone",
          "{T}: Add {C}.\n{1}, {T}, Sacrifice this artifact: Draw a card.",
          "Artifact"), {"ramp", "draw"}, {"wipe"}),
    (card("Blasphemous Act",
          "This spell costs {1} less to cast for each creature on the battlefield.\n"
          "Blasphemous Act deals 13 damage to each creature."),
     {"wipe"}, {"removal", "ramp"}),
    (card("Vandalblast",
          "Destroy target artifact you don't control.\n"
          "Overload {4}{R} (You may cast this spell for its overload cost. If you do, "
          "change \"target\" in its text to \"each.\")"), {"removal"}, {"wipe"}),
    (card("Rest in Peace",
          "When this enchantment enters, exile all graveyards.\n"
          "If a card or token would be put into a graveyard from anywhere, exile it "
          "instead.", "Enchantment"), set(), {"wipe", "removal"}),
    (card("Toxic Deluge",
          "As an additional cost to cast this spell, pay X life.\n"
          "All creatures get -X/-X until end of turn."), {"wipe"}, set()),
    (card("Lightning Bolt", "Lightning Bolt deals 3 damage to any target.", "Instant"),
     {"removal"}, {"wipe"}),
    (card("Chaos Warp",
          "The owner of target permanent shuffles it into their library, then reveals "
          "the top card of their library. If it's a permanent card, they put it onto "
          "the battlefield.", "Instant"), {"removal"}, {"wipe"}),
    (card("Phyrexian Arena",
          "At the beginning of your upkeep, you draw a card and you lose 1 life.",
          "Enchantment"), {"draw"}, set()),
    (card("Painful Truths",
          "Converge — You draw X cards and lose X life, where X is the number of colors "
          "of mana spent to cast this spell."), {"draw"}, set()),
    (card("Seize the Spoils",
          "As an additional cost to cast this spell, discard a card.\n"
          "Draw two cards and create a Treasure token."), {"draw", "ramp"}, set()),
    (card("Laughing Mad",
          "As an additional cost to cast this spell, discard a card.\n"
          "Draw two cards.", "Instant"), {"draw"}, set()),
    (card("Dangerous Wager", "Discard your hand, then draw two cards.", "Instant"),
     {"draw"}, set()),
    (card("Darksteel Plate",
          "Indestructible\nEquipped creature has indestructible.\nEquip {2}",
          "Artifact — Equipment"), {"protection"}, set()),
    (card("Lightning Greaves",
          "Equipped creature has haste and shroud.\nEquip {0}",
          "Artifact — Equipment"), {"protection"}, set()),
    (card("Smaug the Impenetrable",
          "Flying, indestructible, haste\n"
          "Whenever Smaug is dealt noncombat damage, create that many Treasure tokens.",
          "Legendary Creature — Dragon"), {"ramp"}, {"protection"}),
    (card("Berserkers' Onslaught",
          "Attacking creatures you control have double strike.", "Enchantment"),
     {"finisher"}, set()),
    (card("Hellkite Tyrant",
          "Flying, trample\nWhenever this creature deals combat damage to a player, gain "
          "control of all artifacts that player controls.\nAt the beginning of your "
          "upkeep, if you control twenty or more artifacts, you win the game.",
          "Creature — Dragon"), {"finisher"}, set()),
    (card("Mana Geyser", "Add {R} for each tapped land your opponents control."),
     {"ramp"}, set()),
    (card("Wayfarer's Bauble",
          "{2}, {T}, Sacrifice this artifact: Search your library for a basic land card, "
          "put that card onto the battlefield tapped, then shuffle.", "Artifact"),
     {"ramp"}, {"draw"}),
    (card("Solemn Simulacrum",
          "When this creature enters, you may search your library for a basic land card, "
          "put that card onto the battlefield tapped, then shuffle.\n"
          "When this creature dies, you may draw a card.",
          "Artifact Creature — Golem"), {"ramp", "draw"}, set()),
    (card("Command Tower",
          "{T}: Add one mana of any color in your commander's color identity.", "Land"),
     {"ramp"}, set()),
]


def test_gold_set():
    failures = []
    for c, must, must_not in GOLD:
        got = cp.classify(c)
        if (must - got) or (must_not & got):
            failures.append(f"{c['name']}: got {sorted(got)}, "
                            f"missing {sorted(must - got)}, "
                            f"wrongly tagged {sorted(must_not & got)}")
    assert not failures, "\n".join(failures)


def test_net_mana_gate_rejects_mana_neutral_ability():
    """{1}, {T}: Add {B} nets zero. This is the bug the gate exists for."""
    neutral = card("Neutral Rock", "{1}, {T}: Add {B}.", "Artifact")
    assert "ramp" not in cp.classify(neutral)


def test_net_mana_gate_accepts_positive_filter():
    """{1}, {T}: Add {W}{W} nets +1 and IS ramp — the gate must not blanket-reject."""
    filt = card("Filter Rock", "{1}, {T}: Add {W}{W}.", "Artifact")
    assert "ramp" in cp.classify(filt)


def test_multi_face_text_and_type_are_read():
    dfc = {"name": "Split", "card_faces": [
        {"type_line": "Instant", "oracle_text": "Destroy target creature."},
        {"type_line": "Sorcery", "oracle_text": "Draw two cards."},
    ], "legalities": {"commander": "legal"}, "color_identity": []}
    assert "removal" in cp.classify(dfc)
    assert "draw" in cp.classify(dfc)
    assert "Instant" in cp.type_line(dfc)


def test_land_tier_is_conservative():
    """None means 'not confidently classifiable' and the caller ALLOWS it. Mislabelling
    an ordinary owned dual as a restricted tier would gut a strict manabase."""
    tower = card("Command Tower", "{T}: Add one mana of any color.", "Land")
    shock = card("Blood Crypt", "({T}: Add {B} or {R}.)\nAs this land enters, you may "
                                "pay 2 life. If you don't, it enters tapped.",
                 "Land — Swamp Mountain")
    fetch = card("Bloodstained Mire", "{T}, Pay 1 life, Sacrifice this land: Search your "
                                      "library for a Swamp or Mountain card, put it onto "
                                      "the battlefield, then shuffle.", "Land")
    plain = card("Smoldering Marsh", "({T}: Add {B} or {R}.)\nThis land enters tapped "
                                     "unless you control two or more basic lands.",
                 "Land — Swamp Mountain")
    assert cp.land_tier(tower) == "Command Tower"
    assert cp.land_tier(shock) == "shock"
    assert cp.land_tier(fetch) == "fetch"
    assert cp.land_tier(plain) is None          # unknown -> allowed
    # Not a land: never tiered, even though its text sacs-to-search like a fetch.
    bauble = card("Wayfarer's Bauble",
                  "{2}, {T}, Sacrifice this artifact: Search your library for a basic "
                  "land card, put that card onto the battlefield tapped, then shuffle.",
                  "Artifact")
    assert cp.land_tier(bauble) is None


def test_build_pool_filters_and_orders():
    commander = {"name": "Cmdr", "color_identity": ["B", "R"]}
    pool = [
        card("Off Colour", "Draw a card.", ci=["G"]),
        card("Basic", "({T}: Add {R}.)", "Basic Land — Mountain"),
        card("Banned", "Draw a card.", ci=["B"], legalities={"commander": "banned"}),
        card("Good", "Draw two cards.", ci=["B"], edhrec_rank=10),
        card("Better", "Draw two cards.", ci=["R"], edhrec_rank=2),
        card("Unranked", "Draw two cards.", ci=["R"]),
        commander,
    ]
    p = cp.build_pool(commander, pool)
    names = [c["name"] for c in p.flex]
    assert "Off Colour" not in names          # outside colour identity
    assert "Basic" not in names               # basics are never "collection" cards
    assert "Banned" not in names              # not commander-legal
    assert "Cmdr" not in names                # the commander itself
    assert names == ["Better", "Good", "Unranked"]   # EDHREC first, unranked last
    assert p.stats.eligible == 3


def test_roles_never_contain_lands():
    """classify() legitimately tags Command Tower as ramp — it IS a mana source — but
    the role lists must stay nonland. deck_builder drafts role slots straight out of
    this dict, and every ROLE_QUERY it mirrors carries `-type:land`. When lands leaked
    in, a strict build pulled them into its ramp slots: that bypassed the bracket
    land-tier gate, pushed the deck two lands past its planned 38, and starved real
    ramp. Bracket 1 ended up with MORE lands than Bracket 3."""
    commander = {"name": "Cmdr", "color_identity": ["B", "R"]}
    tower = card("Command Tower", "{T}: Add one mana of any color.", "Land")
    rock = card("Signet", "{1}, {T}: Add {B}{R}.", "Artifact")
    assert "ramp" in cp.classify(tower)              # the classification is correct...
    p = cp.build_pool(commander, [tower, rock])
    assert [c["name"] for c in p.roles["ramp"]] == ["Signet"]   # ...the ROLE list is not
    assert [c["name"] for c in p.lands] == ["Command Tower"]
    for role in cp.ROLES:
        assert not any(cp.is_land(c) for c in p.roles[role]), role


def test_build_pool_is_deterministic():
    commander = {"name": "Cmdr", "color_identity": ["B"]}
    pool = [card(f"C{i}", "Draw two cards.", ci=["B"]) for i in range(20)]
    a = [c["name"] for c in cp.build_pool(commander, pool).flex]
    b = [c["name"] for c in cp.build_pool(commander, pool).flex]
    assert a == b


def test_shortfall_omits_covered_roles():
    commander = {"name": "Cmdr", "color_identity": ["B"]}
    pool = [card(f"D{i}", "Draw two cards.", ci=["B"]) for i in range(3)]
    p = cp.build_pool(commander, pool)
    assert cp.shortfall(p, {"draw": 2}) == {}            # covered -> omitted
    assert cp.shortfall(p, {"draw": 5}) == {"draw": 2}
    assert cp.shortfall(p, {"nonsense": 9}) == {}        # unknown keys ignored


def test_colourless_commander_takes_only_colourless_cards():
    commander = {"name": "Kozilek", "color_identity": []}
    pool = [card("Colourless", "Draw two cards.", "Artifact", ci=[]),
            card("Black", "Draw two cards.", ci=["B"])]
    names = [c["name"] for c in cp.build_pool(commander, pool).flex]
    assert names == ["Colourless"]
