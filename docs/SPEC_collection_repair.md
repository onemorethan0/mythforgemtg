# SPEC — `collection_repair.py`

/no_think

Write the complete Python module `collection_repair.py` for the Myth Forge repo.
Output ONLY the code in a single ```python fenced block. No prose.

## Purpose

The canonical collection CSV (`Documents/MythSuite/collection.csv`) has accumulated rows
whose **Name column holds a whole decklist line** instead of a card name, because the
bulk-import parser only understood a bare leading integer (`13 Island`), not the `13x`
form. Real rows from the live file:

```
Count,Name,Edition,Collector Number
1,1x Abandoned Air Temple (tla) 263 [Land],,
1,13x Island (msh) 290 [Land],,
1,1x Archaeomancer's Map (fic) 230 [Ramp],,
2,1x Archangel of Tithes (ori) 4 [Protection],,
1,1x Conciliator's Duelist (sos) 182 *F* [Creature],,
7,7x Plains (sos) 273 *F* [Land],,
```

246 of 1040 rows look like this. They are invisible to every consumer, because ownership
is keyed on the normalized name — `owned_key("1x abrade (soa) 37 [removal]")` never
equals `"abrade"`. So collection-aware deck building silently ignores a quarter of the
collection.

This module **diagnoses and proposes** repairs. It never writes files and never repairs
silently — the caller shows the proposals and applies only what the user accepts.

## Imports allowed

`from __future__ import annotations`, `re`, and `from collection import printing_key`.
Nothing else. Do NOT import `typing` — with the future import you write `dict[str, int]`
and `list[dict]` directly, with no import at all.

## Row shape (this is exact — do not invent fields)

A row is what `collection.load_collection()` returns:

```python
{"name": str, "count": int, "set": str, "cn": str}
```

plus an OPTIONAL `"_extra": dict[str, str]` carrying CSV columns the collection module
does not model (MythScanner writes `Condition` / `Language` / `Foil`). Preserve `_extra`
through every transformation.

`printing_key(name, set_code, cn) -> tuple` is imported from `collection`; it returns the
identity of a specific printing. Use it, do not reimplement it.

## 1. `DECORATED_RE`

A module-level compiled `re` pattern (use `re.X` verbose mode with comments) that splits a
decorated name into: optional `qty` (`13x `), the `name`, an optional `(set) cn`, an
optional `*F*` foil marker, and an optional `[Tag]` category suffix.

This exact pattern is already verified against all 1040 live rows — reproduce it:

```python
DECORATED_RE = re.compile(
    r"""^\s*
        (?:(?P<qty>\d+)\s*[xX]\s+)?            # leading "13x "
        (?P<name>.+?)                          # card name (lazy)
        (?:\s*\((?P<set>[A-Za-z0-9]{2,6})\)    # " (msh)"
           (?:\s*(?P<cn>[A-Za-z0-9★-]+))? # " 290"
        )?
        (?:\s*\*(?P<foil>[A-Za-z]{1,2})\*)?    # " *F*" foil, " *E*" etched
        (?:\s*\[(?P<tag>[^\]]*)\])?            # " [Land]"
        \s*$""",
    re.X,
)
```

`ISSUE_KINDS = ("quantity_prefix", "embedded_printing", "foil_marker", "category_suffix")`

## 2. `parse_decorated(raw: str) -> dict`

Run `DECORATED_RE` over `raw`. Return

```python
{"name": str, "qty": int | None, "set": str, "cn": str, "foil": bool, "tag": str}
```

Rules:
- `set` is upper-cased and stripped; `cn` is stripped. Both `""` when absent.
- `foil` is `True` when the `*F*`/`*E*` group matched, else `False`.
- `tag` is the `[...]` content stripped, else `""`.
- `qty` is `int` when the `13x` group matched, else `None`.
- **`name` must never be empty.** The lazy `.+?` can in principle match nothing; if the
  parsed name is blank after stripping, fall back to `raw.strip()` and return
  `qty=None, set="", cn="", foil=False, tag=""` (i.e. treat the row as unparseable
  rather than destroying the name). If the regex does not match at all, do the same.

## 3. `diagnose_row(row: dict, index: int) -> dict | None`

Return `None` when the row is already clean — that is, when `parse_decorated` found no
`qty`, no `set`, no `foil` and no `tag` (the name is just a name).

Otherwise return an issue dict:

```python
{
  "index": index,                 # position in the caller's rows list
  "kinds": [...],                 # subset of ISSUE_KINDS, in ISSUE_KINDS order
  "current":  {"name": ..., "count": ..., "set": ..., "cn": ...},
  "proposed": {"name": ..., "count": ..., "set": ..., "cn": ...},
  "foil": bool,
  "tag": str,
  "count_conflict": bool,
}
```

Which kinds fire:
- `quantity_prefix` when `qty is not None`
- `embedded_printing` when the parsed `set` is non-empty
- `foil_marker` when `foil` is True
- `category_suffix` when `tag` is non-empty

Proposed values:
- `proposed["name"]` = the parsed name.
- `proposed["set"]` = parsed set if non-empty, else the row's existing `set`.
- `proposed["cn"]` = parsed cn if non-empty, else the row's existing `cn`.
- `proposed["count"]` = `qty` when `qty is not None`, else the row's existing `count`.

  **Rationale, keep this as a comment in the code:** the `<n>x` is the quantity the
  user's source decklist stated. The stored `Count` is an import artifact — the old
  parser assigned every `13x …` row a count of 1, so a stored count above 1 means the
  same junk row was merge-imported that many times, NOT that the user owns more copies.
  Multiplying the two would fabricate copies. We take the source quantity and flag the
  disagreement instead of guessing.

- `count_conflict` = `qty is not None and int(row.get("count", 0)) != qty`.

## 4. `diagnose(rows: list[dict]) -> dict`

```python
{
  "issues": [issue, ...],       # in row order
  "rows": len(rows),
  "affected": len(issues),
  "clean": rows - affected,
  "copies_before": sum of every row's current count,
  "copies_after": copies_before, but each affected row contributes its proposed count,
}
```

## 5. `apply_repairs(rows: list[dict], accept: set[int] | None = None) -> tuple[list[dict], dict]`

Return `(new_rows, report)`. Never mutate the input rows or their nested dicts — build
new dicts.

- `accept` is a set of issue `index` values to apply. `None` means apply every issue.
- A row with no issue, or whose index is not accepted, is copied through unchanged.
- A repaired row takes the issue's `proposed` name/count/set/cn.
- When `foil` is True, set `Foil` to `"foil"` inside the row's `_extra` dict (creating
  `_extra` if absent, copying it if present). This is a Moxfield-style column that
  `collection.write_collection` preserves on write.
- **Discard the `tag`.** It is a deckbuilding category from whatever exporter produced
  the line, not collection data.
- **Merge collisions.** After repair two rows can land on the same `printing_key(name,
  set, cn)` — sum their counts into the first occurrence and drop the later row.
  Merge `_extra` shallowly, first row winning on conflicts.

Report:

```python
{"repaired": n,        # rows whose fields changed
 "merged": n,          # rows absorbed into an earlier row
 "copies_before": n,
 "copies_after": n,
 "rows_before": n,
 "rows_after": n}
```

## Module docstring

Open the file with a docstring that states the purpose in two or three sentences and
then includes this worked table verbatim:

```
    "1x Abandoned Air Temple (tla) 263 [Land]"   -> Abandoned Air Temple  x1   TLA 263
    "13x Island (msh) 290 [Land]"                -> Island               x13   MSH 290
    "1x Conciliator's Duelist (sos) 182 *F* [Creature]"
                                                 -> Conciliator's Duelist x1   SOS 182  foil
    "Sol Ring"                                   -> clean, no issue
```

## Style

Match the repo: `from __future__ import annotations` first, 4-space indent, ~95 column
lines, double quotes, lower_snake_case, type hints on every public function, a short
docstring on every public function. Comments explain *why*, not *what*.
