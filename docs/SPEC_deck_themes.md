# SPEC — `deck_themes.py` (app root)

Derive a deck's archetypes from the CARDS IN IT, not only from its commander's oracle text.

## Why this exists

`commander_analysis._detect_themes` reads the commander's oracle text and nothing else. For
a fresh build that is the only signal available. But once a deck EXISTS — an import, an
"Analyze a Deck", an Edit & Rebuild — the 99 cards are a far better description of what the
deck is actually doing, and the two routinely disagree.

Measured on `corpus/decks` (STRONG match counts via `theme_match.theme_score`):

| commander | commander themes | deck STRONG counts |
|---|---|---|
| Shelob, Child of Ungoliant | `tokens`, **`aristocrats`** | tokens 15, graveyard 7, voltron_combat 7, counters 5, **aristocrats 1** |
| Ghired, Conclave Exile | `tokens`, `voltron_combat` | tokens 39, voltron_combat 6, counters 4 |
| Jegantha, the Wellspring | **`[]`** | voltron_combat 7, tokens 5, graveyard 5 |

Three things that table shows:

- **Shelob is the context-collapse case.** The commander's text says `aristocrats`; the
  deck contains exactly ONE aristocrats card. Rebuilding it on the commander's themes
  would chase a plan the deck does not have.
- **Ghired is the agreement case.** 39 token cards; the commander was right. Deck context
  must not thrash a theme that is already correct.
- **Jegantha is the empty case.** A companion with no detectable oracle theme gets no plan
  at all today; the deck plainly has three.

**This module DESCRIBES; it does not decide.** Callers merge its output with the
commander's, and the commander's themes stay first — see `merge_themes`.

## Constants

```python
MIN_STRONG = 3       # STRONG cards a theme needs before it counts as a theme at all
WEAK_WEIGHT = 0.1    # a WEAK match is a tie-break, never evidence on its own
DEFAULT_TOP_N = 3    # DeckBuilder uses at most 3 active themes
```

`MIN_STRONG = 3` is calibrated on the table above: it admits Shelob's `counters` (5) and
`graveyard` (7) while rejecting its `aristocrats` (1). It also rejects Shelob's
`enchantress`, which has **0 STRONG and 8 WEAK** — eight incidental matches with no payoff
card is not an archetype, which is exactly why WEAK cannot promote a theme by itself.

## Public API

```python
def theme_counts(deck: list[dict]) -> dict[str, tuple[int, int]]
def detect_deck_themes(deck: list[dict], *, top_n: int = DEFAULT_TOP_N,
                       min_strong: int = MIN_STRONG) -> list[str]
def merge_themes(commander_themes: list[str], deck_themes: list[str],
                 *, limit: int = DEFAULT_TOP_N) -> list[str]
```

### `theme_counts(deck)`
`{theme: (strong_count, weak_count)}` over every theme in `theme_match.THEMES`, omitting
themes with no match at all. Cards are Myth Forge dicts (`name` / `type_line` /
`oracle_text`); scoring is `theme_match.theme_score`, which is local and offline.

- **`quantity` is ignored.** Four copies of one token-maker is not four token cards, and
  Commander is singleton anyway apart from basics.
- Deduplicate by card name (casefolded).
- Skip basic lands.

### `detect_deck_themes(deck, top_n, min_strong)`
Themes with `strong >= min_strong`, ranked by `strong + WEAK_WEIGHT * weak` descending,
ties broken by theme name ascending (determinism). At most `top_n`. `[]` for an empty or
themeless deck.

### `merge_themes(commander_themes, deck_themes, *, deck_counts=None, limit, min_strong)`
Order matters downstream: `DeckBuilder._fetch_theme_synergy_list` gives the LEAD theme the
slot remainder, so first place is a real budget decision.

**Three tiers**, because plain commander-first is not good enough:

1. commander themes the DECK SUPPORTS (`strong >= min_strong`)
2. deck themes not already listed
3. commander themes the deck does NOT support

Tier 3 is the point, and it is a correction to this spec's first draft. Commander-first
kept Shelob's `aristocrats` — declared by the commander's text, supported by exactly ONE
card in the deck — and spent a theme slot chasing a plan the deck does not have, which is
the very failure deck context exists to fix. Demoted rather than dropped, because a user
rebuilding may be building TOWARD that plan.

Passing no `deck_counts` disables demotion and restores plain commander-first, which is
correct when there is no deck to read (a fresh build).

Verified end to end on the three corpus decks above:

| commander | merged result |
|---|---|
| Shelob | `tokens, graveyard, voltron_combat` — phantom `aristocrats` demoted out |
| Ghired | `tokens, voltron_combat, counters` — correct answer untouched |
| Jegantha | `voltron_combat, graveyard, tokens` — a plan where there was none |

### `stats_block(commander, deck) -> dict`
The `compute_stats` integration point, mirroring `lift_stats.stats_block`. Returns
`{"commander": [...], "deck": [...], "merged": [...]}` or `{}` when there is nothing to
say. Reads commander themes via `commander_analysis.build_commander_profile`. Returns `{}`
on any exception — descriptive figures must never fail a build. **Pure and offline**: no
network, unlike `lift_stats.stats_block`.

## Style requirements

- `from __future__ import annotations`, module docstring FIRST (before imports).
- Module docstring carries the measured table above, per house convention
  (`collection_pool.py`, `deck_quality.py`, `theme_match.py`).
- Imports: stdlib + `import theme_match`. Nothing else — no network, no Scryfall, no engine.
- Type-annotate every parameter and return. `list`/`dict`/`tuple` are BUILTINS — never
  import them from `typing`.
- Pure and deterministic. No I/O, no logging, no printing.
