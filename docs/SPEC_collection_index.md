# SPEC — `collection_index.py`

/no_think

Write the complete Python module `collection_index.py` for the Myth Forge repo.
Output ONLY the code in a single ```python fenced block. No prose.

## Purpose

The collection CSV stores only `name, count, set, cn`. The collection browser therefore
cannot filter or sort by anything but the name. This module attaches card metadata to
collection rows **entirely offline**, from two card stores already on disk, so browsing
never touches the network.

Verified coverage against the live 1040-row collection: **917 of 917** distinct card
names resolve from these two stores. Offline is not a degraded mode here — it is the
mode.

## Imports allowed

`from __future__ import annotations`, `json`, `re`, `functools`, `pathlib.Path`, and
`from app_paths import app_path`. Nothing else. Do NOT import `typing` — with the future
import, write `dict[str, int]` / `list[dict]` directly with no import at all.

**Every path must go through `app_path(*parts)`.** A bare `Path("data/cards_slim.json")`
resolves against the process working directory and is a bug the repo has a test for.

## The two stores (shapes verified — do not invent fields)

**A. `app_path("cache", "scryfall_cards.json")`** — a flat dict mapping a lookup name
(lower-cased) to a full Scryfall card object. ~1,500 entries. Carries everything:
`name, mana_cost, cmc, type_line, oracle_text, colors, color_identity, rarity, set,
set_name, edhrec_rank, game_changer, layout, image_uris, legalities, prices, keywords`.

**B. `app_path("data", "cards_slim.json")`** — `{"schema": int, "cards": [...]}`, ~34,800
cards. Each card carries ONLY:
`name, mana_cost, type_line, oracle_text, colors, color_identity, produced_mana, power,
toughness, edhrec_rank, game_changer, layout, oracle_id`.

**Store B has no `cmc`, no `rarity`, and no `set_name`.** Derive `cmc` from `mana_cost`;
leave `rarity` and `set_name` as `None` when only store B has the card. Do not guess them.

Store A is richer, so it wins when a name is in both.

## Name keying

```python
def index_key(name: str) -> str
```
Front face, casefolded: strip whitespace, take the part before `//` if present, casefold.
(This mirrors `collection.owned_key`; reimplement it here so this module has no import
cycle with `collection`.)

## 1. `mana_value(mana_cost: str) -> int`

Converted mana cost from a `{...}` cost string. **This is MTG-rules-facing; a wrong value
is a defect, not an approximation.** Your implementation must reproduce this table
exactly — include it as a comment block above the function:

```
    ""            -> 0     (no cost / lands)
    "{0}"         -> 0
    "{3}"         -> 3
    "{10}"        -> 10    (multi-digit generic, not 1 and 0)
    "{W}"         -> 1
    "{C}"         -> 1     (colorless mana symbol still costs 1)
    "{2}{W}{U}"   -> 4
    "{X}{R}"      -> 1     (X counts as 0 outside the stack)
    "{X}{X}{G}"   -> 1
    "{W/U}"       -> 1     (hybrid colour/colour)
    "{2/W}"       -> 2     (monocolour hybrid = the HIGHER half, rule 202.3b)
    "{W/P}"       -> 1     (Phyrexian)
    "{1}{G} // {G}" -> 2   (MDFC: FRONT face only)
```

Implementation notes:
- Split on `//` first and keep only the front face.
- Find every `{...}` group with a regex.
- For a group containing `/`, split on `/` and take the max value of the halves, where a
  numeric half is its integer value, `P` (Phyrexian) is 0, and any colour letter is 1.
  So `{2/W}` -> max(2, 1) = 2 and `{W/U}` -> max(1, 1) = 1 and `{W/P}` -> max(1, 0) = 1.
- A purely numeric group is its integer value.
- `X`, `Y`, `Z` are 0.
- Any other single symbol (`W U B R G C S`) is 1.
- Return an `int`. Never raise — an unparseable cost returns 0.

## 2. `primary_type(type_line: str) -> str`

The one bucket a card belongs in for browsing. Check the type line (case-insensitive,
front face only — split on `//`) in **this precedence order** and return the first hit:

```
Land, Creature, Planeswalker, Battle, Instant, Sorcery, Enchantment, Artifact
```
Anything else returns `"Other"`.

Precedence matters and this order is deliberate: an *Artifact Creature* is a Creature, an
*Enchantment Creature* is a Creature, and an *Artifact Land* is a Land. Put a comment
saying so.

## 3. `load_card_index() -> dict[str, dict]`

Build `{index_key(name): meta}` merging both stores, store A winning. Decorate it with
`functools.lru_cache(maxsize=1)` so the 16 MB parse happens once per process.

Each `meta` value is exactly:

```python
{
  "name":           str,          # canonical spelling from the store
  "mana_cost":      str,
  "cmc":            int,          # store A's `cmc` (as int) else mana_value(mana_cost)
  "type_line":      str,
  "type":           str,          # primary_type(type_line)
  "colors":         list[str],
  "color_identity": list[str],
  "rarity":         str | None,
  "set":            str | None,   # upper-cased store A `set`, else None
  "set_name":       str | None,
  "edhrec_rank":    int | None,
  "game_changer":   bool,
  "is_land":        bool,         # type == "Land"
}
```

A missing or unreadable store is not an error — skip it and use whatever loaded. If both
fail, return `{}`.

## 4. `enrich_row(row: dict, index: dict) -> dict`

Return a NEW dict: the row's own keys, plus the meta fields above, plus
`"resolved": bool`. Never mutate the input.

- The row's own `name`, `count`, `set`, `cn`, `price` and `_extra` always win over the
  meta — the collection knows which printing the user owns; the index only knows the card.
  So take `set` from the row when the row has one, and only fall back to the meta's `set`.
- On a miss (`resolved=False`), fill: `cmc=0`, `type="Other"`, `colors=[]`,
  `color_identity=[]`, `rarity=None`, `set_name=None`, `edhrec_rank=None`,
  `game_changer=False`, `is_land=False`, `type_line=""`, `mana_cost=""`.

## 5. `enrich_rows(rows: list[dict], index: dict | None = None) -> list[dict]`

Map `enrich_row` over the rows. `index=None` means call `load_card_index()`.

## 6. `color_bucket(colors: list[str]) -> str`

`"Colorless"` for an empty list, `"Multicolor"` for two or more, else the single letter
(`"W"`, `"U"`, `"B"`, `"R"`, `"G"`).

## 7. `facets(rows: list[dict]) -> dict`

Over ENRICHED rows, the filter values actually present plus how many distinct rows carry
each — so the UI only ever offers filters that match something.

```python
{
  "colors":   [{"key": "W", "count": n}, ...],   # by color_bucket; WUBRG, then
                                                 # Multicolor, then Colorless
  "types":    [{"key": "Creature", "count": n}, ...],   # count desc, then key asc
  "rarities": [{"key": "rare", "count": n}, ...],       # common, uncommon, rare,
                                                        # mythic, special, bonus order;
                                                        # unknown rarity is omitted
  "sets":     [{"key": "TLA", "count": n}, ...],        # count desc, then key asc
  "cmc_max":  int,                                       # highest cmc present, min 0
  "unresolved": n,
}
```

## 8. `filter_rows(rows, q=None, colors=None, types=None, rarities=None, sets=None, cmc_min=None, cmc_max=None, min_count=None) -> list[dict]`

Every criterion is optional; `None` or an empty collection means "no constraint". All
supplied criteria are ANDed; values *within* one criterion are ORed.

- `q` — case-insensitive substring of the row `name`.
- `colors` — a collection of bucket keys, matched against `color_bucket(row["colors"])`.
- `types` / `rarities` / `sets` — membership, case-insensitively for `sets`.
- `cmc_min` / `cmc_max` — inclusive bounds on `cmc`.
- `min_count` — inclusive lower bound on `count` (this is the "show me my duplicates" lever).

## 9. `sort_rows(rows, sort="name", direction="asc") -> list[dict]`

Return a new sorted list. Supported `sort` keys, with the tiebreak each uses:

```
"name"   -> casefolded name
"count"  -> count,          tiebreak name
"cmc"    -> cmc,            tiebreak name
"price"  -> price,          tiebreak name   (a None price sorts LAST in both directions)
"value"  -> price * count,  tiebreak name   (same None handling)
"edhrec" -> edhrec_rank,    tiebreak name   (a None rank sorts LAST in both directions)
"type"   -> type,           tiebreak name
"set"    -> set or "",      tiebreak name
```

An unknown `sort` falls back to `"name"`. `direction="desc"` reverses, **except** that
rows with a `None` price / rank must stay at the end either way — they are "unknown",
not "worst". Do this by sorting on a `(is_none, value)` tuple and reversing only the
value component, not the flag.

## Module docstring

Two or three sentences on purpose, then this line verbatim:

```
    Verified offline coverage: 917/917 distinct names in the live 1040-row collection.
```

## Style

Match the repo: `from __future__ import annotations` first, 4-space indent, ~95 column
lines, double quotes, lower_snake_case, type hints on every public function, a short
docstring on every public function. Comments explain *why*, not *what*.
