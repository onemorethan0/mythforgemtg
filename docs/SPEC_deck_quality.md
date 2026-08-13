# SPEC — `deck_quality.py`

Write ONE new Python file: `deck_quality.py`, at the repo root of Myth Forge.

**Self-contained, pure, offline.** Standard library only (`re`, `dataclasses`, `typing`,
`collections`, `math`). **No network. No imports from any other project module.**

Output **only the contents of `deck_quality.py`**, in a single ```python fenced block.
No prose. `/no_think`

---

## 1. Why this module exists

Myth Forge's `DeckBuilder` fills 99 slots by functional role (ramp / draw / removal /
wipe / protection / finisher / theme / goodstuff), each drafted EDHREC-best-first. It has
**no notion of mana curve and no notion of whether the manabase can actually cast the
deck.** Two consequences we have measured on real output:

* A deck can draft twelve six-drops because they happen to rank well, and stall.
* A `{B}{B}{B}` card can land in a deck whose manabase produces black from nine sources.

This module supplies the two missing measurements as **pure functions over a finished or
partial decklist**, so the builder can consult them while drafting and the UI can report
them afterward. It decides nothing on its own — it measures and recommends.

---

## 2. Card dict shape (VERIFIED — do not invent fields)

```python
{
  "name": "Blasphemous Act",
  "mana_cost": "{8}{R}",              # may be "" for lands; may be absent
  "type_line": "Sorcery",
  "oracle_text": "...",
  "cmc": 9.0,                          # may be absent -> derive from mana_cost
  "color_identity": ["R"],
  "produced_mana": ["R"],              # PRESENT ON LANDS AND ROCKS; may be absent
  "card_faces": [ {...} ],             # split/DFC only
  "quantity": 1,                       # aggregated duplicates (basics!) — may be absent, default 1
}
```

**`quantity` is load-bearing.** Basic lands are aggregated into ONE dict with
`quantity: 14`. Any count over a decklist MUST sum `quantity`, never `len()`. Getting this
wrong makes a 36-land deck look like a 10-land deck.

---

## 3. Required public API — EXACT signatures

```python
WUBRG: str = "WUBRG"

def qty(card: dict) -> int: ...
    """int(card['quantity']) or 1. Never returns < 1."""

def mana_value(card: dict) -> int: ...
    """card['cmc'] as int if present, else parsed from mana_cost.
    Hybrid {2/W} counts as its HIGHEST half (rule 202.3b) -> 2.
    {X} counts as 0. Phyrexian {R/P} counts as 1."""

def pip_counts(card: dict) -> dict[str, int]: ...
    """Coloured pips in the mana cost, e.g. {'B': 2, 'R': 1}. A hybrid {B/R} adds
    0.5 to neither — it adds 1 to BOTH keys, because either colour can pay it and
    the source count must treat it as satisfiable by either. Generic and {X} are
    not pips. Returns only non-zero keys."""

def is_land(card: dict) -> bool: ...

def curve(deck: list[dict]) -> dict[int, int]: ...
    """Mana-value histogram of NONLAND cards, quantity-weighted. Values 7+ are
    bucketed into key 7. Keys with zero count are omitted."""

@dataclass(frozen=True)
class CurveVerdict:
    average:  float                 # average MV of nonland cards, 2dp
    buckets:  dict[int, int]
    target:   dict[int, int]        # the ideal for this deck size / commander MV
    over:     dict[int, int]        # bucket -> how many TOO MANY
    under:    dict[int, int]        # bucket -> how many TOO FEW
    verdict:  str                   # "ok" | "top-heavy" | "too-flat"
    notes:    list[str]             # human-readable, at most 3

def curve_target(nonland_count: int, commander_mv: int) -> dict[int, int]: ...
    """The reference curve. Base shape for a ~63-card nonland Commander deck:
       MV 1 -> 8%,  2 -> 19%,  3 -> 21%,  4 -> 17%,  5 -> 13%,  6 -> 10%,  7+ -> 12%
    Scale by nonland_count, then shift: for every point of commander_mv above 4,
    move 1 slot from bucket 6 and 1 from bucket 7 down into buckets 2 and 3 (a
    seven-drop commander needs a cheaper deck under it, not a heavier one). Never
    let any bucket go below 0. The returned counts must SUM EXACTLY to
    nonland_count — assign any rounding remainder to bucket 3."""

def assess_curve(deck: list[dict], commander_mv: int) -> CurveVerdict: ...
    """verdict is "top-heavy" when buckets 5+6+7 exceed their combined target by
    more than 15% of nonland_count; "too-flat" when buckets 1+2 fall short of
    their combined target by more than 15%; otherwise "ok"."""

@dataclass(frozen=True)
class ColorVerdict:
    pips:      dict[str, int]        # total coloured pips demanded by the deck
    sources:   dict[str, int]        # lands + rocks that can produce each colour
    required:  dict[str, int]        # sources needed to cast reliably
    short:     dict[str, int]        # colour -> deficit (omitted when covered)
    ok:        bool
    notes:     list[str]

def color_sources(deck: list[dict]) -> dict[str, int]: ...
    """Quantity-weighted count of permanents that can produce each colour. A card
    counts when its `produced_mana` contains the colour, OR (when produced_mana is
    absent) its oracle text has an `Add` ability naming that colour, OR names
    'any color' / 'mana of any color' — which counts for EVERY colour in WUBRG.
    Count LANDS and nonland mana sources (rocks, dorks) alike; a Signet fixes
    colour just as a dual does. A card is counted ONCE per colour, not once per
    Add ability."""

def required_sources(pips: dict[str, int], nonland_count: int) -> dict[str, int]: ...
    """How many sources each colour needs. Use the accepted Frank Karsten shape,
    simplified for a 100-card singleton deck and expressed as a table on the
    HEAVIEST pip requirement seen for that colour, not the total:
        1 pip at MV<=3   -> 15 sources
        1 pip at MV>=4   -> 13
        2 pips (e.g. {B}{B}) -> 20
        3 pips           -> 23
    Since this function receives only totals, approximate: treat a colour whose
    pip total is >= 2.5x the deck's per-colour mean as a 'heavy' colour needing 20,
    a colour with any pips at all as needing 15, and scale all of it by
    nonland_count/63 so a bigger nonland count doesn't inflate the requirement.
    Round to the nearest int. Colours with 0 pips are omitted."""

def assess_colors(deck: list[dict], commander: dict) -> ColorVerdict: ...
    """Commander pips COUNT — you must cast it. ok is True when `short` is empty."""

def suggest_cuts(deck: list[dict], verdict: CurveVerdict, limit: int = 8) -> list[dict]: ...
    """When the curve is top-heavy, the nonland cards most worth cutting: drawn
    from the OVER-full buckets, worst EDHREC rank first (highest number = least
    played), never a land, never more than `limit`. Returns the card dicts
    themselves. Empty list when the curve is 'ok'."""
```

---

## 4. Worked examples your output must satisfy

Put these in the module docstring as a comment table.

| Input | Expectation |
|---|---|
| `mana_value({"mana_cost": "{2/W}{2/W}"})` | `4` — hybrid takes the higher half, twice |
| `mana_value({"mana_cost": "{X}{R}{R}"})` | `2` — X is 0 |
| `mana_value({"mana_cost": "{R/P}"})` | `1` |
| `pip_counts({"mana_cost": "{5}{B}{R}"})` | `{"B": 1, "R": 1}` |
| `pip_counts({"mana_cost": "{B/R}{B}"})` | `{"B": 2, "R": 1}` — hybrid counts for both |
| `qty({"quantity": 14})` | `14` |
| `curve` over a deck with one `{"cmc": 9, "quantity": 1}` | that card lands in bucket **7** |
| `curve_target(63, 7)` | sums to exactly 63; bucket 6 and 7 each 3 lower than `curve_target(63, 4)`, buckets 2 and 3 each 3 higher |
| `color_sources` on 14 aggregated Mountains (`quantity: 14`) | `{"R": 14}`, not `{"R": 1}` |
| `color_sources` on Command Tower (`produced_mana` absent, text "Add one mana of any color…") | counts +1 for **all five** colours |

---

## 5. Style constraints

* Python 3.14, `from __future__ import annotations`.
* Type-hint every public function. Frozen dataclasses as specified.
* Module docstring: 4–6 lines on purpose + the table from §4.
* Comments say **why**. Where a rule prevents a specific bug, name it
  (`# quantity, not len(): 14 aggregated Mountains are 14 sources`).
* No `print()`, no logging, no I/O, no `__main__` block, no CLI.
* Guard every `.get()` — card dicts may be slim.
* Roughly 240–320 lines including docstrings.

---

## 6. Known failure modes — do not repeat these

These are real bugs from earlier work in this codebase. Each is banned here.

* **Counting `len()` instead of summing `quantity`.** Aggregated basics make this a
  4x error on the manabase. Every count in this module is quantity-weighted.
* **Matching a verb and ignoring its object.** `"Add"` alone is not a mana source —
  require an actual mana symbol or the phrase "mana of any color" near it.
* **Reading an effect without its cost.** Not applicable to counting sources (a
  source is a source regardless of cost), but do NOT count a card twice because it
  has two Add abilities for the same colour.
* **`\d+` where oracle text uses number words.** "Add two mana of any color" —
  accept digits and the words `one|two|three`.
* **Bare substring keyword matches.** `"ward"` matches `Warden`. Use `\b` anchors.
* **A rounding scheme whose buckets do not sum to the input.** `curve_target` must
  sum EXACTLY; assign the remainder deterministically to bucket 3.
