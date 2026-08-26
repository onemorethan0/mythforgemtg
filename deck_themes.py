"""Derive a deck's archetypes from the CARDS IN IT, not only its commander's oracle text.

`commander_analysis._detect_themes` reads the commander's oracle text and nothing else. For
a fresh build that is the only signal there is. But once a deck EXISTS — an import, an
"Analyze a Deck", an Edit & Rebuild — the 99 cards describe what the deck is actually doing
far better than one card's rules text, and the two routinely disagree.

A RAW COUNT IS NOT EVIDENCE. Measured on corpus/decks, with each theme's lift over what a
random pile of the same size would produce (see BASE_RATE):

| commander                  | commander themes    | deck STRONG (lift)              | detected  |
|----------------------------|---------------------|---------------------------------|-----------|
| Shelob, Child of Ungoliant | tokens, ARISTOCRATS | tokens 15 (1.7x), graveyard 7   | []        |
|                            |                     | (1.4x), voltron 7 (0.5x)        |           |
| Ghired, Conclave Exile     | tokens, voltron     | tokens 39 (3.9x), voltron 6     | [tokens]  |
|                            |                     | (0.4x), counters 4 (0.5x)       |           |
| Brudiclad, Telchor Engineer| tokens              | tokens (5.2x), voltron (0.6x)   | [tokens]  |
| Jegantha, the Wellspring   | [] (none)           | nothing above 1.2x              | []        |

- GHIRED AND BRUDICLAD ARE THE REAL SIGNAL. 39 token cards at 3.9x, and 5.2x — those decks
  genuinely are token decks.
- SHELOB IS THE CONTEXT-COLLAPSE CASE. Its commander text declares `aristocrats` and the
  deck holds exactly ONE aristocrats card, so `merge_themes` demotes it. Its 15 token cards
  look like a theme until you notice that is only 1.7x what chance gives you, so the honest
  answer is `[]` — an under-count rather than a confident fabrication.
- VOLTRON_COMBAT AT 0.4-0.6x ON EVERY DECK is why BASE_RATE exists. Real decks play it LESS
  than random, yet the original absolute "3 STRONG cards" rule detected it on 100% of
  randomly drawn 60-card piles. Same for tokens (92.5%), counters (90%) and graveyard (70%).
  Those detections were noise, and they shipped before this was measured.

This module DESCRIBES; it does not decide. Callers merge its output with the commander's —
see `merge_themes`.
"""

from __future__ import annotations

import theme_match

# An absolute floor: below this a "theme" is two or three cards, whatever the ratio says.
# It also rejects Shelob's `enchantress` (0 STRONG / 8 WEAK) — incidental matches with no
# payoff card are not an archetype, which is why WEAK can only ever tie-break.
MIN_STRONG = 3
# A WEAK match is a tie-break, never evidence. Measured over 120 corpus decks it changes
# the detected themes on 5 of them at 0.1 (4 at 0.05, 7 at 0.5, saturating there), so it is
# genuinely a tie-break and not inert. There is no ground truth for which theme is "right"
# in a tie, so this value is NOT calibratable the way LIFT_FACTOR and BASE_RATE are — it is
# a judgement that WEAK membership is weak evidence, held small on purpose.
WEAK_WEIGHT = 0.1
DEFAULT_TOP_N = 3        # DeckBuilder uses at most 3 active themes

# How far above its BASE_RATE expectation a theme must sit to count. CALIBRATED, not
# picked — swept over 89 corpus decks against 40 random 80-card piles:
#
#   factor   real decks with >=1 theme   random piles with >=1
#     1.0            77.5%                      97.5%
#     1.5            53.9%                      40.0%
#     2.0            47.2%                       7.5%   <- knee
#     2.5            40.4%                       7.5%
#     3.0            38.2%                       7.5%
#
# 2.0 is where the random false-positive rate collapses and then goes flat, so it buys the
# most real coverage at the lowest achievable noise floor. The residual 7.5% is a
# small-numbers artifact: a rare theme can pick up 3 hits where fewer than one is expected.
LIFT_FACTOR = 2.0

# Share of ALL non-basic cards that score STRONG for each theme, measured over the
# 34,846-card store. Regenerate with `python scripts/theme_base_rates.py` (`--check` diffs
# against this table) after editing theme_match rules or refreshing card data.
#
# THIS TABLE IS THE POINT. The themes are wildly different sizes: `voltron_combat` scores
# STRONG on 19.35% of every card in Magic, so an absolute "3 STRONG cards means the deck
# has this theme" rule fired on a randomly drawn 60-card pile 100% of the time, with
# tokens/counters/graveyard at 92.5%/90%/70%. Real corpus decks run voltron_combat at
# 0.4-0.6x base rate — FEWER than random — so every one of those detections was noise.
BASE_RATE: dict[str, float] = {
    "aristocrats": 0.01320,
    "artifacts": 0.00014,
    "auras": 0.00020,
    "chaos": 0.01234,
    "counters": 0.09878,
    "draw_matters": 0.00356,
    "enchantress": 0.00158,
    "energy": 0.00419,
    "etb": 0.00482,
    "face_down": 0.00987,
    "graveyard": 0.06497,
    "group_hug": 0.00175,
    "impulse": 0.01289,
    "landfall": 0.00611,
    "lifegain": 0.00258,
    "reanimator": 0.00798,
    "sagas": 0.00752,
    "spellslinger": 0.00600,
    "theft": 0.00760,
    "tokens": 0.11783,
    "tribal_angels": 0.00141,
    "tribal_beasts": 0.00146,
    "tribal_cats": 0.00138,
    "tribal_demons": 0.00115,
    "tribal_dinosaurs": 0.00187,
    "tribal_dragons": 0.00419,
    "tribal_elves": 0.00385,
    "tribal_goblins": 0.00482,
    "tribal_humans": 0.00577,
    "tribal_knights": 0.00224,
    "tribal_merfolk": 0.00224,
    "tribal_ninjas": 0.00086,
    "tribal_slivers": 0.00350,
    "tribal_soldiers": 0.00471,
    "tribal_spirits": 0.00531,
    "tribal_vampires": 0.00296,
    "tribal_warriors": 0.00502,
    "tribal_werewolves": 0.00172,
    "tribal_wizards": 0.00261,
    "tribal_wolves": 0.00086,
    "tribal_zombies": 0.00505,
    "voltron": 0.00011,
    "voltron_combat": 0.19354,
}


def theme_lift(theme: str, strong: int, scored: int) -> float:
    """How many times more often this deck plays `theme` than a random pile would.

    1.0 is exactly what chance would give you. Returns `inf` for a theme with no measured
    base rate — a theme added to `theme_match` before the table was regenerated is judged
    on MIN_STRONG alone rather than silently discarded.
    """
    expected = BASE_RATE.get(theme, 0.0) * scored
    if expected <= 0:
        return float("inf")
    return strong / expected


def _is_basic_land(card: dict) -> bool:
    """Both words, not just "basic" — a card can say Basic without being a land."""
    tl = (card.get("type_line") or "").casefold()
    return "basic" in tl and "land" in tl


def _scored_card_count(deck: list[dict]) -> int:
    """How many distinct non-basic cards `theme_counts` actually looked at.

    The denominator for `theme_lift`, so it must be counted exactly the same way
    `theme_counts` filters — same dedupe, same basic-land skip.
    """
    seen: set[str] = set()
    for card in deck:
        name = (card.get("name") or "").casefold()
        if name and name not in seen and not _is_basic_land(card):
            seen.add(name)
    return len(seen)


def theme_counts(deck: list[dict]) -> dict[str, tuple[int, int]]:
    """`{theme: (strong_count, weak_count)}`, omitting themes nothing matched.

    `quantity` is ignored on purpose: four copies of one token-maker is not four token
    cards, and Commander is singleton anyway outside basics. Cards are deduplicated by
    name, and basics are skipped — they match nothing and only add work.

    `theme_match.theme_score(card, theme)` is local and offline, so this is a pure scan.
    """
    counts: dict[str, list[int]] = {}
    seen: set[str] = set()
    for card in deck:
        name = (card.get("name") or "").casefold()
        if not name or name in seen or _is_basic_land(card):
            continue
        seen.add(name)
        for theme in theme_match.THEMES:
            score = theme_match.theme_score(card, theme)
            if score == theme_match.NO_MATCH:
                continue
            slot = counts.setdefault(theme, [0, 0])
            slot[0 if score == theme_match.STRONG else 1] += 1
    return {theme: (s, w) for theme, (s, w) in counts.items()}


def detect_deck_themes(
    deck: list[dict],
    *,
    top_n: int = DEFAULT_TOP_N,
    min_strong: int = MIN_STRONG,
) -> list[str]:
    """The deck's own archetypes, strongest first.

    A theme must clear BOTH bars: `min_strong` STRONG cards in absolute terms, AND
    `LIFT_FACTOR` times the count a random pile of the same size would produce. The second
    is what makes the answer mean anything — see BASE_RATE. Ranked by
    `strong + WEAK_WEIGHT * weak`, ties broken on theme name ASCENDING for reproducibility.
    """
    counts = theme_counts(deck)
    scored = _scored_card_count(deck)
    qualifying = [
        (strong + WEAK_WEIGHT * weak, theme)
        for theme, (strong, weak) in counts.items()
        if strong >= min_strong and theme_lift(theme, strong, scored) >= LIFT_FACTOR
    ]
    # Sort on (-score, name): negating the score keeps the name ascending, which
    # `reverse=True` on a plain tuple would have flipped.
    qualifying.sort(key=lambda sw: (-sw[0], sw[1]))
    return [theme for _score, theme in qualifying[:top_n]]


def merge_themes(
    commander_themes: list[str],
    deck_themes: list[str],
    *,
    deck_counts: dict[str, tuple[int, int]] | None = None,
    deck_scored: int | None = None,
    limit: int = DEFAULT_TOP_N,
    min_strong: int = MIN_STRONG,
) -> list[str]:
    """Blend the commander's stated plan with what the deck actually plays.

    Order is a real budget decision, not cosmetics: `_fetch_theme_synergy_list` gives the
    LEAD theme the slot remainder.

    THREE TIERS, because plain commander-first is not good enough:

      1. commander themes the DECK SUPPORTS (>= `min_strong` STRONG cards)
      2. deck themes not already listed
      3. commander themes the deck does NOT support

    Tier 3 is the point. Shelob's commander text declares `aristocrats` and the deck holds
    exactly ONE aristocrats card; commander-first kept that theme and spent a slot chasing
    a plan the deck does not have — the very failure deck context exists to fix. It is
    demoted rather than dropped, because a user rebuilding may be building TOWARD it.

    Passing no `deck_counts` disables the demotion and restores plain commander-first,
    which is correct when there is no deck to read (a fresh build).
    """
    supported: list[str] = []
    unsupported: list[str] = []
    for theme in commander_themes or []:
        if not theme:
            continue
        strong = (deck_counts or {}).get(theme, (0, 0))[0]
        # "Supported" has to mean the SAME thing detect_deck_themes means by it, or a
        # theme could be demoted by one test and kept by the other. `deck_scored` carries
        # the real denominator when the caller has it; without it the absolute floor
        # alone decides. No counts at all -> nothing is contradicted, so everything
        # stays tier 1 (correct for a fresh build with no deck to read).
        ok = strong >= min_strong and (
            deck_scored is None
            or theme_lift(theme, strong, deck_scored) >= LIFT_FACTOR
        )
        (supported if deck_counts is None or ok else unsupported).append(theme)

    merged: list[str] = []
    for theme in supported + list(deck_themes or []) + unsupported:
        if theme and theme not in merged:
            merged.append(theme)
    return merged[:limit]


def stats_block(commander: dict, deck: list[dict],
                partners: list[dict] | None = None) -> dict:
    """The `compute_stats` integration point, mirroring `lift_stats.stats_block`.

    Unlike that one this is PURE and OFFLINE — `theme_match` is a local text scan — so it
    costs nothing on any path and never waits on a third party. Returns `{}` when there is
    nothing to describe, or on any exception: a descriptive figure must never fail a build.
    """
    try:
        if not deck:
            return {}
        counts = theme_counts(deck)
        detected = detect_deck_themes(deck)
        cmdr: list[str] = []
        if commander:
            # Imported decks can carry a commander dict with no oracle text at all, and a
            # 60-card list may carry none whose front face is legendary; both are fine.
            # The whole command zone: a partner pair's plan comes from BOTH halves,
            # and reading the lead alone is why Tymna and Falthis report no themes.
            from commander_analysis import build_commander_profile
            cmdr = list(build_commander_profile(commander, partners).themes)
        merged = merge_themes(cmdr, detected, deck_counts=counts,
                              deck_scored=_scored_card_count(deck))
        if not merged:
            return {}
        return {"commander": cmdr, "deck": detected, "merged": merged}
    except Exception:      # noqa: BLE001 - descriptive only, never fails a build
        return {}
