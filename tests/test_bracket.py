"""BracketFilter.allows() -- the per-card gate deck_builder uses while drafting.

No test coverage existed for this before 2026-08-24 despite it gating every card that
goes into a built deck. Two real bugs found by audit and fixed here:

1. Game Changers were matched by a hardcoded, dated name frozenset with no live source
   of truth -- while the engine's own `data/scryfall.py` reads the identical field
   (`game_changer`) live off Scryfall and hard-fails on a stale schema by design. Two
   authorities computing the same official-rules quota two different ways is exactly the
   "two opinions on one screen drifted" problem CLAUDE.md documents the engine merge was
   meant to end. Confirmed live 2026-08-24: Scryfall's `/cards/search` (what
   `deck_builder.py` actually calls) returns `game_changer` on every result, and one real
   printing name-mismatch already existed (some Tergrid, God of Fright printings report
   as "Tergrid, God of Fright // Tergrid's Lantern", which a bare-name frozenset misses).
2. `_MLD_PATTERNS` was plain substring checks with no object gate -- "each player
   destroys all" matches ANY plural object, not just lands, so a card that says "each
   player destroys all artifacts they control" would have been wrongly read as mass land
   denial. The engine's own parallel copy of this same pattern was hardened for exactly
   this failure on 2026-08-07 (validated against all 34,179 cards); this file now carries
   the identical, already-validated regexes rather than a second unfixed copy.
"""
from bracket import BracketFilter, GAME_CHANGERS


def _card(name, oracle_text="", game_changer=None):
    card = {"name": name, "oracle_text": oracle_text}
    if game_changer is not None:
        card["game_changer"] = game_changer
    return card


# ── Game Changers: live field wins over the fallback name list ────────────────────────

def test_live_game_changer_field_true_counts_toward_quota():
    f = BracketFilter(3)  # max 3
    # Not in the hardcoded fallback set at all -- only the live field says so.
    assert f.allows(_card("Some New Card", game_changer=True))
    assert f.gc_used == 1


def test_live_game_changer_field_false_overrides_the_fallback_list():
    """A card whose live field says False must not be gated as a Game Changer even if a
    stale fallback name entry would have said otherwise -- the live field is authoritative
    whenever it's present. Rhystic Study is unambiguously a real Game Changer, so use a
    fallback-list name with an explicit False to prove the override direction."""
    f = BracketFilter(1)  # max 0 -- would reject a real Game Changer outright
    name = next(iter(GAME_CHANGERS))
    assert f.allows(_card(name, game_changer=False))
    assert f.gc_used == 0


def test_missing_field_falls_back_to_the_name_list():
    f = BracketFilter(1)
    name = next(iter(GAME_CHANGERS))
    assert not f.allows(_card(name))  # no "game_changer" key at all -> fallback applies


def test_missing_field_and_unknown_name_is_not_a_game_changer():
    f = BracketFilter(1)
    assert f.allows(_card("Totally Ordinary Bear"))


def test_quota_enforced_after_live_field_says_true():
    f = BracketFilter(3)
    for i in range(3):
        assert f.allows(_card(f"GC {i}", game_changer=True))
    assert not f.allows(_card("GC 4", game_changer=True))
    assert f.gc_used == 3


# ── Mass land denial: object-gated regex, not a bare substring ────────────────────────

def test_mld_true_positive_destroy_all_lands():
    f = BracketFilter(1)
    assert not f.allows(_card("Armageddon II", "Destroy all lands."))


def test_mld_false_positive_fixed_wrong_object():
    """The exact shape of the bug: 'each player destroys all <non-land noun>' must NOT
    read as mass land denial just because it starts the same way a real MLD card does."""
    f = BracketFilter(1)
    assert f.allows(_card("Not MLD At All", "Each player destroys all artifacts they control."))


def test_mld_false_positive_fixed_except_guard():
    f = BracketFilter(1)
    assert f.allows(_card(
        "Scourglass-Shaped", "Destroy all permanents except for artifacts and lands."
    ))


def test_mld_catches_sacrifice_scaling_without_the_literal_phrase():
    f = BracketFilter(1)
    assert not f.allows(_card(
        "Thoughts of Ruin-Shaped",
        "Each player sacrifices a land for each Mountain you control.",
    ))


# ── Extra turns: widened to match the engine's pattern ─────────────────────────────────

def test_extra_turn_after_this_one_phrasing_now_caught():
    f = BracketFilter(1)
    assert not f.allows(_card("New Nexus", "Target player takes an extra turn after this one."))
