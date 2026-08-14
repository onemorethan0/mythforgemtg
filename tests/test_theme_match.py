"""Gold-set tests for theme_match's local theme synergy.

Strict "build only from cards I own" cannot run the Scryfall THEME_SYNERGY_QUERIES, so
these matches decide which cards fill a deck's ~20 theme slots. Every fixture carries
VERBATIM oracle text.

Written from SPEC_theme_match.md independently of the implementation: a check authored by
the same model that wrote the code inherits its misreadings.

Self-contained — no data/ directory, no network, which is CI's actual state.
"""
import theme_match as tm


def card(name, type_line, text, **kw):
    c = {"name": name, "type_line": type_line, "oracle_text": text}
    c.update(kw)
    return c


SHIVAN = card("Shivan Dragon", "Creature — Dragon",
              "Flying\n{R}: This creature gets +1/+0 until end of turn.")
BLADEWING = card("Bladewing the Risen", "Legendary Creature — Zombie Dragon",
                 "Flying\nWhen Bladewing enters, you may return target Dragon permanent "
                 "card from your graveyard to the battlefield.\n"
                 "{B}{R}: Dragon creatures get +1/+1 until end of turn")
CHIEFTAIN = card("Goblin Chieftain", "Creature — Goblin",
                 "Haste\nOther Goblin creatures you control get +1/+1 and have haste.")
JADAR = card("Jadar, Ghoulcaller of Nephalia", "Legendary Creature — Human Wizard",
             "At the beginning of your end step, if you control no creatures with "
             "decayed, create a 2/2 black Zombie creature token with decayed.")
STORM_KILN = card("Storm-Kiln Artist", "Creature — Dwarf Shaman",
                  "This creature gets +1/+0 for each artifact you control.\n"
                  "Magecraft — Whenever you cast or copy an instant or sorcery spell, "
                  "create a Treasure token.")
GRAVE_PACT = card("Grave Pact", "Enchantment",
                  "Whenever a creature you control dies, each other player sacrifices a "
                  "creature of their choice.")
CRAWLER = card("Psychosis Crawler", "Artifact Creature — Phyrexian Horror",
               "Psychosis Crawler's power and toughness are each equal to the number of "
               "cards in your hand.\nWhenever you draw a card, each opponent loses 1 life.")
OVERSEER = card("Steel Overseer", "Artifact Creature — Construct",
                "{T}: Put a +1/+1 counter on each artifact creature you control.")
LIVING_DEATH = card("Living Death", "Sorcery",
                    "Each player exiles all creature cards from their graveyard, then "
                    "sacrifices all creatures they control, then puts all cards they "
                    "exiled this way onto the battlefield.")
SOL_RING = card("Sol Ring", "Artifact", "{T}: Add {C}{C}.")


# NOTE on the WEAK/STRONG split for tribal themes. The Scryfall query is
# `type:dragon OR (o:"dragon" o:"you control")`, and Bladewing's text never says "you
# control" — so it matches only via its TYPE. Fidelity governs the MATCH SET, which is
# why that stays true. But the score governs ORDERING, which Scryfall never provided
# (it sorted purely by EDHREC), so a card whose rules text references the tribe at all
# ("Dragon creatures get +1/+1") is ranked STRONG ahead of a vanilla tribe member.
# Ranking a real payoff first cannot pull in a card Scryfall would have excluded.
GOLD = [
    (SHIVAN,       "tribal_dragons", 1),   # a Dragon, but its text never says "Dragon"
    (BLADEWING,    "tribal_dragons", 2),   # "Dragon creatures get +1/+1" is a payoff
    (BLADEWING,    "tribal_zombies", 1),   # a Zombie, but no Zombie payoff text
    (CHIEFTAIN,    "tribal_goblins", 2),
    (JADAR,        "tribal_zombies", 2),   # "Zombie" + "you control" co-occur
    (STORM_KILN,   "spellslinger",   2),
    (STORM_KILN,   "tokens",         2),
    (STORM_KILN,   "artifacts",      0),   # counts artifacts != type:artifact
    (GRAVE_PACT,   "aristocrats",    2),
    (CRAWLER,      "draw_matters",   2),
    (CRAWLER,      "artifacts",      1),
    (OVERSEER,     "counters",       2),
    (LIVING_DEATH, "reanimator",     0),
    (LIVING_DEATH, "graveyard",      0),   # "their graveyard", not "your"
    (SOL_RING,     "tribal_dragons", 0),
    (SOL_RING,     "artifacts",      1),
]


def test_gold_set():
    failures = []
    for c, theme, expected in GOLD:
        got = tm.theme_score(c, theme)
        if got != expected:
            failures.append(f"{c['name']} / {theme}: got {got}, want {expected}")
    assert not failures, "\n".join(failures)


def test_score_constants_are_ordered():
    assert tm.NO_MATCH < tm.WEAK < tm.STRONG


def test_every_theme_key_is_present():
    """The builder maps its active themes straight onto these keys; a missing one
    silently empties a theme slot."""
    expected = {
        "tribal_dragons", "tribal_elves", "tribal_zombies", "tribal_humans",
        "tribal_merfolk", "tribal_vampires", "tribal_goblins", "tribal_soldiers",
        "tribal_warriors", "tribal_wizards", "tribal_spirits", "tribal_angels",
        "tribal_demons", "tribal_beasts", "tribal_dinosaurs", "tribal_slivers",
        "tribal_werewolves", "tribal_wolves", "tribal_knights", "tribal_ninjas",
        "tribal_cats", "auras", "tokens", "counters", "aristocrats", "reanimator",
        "spellslinger", "enchantress", "artifacts", "voltron", "draw_matters",
        "lifegain", "landfall", "graveyard", "etb", "energy", "chaos", "theft",
        "group_hug", "voltron_combat",
    }
    assert expected <= set(tm.THEMES), expected - set(tm.THEMES)


def test_unknown_theme_returns_no_match_and_does_not_raise():
    assert tm.theme_score(SHIVAN, "not_a_theme") == tm.NO_MATCH


def test_tribal_text_matching_uses_word_boundaries():
    """Bare substrings wreck the tribal themes: 'cat' is inside 'escalate' and
    'duplicate', 'elf' is inside 'yourself'."""
    escalate = card("Escalating Spell", "Instant",
                    "Escalate {2} (Pay this cost for each mode chosen beyond the first.) "
                    "You control the outcome.")
    yourself = card("Self Serve", "Sorcery",
                    "You control target creature you own. Sacrifice it yourself.")
    assert tm.theme_score(escalate, "tribal_cats") == tm.NO_MATCH
    assert tm.theme_score(yourself, "tribal_elves") == tm.NO_MATCH


def test_subtypes_reads_every_face_and_both_dash_styles():
    assert tm.subtypes(BLADEWING) == {"zombie", "dragon"}
    hyphen = card("Old Export", "Creature - Goblin Warrior", "")
    assert tm.subtypes(hyphen) == {"goblin", "warrior"}
    assert tm.subtypes(card("No Dash", "Sorcery", "")) == set()


def test_combined_dfc_type_line_does_not_leak_back_face_words():
    """A DFC carries a COMBINED top-level type line. Splitting on the first dash alone
    drags the back face's pre-dash words and the '//' into the front face's subtypes,
    which is how themer.py once turned every imported card into the same creature type.
    Split face by face first."""
    dfc = card("Werewolf", "Creature — Human Rogue // Creature — Werewolf Horror", "")
    assert tm.subtypes(dfc) == {"human", "rogue", "werewolf", "horror"}
    assert "creature" not in tm.subtypes(dfc)


def test_multi_face_text_and_type_are_read():
    dfc = {"name": "Split", "card_faces": [
        {"type_line": "Creature — Dragon", "oracle_text": "Flying"},
        {"type_line": "Sorcery", "oracle_text": "Whenever you draw a card, gain 1 life."},
    ]}
    assert tm.theme_score(dfc, "tribal_dragons") == tm.WEAK
    assert tm.theme_score(dfc, "draw_matters") == tm.STRONG


def test_match_themes_orders_strong_first_then_edhrec_then_name():
    strong_bad_rank = dict(CHIEFTAIN, edhrec_rank=9000)
    weak_good_rank = dict(SHIVAN, edhrec_rank=1, name="Aaa Weak",
                          type_line="Creature — Goblin",
                          oracle_text="Flying")
    weak_unranked = dict(weak_good_rank, name="Zzz Unranked", edhrec_rank=None)
    out = tm.match_themes([weak_good_rank, weak_unranked, strong_bad_rank],
                          ["tribal_goblins"])
    assert [c["name"] for c in out["tribal_goblins"]] == [
        "Goblin Chieftain", "Aaa Weak", "Zzz Unranked"]


def test_match_themes_keys_every_requested_theme_and_drops_non_matches():
    out = tm.match_themes([SOL_RING], ["tribal_dragons", "artifacts"])
    assert set(out) == {"tribal_dragons", "artifacts"}
    assert out["tribal_dragons"] == []
    assert [c["name"] for c in out["artifacts"]] == ["Sol Ring"]


def test_match_themes_is_deterministic():
    pool = [dict(SHIVAN, name=f"D{i}") for i in range(20)]
    a = [c["name"] for c in tm.match_themes(pool, ["tribal_dragons"])["tribal_dragons"]]
    b = [c["name"] for c in tm.match_themes(pool, ["tribal_dragons"])["tribal_dragons"]]
    assert a == b


def test_score_ordered_covers_the_tribes_and_excludes_card_type_themes():
    """The score is only meaningful where WEAK means "is a member of the thing".

    Where WEAK is a whole card TYPE it contains every staple, so score-first is
    destructive: measured over the 34k store, `artifacts` has 5 STRONG against 3909 WEAK,
    and reordering demotes Sol Ring, Arcane Signet and Lightning Greaves for five obscure
    artifact-ETB triggers. `voltron` is 4 vs 1909 with medians 16700/16948 — noise."""
    assert len(tm.SCORE_ORDERED) == 21
    assert all(t.startswith("tribal_") for t in tm.SCORE_ORDERED)
    for t in ("artifacts", "voltron", "auras", "enchantress"):
        assert t not in tm.SCORE_ORDERED, t


def test_enchantress_strong_rule_actually_fires():
    """It used to match zero of 34k cards. The Scryfall query's literal
    "whenever an enchantment enters" is not how any card is templated; the real wordings
    are "whenever you cast an enchantment spell" and "whenever an enchantment you control
    enters". A STRONG tier that can never fire is a dead rule."""
    argothian = card("Argothian Enchantress", "Creature — Human Druid",
                     "Whenever you cast an enchantment spell, draw a card.")
    sigil = card("Sigil of the Empty Throne", "Enchantment",
                 "Whenever you cast an enchantment spell, create a 4/4 white Angel "
                 "creature token with flying.")
    assert tm.theme_score(argothian, "enchantress") == tm.STRONG
    assert tm.theme_score(sigil, "enchantress") == tm.STRONG
    # A plain enchantment with no payoff text stays WEAK, not promoted.
    assert tm.theme_score(card("Plain", "Enchantment", "Creatures get +1/+1."),
                          "enchantress") == tm.WEAK
