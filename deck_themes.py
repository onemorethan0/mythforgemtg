"""Derive a deck's archetypes from the CARDS IN IT, not only its commander's oracle text.

`commander_analysis._detect_themes` reads the commander's oracle text and nothing else. For
a fresh build that is the only signal there is. But once a deck EXISTS — an import, an
"Analyze a Deck", an Edit & Rebuild — the 99 cards describe what the deck is actually doing
far better than one card's rules text, and the two routinely disagree.

Measured on corpus/decks (STRONG counts via theme_match.theme_score):

| commander                  | commander themes      | deck STRONG counts                    |
|----------------------------|-----------------------|---------------------------------------|
| Shelob, Child of Ungoliant | tokens, ARISTOCRATS   | tokens 15, graveyard 7, voltron 7,     |
|                            |                       | counters 5, ARISTOCRATS 1             |
| Ghired, Conclave Exile     | tokens, voltron_combat| tokens 39, voltron_combat 6, counters 4|
| Jegantha, the Wellspring   | [] (none)             | voltron_combat 7, tokens 5, graveyard 5|

- SHELOB IS THE CONTEXT-COLLAPSE CASE. The commander's text says `aristocrats`; the deck
  contains exactly ONE aristocrats card. Rebuilding on the commander's themes chases a plan
  the deck does not have.
- GHIRED IS THE AGREEMENT CASE. 39 token cards — the commander was right, and deck context
  must not thrash an answer that is already correct.
- JEGANTHA IS THE EMPTY CASE. A companion with no detectable oracle theme gets no plan at
  all today; its deck plainly has three.

This module DESCRIBES; it does not decide. Callers merge its output with the commander's,
and the commander's themes stay first — see `merge_themes`.
"""

from __future__ import annotations

import theme_match

# A theme needs this many STRONG cards before it counts as a theme at all. Calibrated on
# the table above: admits Shelob's counters (5) and graveyard (7), rejects its
# aristocrats (1). It also rejects Shelob's `enchantress`, which scores 0 STRONG and 8
# WEAK — eight incidental matches with no payoff card is not an archetype, which is
# exactly why WEAK must never promote a theme on its own.
MIN_STRONG = 3
WEAK_WEIGHT = 0.1        # a WEAK match is a tie-break, never evidence
DEFAULT_TOP_N = 3        # DeckBuilder uses at most 3 active themes


def _is_basic_land(card: dict) -> bool:
    """Both words, not just "basic" — a card can say Basic without being a land."""
    tl = (card.get("type_line") or "").casefold()
    return "basic" in tl and "land" in tl


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

    A theme qualifies only on STRONG evidence (`min_strong`); WEAK matches then order the
    survivors. Ties break on theme name ASCENDING so the result is reproducible.
    """
    qualifying = [
        (strong + WEAK_WEIGHT * weak, theme)
        for theme, (strong, weak) in theme_counts(deck).items()
        if strong >= min_strong
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
        # No counts at all -> nothing is contradicted, so everything stays tier 1.
        (supported if deck_counts is None or strong >= min_strong else unsupported).append(theme)

    merged: list[str] = []
    for theme in supported + list(deck_themes or []) + unsupported:
        if theme and theme not in merged:
            merged.append(theme)
    return merged[:limit]


def stats_block(commander: dict, deck: list[dict]) -> dict:
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
            from commander_analysis import build_commander_profile
            cmdr = list(build_commander_profile(commander).themes)
        merged = merge_themes(cmdr, detected, deck_counts=counts)
        if not merged:
            return {}
        return {"commander": cmdr, "deck": detected, "merged": merged}
    except Exception:      # noqa: BLE001 - descriptive only, never fails a build
        return {}
