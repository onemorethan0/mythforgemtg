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


# ── base rate / lift ────────────────────────────────────────────────────────────

def _trampler(n: int) -> list[dict]:
    """Cards that score STRONG for voltron_combat — the highest-base-rate theme."""
    return [{"name": f"Big Guy {i}", "type_line": "Creature — Beast",
             "oracle_text": "Trample"} for i in range(n)]


def test_base_rate_covers_every_theme():
    """A theme with no entry falls back to `inf` lift and is judged on MIN_STRONG alone.

    That is a deliberate safe default, not a licence to let the table rot — regenerate
    with `python scripts/theme_base_rates.py` after touching theme_match rules.
    """
    missing = set(theme_match.THEMES) - set(deck_themes.BASE_RATE)
    stale = set(deck_themes.BASE_RATE) - set(theme_match.THEMES)
    assert not missing, f"BASE_RATE missing themes: {sorted(missing)}"
    assert not stale, f"BASE_RATE has themes theme_match no longer defines: {sorted(stale)}"


def test_theme_lift_math():
    # voltron_combat is 19.354% of all cards -> 60 cards expect ~11.6
    assert deck_themes.theme_lift("voltron_combat", 12, 60) == pytest.approx(1.03, abs=0.02)
    assert deck_themes.theme_lift("voltron_combat", 30, 60) == pytest.approx(2.58, abs=0.02)


def test_unknown_theme_is_judged_on_min_strong_alone():
    """A theme added to theme_match before the table is regenerated must not vanish."""
    assert deck_themes.theme_lift("brand_new_theme", 3, 100) == float("inf")


def test_a_theme_at_its_base_rate_is_rejected():
    """THE REGRESSION. voltron_combat scores STRONG on 19.35% of every card in Magic, so
    an absolute 3-card rule fired on 100% of random 60-card piles. Playing it at chance
    rate is not an archetype."""
    at_base = _trampler(12) + _token(48)          # 12/60 voltron ~= its 11.6 expectation
    assert "voltron_combat" not in deck_themes.detect_deck_themes(at_base, top_n=99)


def test_a_theme_well_above_its_base_rate_is_kept():
    above = _trampler(40) + _token(20)             # 40/60 is ~3.4x expectation
    assert "voltron_combat" in deck_themes.detect_deck_themes(above, top_n=99)


def test_a_rare_theme_needs_only_the_absolute_floor():
    """landfall is 0.003% of cards, so 3 copies is already enormous lift — the floor is
    what protects it from firing on one or two incidental matches."""
    assert deck_themes.theme_lift("landfall", 3, 99) > deck_themes.LIFT_FACTOR


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


def test_stats_block_detected_pass_through_is_trusted_verbatim():
    """A caller (deck_builder.compute_stats) that already ran `detect_deck_themes(deck)`
    passes its result straight through instead of stats_block re-deriving it -- proven
    here by handing it a value the real deck could never produce on its own, and
    confirming stats_block used exactly that instead of recomputing."""
    block = deck_themes.stats_block({}, _goblin(5), detected=["not_a_real_theme"])
    assert block["deck"] == ["not_a_real_theme"]


def test_stats_block_detected_none_recomputes():
    """The default (`detected=None`) must reproduce the pre-existing recompute-everything
    behavior exactly -- this is the fallback path a caller's own detection FAILURE relies
    on (see deck_builder.compute_stats: it passes `detected=None` on that path so this
    function gets its own, independent, identically-failing attempt rather than being
    handed a bare `[]` that would read as "genuinely zero themes")."""
    block = deck_themes.stats_block({}, _goblin(5), detected=None)
    assert block["deck"] == ["tribal_goblins"]


def test_stats_block_counts_pass_through_drives_merge_themes_demotion(monkeypatch):
    """`counts` short-circuits the SAME theme_counts(deck) scan `detected` was meant to
    avoid recomputing -- passing `detected` alone still left this function running
    theme_counts a second time (for merge_themes' `deck_counts`). Proven here the same
    way test_merge_demotes_a_commander_theme_the_deck_contradicts proves merge_themes
    itself: a commander theme demotes to unsupported (and out of a 1-slot budget) when
    the SUPPLIED counts say the deck doesn't back it, even though `detected` (the deck's
    own themes) is identical in both cases -- so the difference is attributable to
    `counts`, not `detected`.
    """
    import commander_analysis

    class _FakeProfile:
        themes = ["aristocrats"]

    monkeypatch.setattr(commander_analysis, "build_commander_profile",
                        lambda commander, partners: _FakeProfile())

    supported = deck_themes.stats_block(
        {"name": "fake"}, _goblin(5), detected=["tribal_goblins"],
        counts={"aristocrats": (5, 0), "tribal_goblins": (5, 0)})
    unsupported = deck_themes.stats_block(
        {"name": "fake"}, _goblin(5), detected=["tribal_goblins"],
        counts={"aristocrats": (0, 0), "tribal_goblins": (5, 0)})

    assert supported["merged"][0] == "aristocrats", "counts said the deck backs it -> stays first"
    assert unsupported["merged"][0] == "tribal_goblins", "counts said 0 support -> demoted"
    assert "aristocrats" in unsupported["merged"], "demoted, not dropped -- there's room"
