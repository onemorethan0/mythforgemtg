"""Deck-context archetype detection. Written from docs/SPEC_deck_themes.md.

Offline: theme_match is a local text scan, so nothing here touches the network.
"""

from __future__ import annotations

import pytest

import deck_themes
import theme_match


def _goblin(n: int) -> list[dict]:
    """Cards that score STRONG for tribal_goblins (a payoff line, not just a body)."""
    return [{"name": f"Goblin Lord {i}", "type_line": "Creature — Goblin",
             "oracle_text": "Other Goblin creatures you control get +1/+1."}
            for i in range(n)]


def _token(n: int) -> list[dict]:
    return [{"name": f"Token Maker {i}", "type_line": "Enchantment",
             "oracle_text": "At the beginning of your end step, create a 1/1 white "
                            "Soldier creature token."}
            for i in range(n)]


def test_theme_score_signature_is_per_theme():
    """Pins the API this module is built on: (card, theme) -> int, NOT card -> dict."""
    card = _goblin(1)[0]
    assert theme_match.theme_score(card, "tribal_goblins") == theme_match.STRONG
    assert theme_match.theme_score(card, "spellslinger") == theme_match.NO_MATCH


def test_theme_counts_returns_strong_and_weak():
    counts = deck_themes.theme_counts(_goblin(4))
    strong, weak = counts["tribal_goblins"]
    assert (strong, weak) == (4, 0)


def test_theme_counts_omits_unmatched_themes():
    counts = deck_themes.theme_counts(_goblin(1))
    assert "spellslinger" not in counts


def test_duplicates_counted_once_and_quantity_ignored():
    """Four copies of one token-maker is not four token cards."""
    card = dict(_token(1)[0], quantity=4)
    counts = deck_themes.theme_counts([card, dict(card)])
    assert counts["tokens"][0] == 1


def test_basic_lands_are_skipped():
    deck = _goblin(3) + [{"name": "Mountain", "type_line": "Basic Land — Mountain",
                          "oracle_text": ""}]
    assert deck_themes.theme_counts(deck).get("tribal_goblins", (0, 0))[0] == 3


def test_a_card_saying_basic_but_not_a_land_is_kept():
    """Both words, not just 'basic' — the filter must check for a LAND."""
    deck = [{"name": "Basic Instinct", "type_line": "Enchantment",
             "oracle_text": "At the beginning of your end step, create a 1/1 white "
                            "Soldier creature token."}]
    assert deck_themes.theme_counts(deck).get("tokens", (0, 0))[0] == 1


# ── detection threshold ─────────────────────────────────────────────────────────

def test_min_strong_gates_a_theme():
    """Shelob's `aristocrats` had ONE supporting card; one card is not an archetype."""
    assert deck_themes.detect_deck_themes(_goblin(2)) == []
    assert deck_themes.detect_deck_themes(_goblin(3)) == ["tribal_goblins"]


def test_weak_matches_alone_never_promote_a_theme():
    """Shelob's `enchantress` scored 0 STRONG / 8 WEAK. Eight incidental matches with no
    payoff card is not an archetype."""
    weak_only = [{"name": f"Plain Goblin {i}", "type_line": "Creature — Goblin",
                  "oracle_text": "Haste."} for i in range(8)]
    counts = deck_themes.theme_counts(weak_only)
    assert counts.get("tribal_goblins", (0, 0))[0] == 0     # no STRONG at all
    assert deck_themes.detect_deck_themes(weak_only) == []


def test_detect_is_ranked_and_capped():
    themes = deck_themes.detect_deck_themes(_token(9) + _goblin(4), top_n=2)
    assert themes[0] == "tokens"                            # 9 beats 4
    assert len(themes) <= 2


def test_detect_is_deterministic():
    deck = _token(5) + _goblin(5)
    assert deck_themes.detect_deck_themes(deck) == deck_themes.detect_deck_themes(deck)


def test_empty_deck():
    assert deck_themes.detect_deck_themes([]) == []
    assert deck_themes.theme_counts([]) == {}


# ── merge ───────────────────────────────────────────────────────────────────────

def test_merge_without_counts_is_plain_commander_first():
    """No deck to read (a fresh build) means nothing is contradicted."""
    assert deck_themes.merge_themes(["aristocrats"], ["tokens"]) == ["aristocrats", "tokens"]


def test_merge_demotes_a_commander_theme_the_deck_contradicts():
    """The Shelob case: the commander declares `aristocrats`, the deck has ONE such card.

    Commander-first spent a theme slot chasing a plan the deck does not have — the very
    failure deck context exists to fix.
    """
    counts = {"tokens": (15, 0), "aristocrats": (1, 0),
              "graveyard": (7, 0), "voltron_combat": (7, 0)}
    merged = deck_themes.merge_themes(
        ["tokens", "aristocrats"],
        ["tokens", "graveyard", "voltron_combat"], deck_counts=counts)
    # Demotion + the 3-theme limit is what actually evicts it, which is the real
    # corpus case: three supported deck themes fill the budget first.
    assert merged == ["tokens", "graveyard", "voltron_combat"]
    assert "aristocrats" not in merged


def test_merge_keeps_a_supported_commander_theme_first():
    """The Ghired case: the commander was already right; don't thrash a correct answer."""
    counts = {"tokens": (39, 0), "voltron_combat": (6, 0), "counters": (4, 0)}
    merged = deck_themes.merge_themes(
        ["tokens", "voltron_combat"], ["tokens", "voltron_combat", "counters"],
        deck_counts=counts)
    assert merged == ["tokens", "voltron_combat", "counters"]


def test_merge_fills_an_empty_commander():
    """The Jegantha case: a companion with no oracle theme gets a plan from its deck."""
    counts = {"voltron_combat": (7, 0), "tokens": (5, 0)}
    assert deck_themes.merge_themes([], ["voltron_combat", "tokens"],
                                    deck_counts=counts) == ["voltron_combat", "tokens"]


def test_demoted_theme_survives_when_there_is_room():
    """Demoted, not dropped — a user rebuilding may be building TOWARD that plan."""
    counts = {"aristocrats": (0, 0), "tokens": (9, 0)}
    merged = deck_themes.merge_themes(["aristocrats"], ["tokens"], deck_counts=counts)
    assert merged == ["tokens", "aristocrats"]


def test_merge_dedupes_and_respects_limit():
    merged = deck_themes.merge_themes(["a", "a", "b"], ["b", "c", "d"], limit=3)
    assert merged == ["a", "b", "c"]


@pytest.mark.parametrize("cmdr,deck", [([], []), (None, None), (["x"], [])])
def test_merge_tolerates_empty_inputs(cmdr, deck):
    assert isinstance(deck_themes.merge_themes(cmdr, deck), list)


# ── stats_block ─────────────────────────────────────────────────────────────────

def test_stats_block_shape():
    block = deck_themes.stats_block({}, _goblin(5))
    assert set(block) == {"commander", "deck", "merged"}
    assert block["deck"] == ["tribal_goblins"]


def test_stats_block_empty_when_nothing_to_say():
    assert deck_themes.stats_block({}, []) == {}
    assert deck_themes.stats_block({}, _goblin(1)) == {}     # below MIN_STRONG


def test_stats_block_swallows_failure(monkeypatch):
    monkeypatch.setattr(deck_themes, "theme_counts",
                        lambda d: (_ for _ in ()).throw(RuntimeError("boom")))
    assert deck_themes.stats_block({}, _goblin(5)) == {}
