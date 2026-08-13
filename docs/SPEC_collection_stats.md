# SPEC — `collection_stats.py`

/no_think

Write the complete Python module `collection_stats.py` for the Myth Forge repo.
Output ONLY the code in a single ```python fenced block. No prose.

## Purpose

Aggregate an enriched collection into the numbers a "what do I actually own" dashboard
shows: value, colour spread, mana curve, type and rarity breakdown, set spread, and the
most valuable cards. Pure aggregation — no file I/O, no network, no mutation of the input.

## Imports allowed

`from __future__ import annotations`, `collections`, and
`from collection_index import color_bucket`. Nothing else. Do NOT import `typing` — with
the future import you write `dict[str, int]` / `list[dict]` directly with no import at all.

## Input shape (exact — do not invent fields)

Rows are the output of `collection_index.enrich_rows`, so each row has at least:

```python
{"name": str, "count": int, "set": str | None, "cn": str,
 "price": float | None,          # may be absent entirely when prices were never fetched
 "cmc": int, "type": str, "colors": list[str], "color_identity": list[str],
 "rarity": str | None, "edhrec_rank": int | None, "is_land": bool, "resolved": bool}
```

`price` is per single copy, in USD, and is `None` or absent when unknown.

Two words used throughout, keep them straight:
- **distinct** = number of rows (one row is one printing the user owns).
- **copies** = sum of `count` over those rows.

## 1. `row_value(row: dict) -> float`

`price * count`, or `0.0` when `price` is missing/None. Never raises.

## 2. `collection_stats(rows: list[dict], top_n: int = 10) -> dict`

Return exactly this structure:

```python
{
  "totals": {
    "distinct":   int,
    "copies":     int,
    "value":      float,   # rounded to 2dp
    "priced":     int,     # rows with a usable price
    "unpriced":   int,
    "unresolved": int,     # rows where resolved is False
  },

  "colors": [                                  # mutually exclusive buckets; the
    {"key": "W", "label": "White",             # distinct values SUM to totals.distinct
     "distinct": int, "copies": int, "value": float},
    ...
  ],

  "color_presence": [                          # OVERLAPPING: a card counts once per
    {"key": "W", "label": "White",             # colour in its color_identity, so a
     "distinct": int, "copies": int},          # Boros card lands in both W and R.
    ...                                        # This is what "how much white do I own"
  ],                                           # actually means. Always all 5, in WUBRG
                                               # order, even at zero.

  "types":    [{"key": "Creature", "distinct": int, "copies": int}, ...],
  "rarities": [{"key": "rare", "label": "Rare",
                "distinct": int, "copies": int, "value": float}, ...],

  "curve":    [{"cmc": 0, "label": "0", "distinct": int, "copies": int}, ...],
  "sets":     [{"key": "TLA", "distinct": int, "copies": int, "value": float}, ...],

  "top_value": [{"name": str, "set": str, "cn": str, "count": int,
                 "price": float, "total": float}, ...],
}
```

### Ordering and bucketing rules

**`colors`** — bucket each row with `color_bucket(row["colors"])`. Emit in this order,
omitting a bucket with zero rows: `W, U, B, R, G, Multicolor, Colorless`. Labels:
`White, Blue, Black, Red, Green, Multicolor, Colorless`.

**`color_presence`** — iterate `row["color_identity"]`. Always emit all five of
`W U B R G` in that order, including zeroes, so a chart axis is stable across refreshes.

**`types`** — sorted by `distinct` descending, then `key` ascending.

**`rarities`** — emit in the fixed order `common, uncommon, rare, mythic, special, bonus`,
omitting any with zero rows, then append any other non-None rarity seen, sorted
alphabetically. Rows with `rarity` None are excluded entirely (they are unknown, not a
category). Labels are the key capitalized (`"mythic"` -> `"Mythic"`).

**`curve`** — **exclude every row where `is_land` is True.** A mana curve containing
lands is meaningless; put that reason in a comment. Buckets are `0,1,2,3,4,5,6` and a
final `7+` that absorbs everything with `cmc >= 7`. Emit all eight buckets even at zero,
in ascending order. Labels are `"0" … "6"` and `"7+"`.

**`sets`** — key on the row's `set`, upper-cased. Rows with a falsy `set` are grouped
under the key `"—"` (an em dash, meaning "printing unknown"). Sort by `distinct`
descending, then `key` ascending, and return **at most 15** entries.

**`top_value`** — rows with a usable price, sorted by `row_value` descending, then name
ascending; the first `top_n`. `total` is `row_value(row)` rounded to 2dp; `price` rounded
to 2dp. `set` and `cn` fall back to `""` when absent.

### Rounding

Every monetary value in the output is rounded to 2 decimal places with `round(x, 2)`.
Round only at the point of output — accumulate in full precision.

### Empty input

`collection_stats([])` must not raise. It returns the same structure with zeroed totals,
empty `colors` / `types` / `rarities` / `sets` / `top_value`, a full five-entry
`color_presence` at zero, and a full eight-bucket `curve` at zero.

## Module docstring

Two or three sentences on purpose, then this note verbatim:

```
    "distinct" counts rows (printings owned); "copies" sums their counts. The mana
    curve excludes lands. `colors` buckets are mutually exclusive and sum to the
    total; `color_presence` overlaps, because a Boros card is both white and red.
```

## Style

Match the repo: `from __future__ import annotations` first, 4-space indent, ~95 column
lines, double quotes, lower_snake_case, type hints on every public function, a short
docstring on every public function. Comments explain *why*, not *what*. Prefer
`collections.Counter` / `defaultdict` over hand-rolled accumulation.
