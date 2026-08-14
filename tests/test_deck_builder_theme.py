"""Tests for DeckBuilder._fetch_theme_synergy_list's STRICT (collection-only) branch.

This is the most intricate step in the builder and had no test at all. Three real bugs
lived here and every one was caught by hand-running a build, not by the suite:

  1. the collection redirect fired in strict mode and drove `theme` to its floor of 4,
     so a strict Dragon deck got 4 theme cards instead of 26;
  2. the slot plan over-allocated and the deck silently truncated from 101 to 99,
     throwing away whatever the last step drafted;
  3. the theme block was curve-blind — it took every flexible slot EDHREC-best-first,
     which disabled curve control for the whole deck (deviation went 2 -> 24).

(1) and (2) are pinned in build()/_normalize_plan (tests/test_deck_builder_curve.py).
What is pinned HERE is the step itself: how `want` is split, what happens when a theme
runs dry, what `shortfall` promises, and that the fill is curve-aware.

Strict mode has NO Scryfall search, so every test drives it with a client whose
search methods RAISE. A test that passes is therefore proof no search happened.

Self-contained: no data/ directory, no network — CI's actual state. Every fixture below
carries VERBATIM Scryfall oracle text, mana cost and type line; theme matching is decided
entirely from that text, so a fixture retyped from memory tests a card that doesn't exist.
"""
import pytest

import collection_pool
import deck_builder
import theme_match
from commander_analysis import CommanderProfile
from deck_builder import DeckBuilder


class _NoSearch(RuntimeError):
    """The stub client reached Scryfall. In strict mode that is the failure."""


class _DeadClient:
    """Strict mode resolves owned NAMES through Scryfall but must never SEARCH.

    Every search entry point raises, so any test in this file that completes is a
    positive proof that the strict branch stayed inside the owned pool."""

    def get_cards_collection(self, names):
        return {}

    def search_cards_paged(self, query, max_results=60):
        raise _NoSearch(query)

    def search_cards(self, query):
        raise _NoSearch(query)


def card(name, type_line, mana_cost, text, ci, rank):
    return {
        "name": name,
        "type_line": type_line,
        "mana_cost": mana_cost,          # no "cmc": deck_quality parses the real cost
        "oracle_text": text,
        "color_identity": list(ci),
        "legalities": {"commander": "legal"},
        "edhrec_rank": rank,
    }


# ── Fixtures ─────────────────────────────────────────────────────────────────────
# Ranks are spaced per tribe (goblins 1xx, elves x10, dragons x20) purely so a test can
# read the draft order off the names. The WEAK/STRONG split is NOT arbitrary: theme_match
# scores a tribe member whose rules text also names the tribe as a payoff (STRONG) and a
# vanilla body as WEAK, and match_themes sorts STRONG first — so within a tribe the
# expected order is "payoffs by rank, then vanilla bodies by rank".

CHIEFTAIN = card("Goblin Chieftain", "Creature — Goblin", "{1}{R}{R}",
                 "Haste (This creature can attack and {T} as soon as it comes under your "
                 "control.)\nOther Goblin creatures you control get +1/+1 and have haste.",
                 ["R"], 100)                                        # STRONG, MV 3
WARCHIEF = card("Goblin Warchief", "Creature — Goblin Warrior", "{1}{R}{R}",
                "Goblin spells you cast cost {1} less to cast.\n"
                "Goblins you control have haste.", ["R"], 200)      # STRONG, MV 3
KRENKO = card("Krenko, Mob Boss", "Legendary Creature — Goblin Warrior", "{2}{R}{R}",
              "{T}: Create X 1/1 red Goblin creature tokens, where X is the number of "
              "Goblins you control.", ["R"], 300)                   # STRONG, MV 4
MATRON = card("Goblin Matron", "Creature — Goblin", "{2}{R}",
              "When this creature enters, you may search your library for a Goblin card, "
              "reveal that card, put it into your hand, then shuffle.", ["R"], 400)
PROSPECTOR = card("Skirk Prospector", "Creature — Goblin", "{R}",
                  "Sacrifice a Goblin: Add {R}.", ["R"], 500)       # STRONG, MV 1
MOGG = card("Mogg Fanatic", "Creature — Goblin", "{R}",
            "Sacrifice this creature: It deals 1 damage to any target.", ["R"], 600)
RAGING = card("Raging Goblin", "Creature — Goblin Berserker", "{R}",
              "Haste (This creature can attack and {T} as soon as it comes under your "
              "control.)", ["R"], 700)                              # WEAK, MV 1
GOBLINS = [CHIEFTAIN, WARCHIEF, KRENKO, MATRON, PROSPECTOR, MOGG, RAGING]

ARCHDRUID = card("Elvish Archdruid", "Creature — Elf Druid", "{1}{G}{G}",
                 "Other Elf creatures you control get +1/+1.\n"
                 "{T}: Add {G} for each Elf you control.", ["G"], 110)
PERFECT = card("Imperious Perfect", "Creature — Elf Warrior", "{2}{G}",
               "Other Elves you control get +1/+1.\n"
               "{G}, {T}: Create a 1/1 green Elf Warrior creature token.", ["G"], 210)
PRIEST = card("Priest of Titania", "Creature — Elf Druid", "{1}{G}",
              "{T}: Add {G} for each Elf on the battlefield.", ["G"], 310)
LLANOWAR = card("Llanowar Elves", "Creature — Elf Druid", "{G}",
                "{T}: Add {G}.", ["G"], 410)                        # WEAK, MV 1
MYSTIC = card("Elvish Mystic", "Creature — Elf Druid", "{G}",
              "{T}: Add {G}.", ["G"], 510)                          # WEAK, MV 1
ELVES = [ARCHDRUID, PERFECT, PRIEST, LLANOWAR, MYSTIC]

REGENT = card("Thunderbreak Regent", "Creature — Dragon", "{2}{R}{R}",
              "Flying\nWhenever a Dragon you control becomes the target of a spell or "
              "ability an opponent controls, this creature deals 3 damage to that player.",
              ["R"], 120)                                           # STRONG, MV 4
LATHLISS = card("Lathliss, Dragon Queen", "Legendary Creature — Dragon", "{4}{R}{R}",
                "Flying\nWhenever another nontoken Dragon you control enters, create a "
                "5/5 red Dragon creature token with flying.\n"
                "{1}{R}: Dragons you control get +1/+0 until end of turn.", ["R"], 220)
UTVARA = card("Utvara Hellkite", "Creature — Dragon", "{6}{R}{R}",
              "Flying\nWhenever a Dragon you control attacks, create a 6/6 red Dragon "
              "creature token with flying.", ["R"], 320)            # STRONG, MV 8
SHIVAN = card("Shivan Dragon", "Creature — Dragon", "{4}{R}{R}",
              "Flying\n{R}: This creature gets +1/+0 until end of turn.", ["R"], 420)
BALEFIRE = card("Balefire Dragon", "Creature — Dragon", "{5}{R}{R}",
                "Flying\nWhenever this creature deals combat damage to a player, it deals "
                "that much damage to each creature that player controls.", ["R"], 520)
DRAGONS = [REGENT, LATHLISS, UTVARA, SHIVAN, BALEFIRE]

SOL_RING = card("Sol Ring", "Artifact", "{1}", "{T}: Add {C}{C}.", [], 1)

COMMANDER = {"name": "Test Commander", "color_identity": ["R", "G"]}
PROFILE = CommanderProfile(
    name=COMMANDER["name"],
    color_identity=["R", "G"],
    oracle_text="",
    keywords=[],
    themes=[],
    mana_value=4.0,
    type_line="Legendary Creature — Goblin Shaman",
    card={},
)


def _strict_builder(pool_cards, curve_target=None):
    """A DeckBuilder wired exactly as build() wires it for card_source='collection'."""
    b = DeckBuilder(_DeadClient())
    b._commander_name = COMMANDER["name"]
    b._card_source = deck_builder.SOURCE_COLLECTION
    b._pool = collection_pool.build_pool(COMMANDER, list(pool_cards))
    b._curve_target = dict(curve_target or {})
    assert b._strict(), "fixture is wrong: the builder is not in strict mode"
    return b


def _names(builder):
    return [c["name"] for c in builder._deck]


# ── The stub itself ──────────────────────────────────────────────────────────────

def test_the_stub_client_really_raises():
    """Otherwise every "no search happened" test below would pass vacuously."""
    with pytest.raises(_NoSearch):
        _DeadClient().search_cards_paged("otag:ramp")
    with pytest.raises(_NoSearch):
        _DeadClient().search_cards('!"Mountain"')


def test_non_strict_mode_is_what_searches():
    """The complement of every other test: with no owned pool the SAME call goes to
    Scryfall. That is what makes the silence in strict mode meaningful."""
    b = DeckBuilder(_DeadClient())
    b._commander_name = COMMANDER["name"]
    assert not b._strict()
    with pytest.raises(_NoSearch):
        b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins"], 5)


def test_strict_mode_never_searches_and_drafts_only_owned_cards():
    b = _strict_builder(GOBLINS + ELVES + DRAGONS)
    added = b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins", "tribal_dragons"], 8)
    assert added == 8
    owned = {c["name"] for c in GOBLINS + ELVES + DRAGONS}
    assert set(_names(b)) <= owned


# ── Slot distribution ────────────────────────────────────────────────────────────

def test_slots_split_across_three_themes_with_the_remainder_to_the_first():
    """want=10 over 3 themes is 3 each with 1 left over, and the leftover goes to the
    LEAD theme — the one the commander was actually detected as."""
    b = _strict_builder(GOBLINS + ELVES + DRAGONS)
    added = b._fetch_theme_synergy_list(
        PROFILE, ["tribal_goblins", "tribal_elves", "tribal_dragons"], 10)
    assert added == 10
    assert _names(b) == [
        # 4 goblins: payoffs first (STRONG), each tribe in EDHREC order
        "Goblin Chieftain", "Goblin Warchief", "Krenko, Mob Boss", "Goblin Matron",
        "Elvish Archdruid", "Imperious Perfect", "Priest of Titania",
        "Thunderbreak Regent", "Lathliss, Dragon Queen", "Utvara Hellkite",
    ]


def test_only_the_first_three_themes_are_active():
    """A commander can detect more than three themes; the step takes the top 3. Sol Ring
    is the only card in the pool matching the fourth, so its absence is the assertion."""
    b = _strict_builder(GOBLINS + ELVES + DRAGONS + [SOL_RING])
    added = b._fetch_theme_synergy_list(
        PROFILE,
        ["tribal_goblins", "tribal_elves", "tribal_dragons", "artifacts"], 9)
    assert added == 9
    assert "Sol Ring" not in _names(b)
    assert theme_match.theme_score(SOL_RING, "artifacts") != theme_match.NO_MATCH


def test_a_theme_with_no_matches_does_not_waste_its_slots():
    """An owned pool is small enough that one thin theme routinely runs dry. The Scryfall
    path can shrug (its pool is the whole format); here the empty theme's slots must be
    redistributed by the second pass or the deck comes up short."""
    b = _strict_builder(GOBLINS + DRAGONS)        # no elves owned at all
    added = b._fetch_theme_synergy_list(
        PROFILE, ["tribal_goblins", "tribal_elves", "tribal_dragons"], 9)
    assert added == 9
    assert "theme" not in b.shortfall
    got = _names(b)
    assert got[:3] == ["Goblin Chieftain", "Goblin Warchief", "Krenko, Mob Boss"]
    assert got[3:6] == ["Thunderbreak Regent", "Lathliss, Dragon Queen",
                        "Utvara Hellkite"]
    # The elf theme's 3 slots came back round to the first theme, not to nobody.
    assert got[6:] == ["Goblin Matron", "Skirk Prospector", "Mogg Fanatic"]


def test_a_card_matching_two_active_themes_is_drafted_once():
    """Krenko is a Goblin payoff AND a token maker, so it is in both matched lists."""
    assert theme_match.theme_score(KRENKO, "tribal_goblins") == theme_match.STRONG
    assert theme_match.theme_score(KRENKO, "tokens") == theme_match.STRONG
    b = _strict_builder(GOBLINS)
    added = b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins", "tokens"], 4)
    got = _names(b)
    assert added == 4 == len(got)
    assert len(set(got)) == 4
    assert got.count("Krenko, Mob Boss") == 1


# ── shortfall ────────────────────────────────────────────────────────────────────

def test_shortfall_records_only_the_genuinely_unfillable_remainder():
    """shortfall is the builder's promise to say what the collection could NOT cover.
    It must be want-minus-drafted, not want — a pool that covered 3 of 10 is short 7."""
    b = _strict_builder([CHIEFTAIN, WARCHIEF, KRENKO])
    added = b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins"], 10)
    assert added == 3
    assert b.shortfall == {"theme": 7}


def test_shortfall_is_absent_when_the_pool_covers_the_request():
    """Absent, not zero: collection_pool.shortfall omits covered roles, so `{}` is what
    the UI reads as "your collection can build this"."""
    b = _strict_builder(GOBLINS)
    assert b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins"], 5) == 5
    assert b.shortfall == {}


def test_shortfall_counts_the_deficit_after_redistribution_not_before():
    """The first pass leaves the empty theme's slots unfilled; only what survives the
    second pass is a real deficit. Recording the first-pass gap would over-report."""
    b = _strict_builder([CHIEFTAIN, WARCHIEF, KRENKO, MATRON, PROSPECTOR])
    added = b._fetch_theme_synergy_list(
        PROFILE, ["tribal_goblins", "tribal_elves", "tribal_dragons"], 9)
    assert added == 5                       # 3 goblins first pass + 2 redistributed
    assert b.shortfall == {"theme": 4}      # not 6, which is the first-pass gap


# ── Unknown theme names ──────────────────────────────────────────────────────────

def test_an_unknown_theme_name_is_skipped_and_recorded_never_raises():
    """A theme key the local matcher doesn't know must not take the build thread down
    with a KeyError; the slots it can't fill are reported instead."""
    b = _strict_builder(GOBLINS)
    added = b._fetch_theme_synergy_list(PROFILE, ["not_a_theme", "also_not_a_theme"], 6)
    assert added == 0
    assert b._deck == []
    # Both the unfillable slots AND the fact that two named themes never applied.
    assert b.shortfall == {"theme": 6, "unrecognised_themes": 2}


def test_an_unknown_theme_alongside_a_known_one_costs_the_known_theme_nothing():
    """The unknown name is filtered out BEFORE the split, so it never reserves slots."""
    b = _strict_builder(GOBLINS)
    added = b._fetch_theme_synergy_list(PROFILE, ["not_a_theme", "tribal_goblins"], 4)
    assert added == 4
    assert _names(b) == ["Goblin Chieftain", "Goblin Warchief", "Krenko, Mob Boss",
                         "Goblin Matron"]
    # The known theme is untouched, but the dropped name is still REPORTED. Recording
    # nothing left the caller unable to tell a thin pool from a typo.
    assert b.shortfall == {"unrecognised_themes": 1}


def test_every_theme_name_the_builder_can_be_handed_is_known_locally():
    """The strict branch filters on theme_match.THEMES while the Scryfall branch filters
    on THEME_SYNERGY_QUERIES. A key in one but not the other would silently empty the
    theme package for exactly one card_source."""
    from commander_analysis import THEME_SYNERGY_QUERIES
    assert set(THEME_SYNERGY_QUERIES) == set(theme_match.THEMES)


# ── Curve awareness ──────────────────────────────────────────────────────────────

def test_the_theme_fill_is_curve_aware():
    """The theme block is ~20-26 of the 99 slots. Drafting it EDHREC-best-first with no
    opinion about cost is what disabled curve control for the whole deck.

    Skirk Prospector (MV 1, rank 500) must beat Goblin Chieftain (MV 3, rank 100) while
    the one-drop bucket is short — both are STRONG on-theme, so the swap costs nothing
    thematic."""
    b = _strict_builder(GOBLINS, curve_target={1: 1, 3: 0})
    assert b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins"], 1) == 1
    assert _names(b) == ["Skirk Prospector"]


def test_the_curve_target_is_what_flips_the_order():
    """Same pool, same theme, same want — only the target differs. Without it the step
    falls back to the plain EDHREC order, which is the pre-fix behaviour."""
    b = _strict_builder(GOBLINS, curve_target={})
    assert b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins"], 1) == 1
    assert _names(b) == ["Goblin Chieftain"]


def test_curve_awareness_keeps_reaching_into_a_short_bucket():
    """Three one-drops ranked 500/600/700 are taken ahead of a rank-100 three-drop for as
    long as bucket 1 is short — the bias is re-evaluated per card, not partitioned once."""
    b = _strict_builder(GOBLINS, curve_target={1: 3})
    assert b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins"], 3) == 3
    assert _names(b) == ["Skirk Prospector", "Mogg Fanatic", "Raging Goblin"]


def test_a_met_bucket_gives_the_slot_back_to_edhrec_order():
    b = _strict_builder(GOBLINS, curve_target={1: 0, 3: 0})   # nothing is short
    assert b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins"], 2) == 2
    assert _names(b) == ["Goblin Chieftain", "Goblin Warchief"]


# ── The count the caller is promised ─────────────────────────────────────────────

def test_never_returns_more_cards_than_the_caller_asked_for():
    """The caller passes min(plan['theme'], 99 - len(deck)). Overshooting it is how the
    deck silently truncated from 101 back to 99, throwing away the last step's work."""
    pool = GOBLINS + ELVES + DRAGONS               # 17 matchable cards
    themes = ["tribal_goblins", "tribal_elves", "tribal_dragons"]
    for want in range(1, 13):
        b = _strict_builder(pool)
        added = b._fetch_theme_synergy_list(PROFILE, themes, want)
        assert added == want, want
        assert len(b._deck) == want, want


def test_want_zero_adds_nothing_and_reports_no_shortfall():
    """The caller's `99 - len(self._deck)` cap hits 0 on a full deck."""
    b = _strict_builder(GOBLINS)
    assert b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins"], 0) == 0
    assert b._deck == []
    assert b.shortfall == {}


def test_a_want_below_the_theme_count_still_fills_exactly_want():
    """want < len(active) makes `remainder` NEGATIVE, so the first theme's slot goes to
    zero or below and the LEAD theme contributes nothing — the opposite of the
    remainder-to-the-first rule the normal path follows. Only reachable when the caller's
    `99 - len(self._deck)` cap bites (the plan floors theme at 4), and the total is still
    correct, so this test pins only the total. REPORTED, NOT FIXED."""
    themes = ["tribal_goblins", "tribal_elves", "tribal_dragons"]
    for want in (1, 2):
        b = _strict_builder(GOBLINS + ELVES + DRAGONS)
        assert b._fetch_theme_synergy_list(PROFILE, themes, want) == want, want
        assert len(b._deck) == want, want


def test_the_pool_is_nonland_flex_so_theme_slots_never_eat_the_manabase():
    """The Scryfall theme queries all carry `-type:land`. Strict mode matches over
    pool.flex for the same reason: a land drafted here bypasses the bracket land-tier
    gate and pushes the deck past its planned land count."""
    tower = card("Command Tower", "Land", "",
                 "{T}: Add one mana of any color in your commander's color identity.",
                 [], 5)
    # A land CAN score on a theme, so the exclusion has to come from the pool, not luck.
    creature_land = card("Den of the Bugbear", "Land", "",
                         "If you control two or more other lands, this land enters "
                         "tapped.\n{T}: Add {R}.\n{3}{R}: Until end of turn, this land "
                         "becomes a 3/2 red Goblin creature with \"Whenever this creature "
                         "attacks, create a 1/1 red Goblin creature token that's tapped "
                         "and attacking.\" It's still a land.", ["R"], 6)
    assert theme_match.theme_score(creature_land, "tribal_goblins") != theme_match.NO_MATCH
    b = _strict_builder(GOBLINS + [tower, creature_land])
    b._fetch_theme_synergy_list(PROFILE, ["tribal_goblins"], 7)
    assert "Command Tower" not in _names(b)
    assert "Den of the Bugbear" not in _names(b)


def test_an_unknown_name_does_not_consume_one_of_the_three_theme_slots():
    """The [:3] cap is applied AFTER the THEMES filter, so a junk name must not push a
    real theme out of the package.

    Without the filter, ["not_a_theme", goblins, elves, dragons][:3] keeps the junk name
    and DROPS dragons entirely. A review mutation-tested this file and found that
    deleting the filter left every test green, because no case ever put an unknown name
    in a live top-3 slot ahead of a known theme.
    """
    b = _strict_builder(GOBLINS + ELVES + DRAGONS)
    b._fetch_theme_synergy_list(
        PROFILE, ["not_a_theme", "tribal_goblins", "tribal_elves", "tribal_dragons"], 9)
    drafted = set(_names(b))
    assert any(c["name"] in drafted for c in GOBLINS), drafted
    assert any(c["name"] in drafted for c in ELVES), drafted
    assert any(c["name"] in drafted for c in DRAGONS), drafted   # the one the filter saves
    assert b.shortfall.get("unrecognised_themes") == 1
