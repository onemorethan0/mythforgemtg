# Collection Printings & Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Written 2026-10-06. Scoped against the live code (`collection.py`, `collection_index.py`,
`server.py` collection routes, `StepCollection.jsx` / `CollectionGrid.jsx`), the live
`MythSuite/collection.csv` (1,205 rows), and the live Scryfall bulk-data API.

**Goal:** Make Myth Forge treat a card's *printing* (set, collector number, finish) as real,
stored, displayed data, and give the collection page proper view modes, grouping and sorting.

**Architecture:** The backend stays the single authority. A new offline **prints store** (Scryfall
`default_cards` → sqlite) resolves each collection row to its exact printing, and
`collection_index` overlays that printing's art, rarity, treatments and finish-aware price.
Grouping and every new sort run **server-side in Python**, where they are pytest-covered and
work with pagination. The frontend adds a persisted view-settings model and one component per
view mode, all drawing cards through one shared `CardFace`.

**Tech Stack:** Python 3.14 / FastAPI / sqlite3 / pytest; React 19 + Vite 8; vitest (new dev dep).

**Spec:** this document, §1–§3. There is no separate spec file.

---

## 1. What exists, measured

Printings are already **half-built**: the CSV is keyed per printing (`printing_key = (name, set,
cn)`), there is a printing picker (`/api/collection/printings`, live Scryfall), a
`PATCH /api/collection/printing`, and an explicit "🖨 Fill printings" backfill. The collection page has
two views (`list`, `grid`) and 8 sort keys, and the view choice is stored in `localStorage['mtg_coll_view']`.

**The headline defect: Forge sees 0 known printings in a file that records 982.** The live
CSV header is

```
Count,Name,Edition,Collector Number,Finish,Condition,Date Added,Language,Edition Name,Edition Code,Multiverse Id,Scryfall ID,Tags
```

`Edition` is blank on **all 1,205** rows. The set code lives in `Edition Code` (982 rows), and
the exact printing is in `Scryfall ID` (982 rows, spot-checked 4/4 correct against the API).
`collection._find_column` picks the first matching header (`edition`), so every row reads as
`set=""`. `Edition Code` and `Scryfall ID` ride along as opaque `_extra` passthrough. The
consequences:

- All 982 rows show "printing unknown". "Fill printings" would overwrite real scanner data with
  the *cheapest* printing.
- `Finish` (785 Normal / 197 Foil) is passthrough. A foil and a nonfoil copy of one printing
  **merge into a single row with the counts summed**, because finish is not in the identity key.
  The decklist `*F*` / `*E*` marker becomes `{"Foil": "foil"}` and loses the etched case.
- A printing change through `set_printing` leaves `Edition Code` / `Scryfall ID` / `Edition Name`
  stale in `_extra`. The file then contradicts itself.

**Display is name-level.** `collection_index.load_card_index()` is keyed by card *name*. So the
grid's `row.image`, `rarity` and `set_name` come from whichever printing the oracle store
happened to cache, not from the printing the user owns. Prices are per printing (the cache is
keyed name+set+cn) but not per finish, so a foil copy is valued at the nonfoil price.

**Offline printing data does not exist.** `scryfall_bulk.py` ingests `oracle_cards`, which has one record
per *card*, not per printing. Verified 2026-10-06: Scryfall's `default_cards` bulk entry has a
`jsonl_download_uri` (`.jsonl.gz`, `compressed_size` 78,777,790). A print record carries `id`,
`set`, `collector_number`, `finishes` (`["nonfoil","foil"]`), `frame_effects`, `full_art`,
`promo`, `promo_types`, `border_color`, `lang`, `released_at`, `rarity`,
`prices.{usd,usd_foil,usd_etched}`, and `image_uris.{small,normal,art_crop,…}`.

## 2. Scope

**In:**
1. **Printing storage:** read every printing column the suite actually writes. Finish, language
   and condition become first-class, and finish joins the row identity. One canonical write
   format, and rows get a stable `row_id`.
2. **Printing data:** an offline prints store, so resolving and displaying a printing needs no network.
3. **Printing display:** the exact printing's art, foil/etched treatment, a rarity-coloured set chip, a
   double-faced card flip, an honest "representative art" marker, finish-aware prices, a richer
   printing picker, and a "versions" grouping that shows every printing of a card together.
4. **Views:** `list` (column chooser), `compact` (dense text), `grid` (full card, S/M/L),
   `tiles` (art crop + info), `stacks` (overlapping columns per group).
5. **Grouping:** none / type / color / mana value / rarity / set / finish / card (versions),
   with per-group subtotals, collapsible.
6. **Sorting:** add rarity, color (WUBRG), release date, collector number, date added and finish,
   plus a secondary sort.
7. **Filters:** finish, treatment, language, and "owned in 2+ printings".

**Out (follow-ups, not this plan):** printings inside *decks* (deck view art, exports with set
codes), the non-English `all_cards` store (non-EN rows resolve to the English printing by
set+cn and are labelled with their language), tradelists and per-copy notes.

## 3. Decisions taken (override before execution if wrong)

| # | Decision | Why |
|---|---|---|
| D1 | Set-code column precedence: `edition code`, `set code`, `setcode`, then `edition`, `set`, `expansion`. Use the **first non-blank** value per row. An `edition`/`set` value is adopted only if it *looks like a code* (2–6 alphanumerics, no spaces). | Deckbox-style files put the set NAME in `Edition`. An unknown set is honest and fixable; a set name stored as a code is not. Same rule as `parse_decorated_line`'s lead-bracket logic. |
| D2 | `Scryfall ID` is authoritative. When present, set and CN are taken from the resolved print if blank. | Verified exact on live data. |
| D3 | Finish is normalized to `nonfoil` / `foil` / `etched` and **is part of the row identity**. | Foil and nonfoil copies have different prices and are different physical cards. |
| D4 | Identity = `(owned_key(name), SET, cn, finish, lang or "en", condition)`. On merge, an incoming row with a **blank condition** merges into the *unique* existing row matching on everything else. Otherwise it becomes a new row. | Matches Moxfield/scanner row granularity without making a plain decklist import fork every row. |
| D5 | Canonical write header: `Count,Name,Edition,Collector Number,Foil,Language,Condition,Scryfall ID`, then the unmodelled extras. `Foil` uses the Moxfield/scanner vocabulary (`""`/`foil`/`etched`, same as MythScanner's `_MOX_FOIL`). The alias columns are **consumed, not passed through**: `Edition Code`, `Set Code`, `Finish`, plus the derivable `Edition Name`, `Set Name`, `Multiverse Id`. | The only way a printing change can't leave stale contradicting columns. Extras like `Date Added` and `Tags` still round-trip. |
| D6 | `row_id = sha1("\x1f".join(identity))[:12]`. Mutating endpoints accept `row_id`. A row_id that no longer exists returns **409** "Collection changed — reload". | The CSV has a second writer (MythScanner). A stale UI must not edit the wrong row. |
| D7 | Prints store is `cache/scryfall_prints.sqlite`, built from `default_cards` and refreshed async at startup when older than 7 days, like `scryfall_bulk`. Digital-only prints and `SKIP_LAYOUTS` are dropped. Kill switch: `MYTHFORGE_SCRYFALL_PRINTS=off`. | Offline-first, same lifecycle the user already has. A ~79 MB download, deleted after build. |
| D8 | A finish with no price is `None`. It **never** falls back to another finish's price. | A foil valued at the nonfoil price is a confident wrong number. |
| D9 | Grouping and sorting are server-side. Groups are computed over the whole filtered set, rows are ordered by group and then sort, and pagination applies after. | Testable in pytest. Totals stay right when a page cuts a group. |
| D10 | Add vitest for pure frontend helpers only. Views are verified in the browser preview. | No frontend test runner exists today. The settings parser handles untrusted localStorage, so it must be pinned. |

## Global Constraints

- Run all Python tests with `python -m pytest tests -q` from the repo root (576 tests pass today). The suite must stay green after every task.
- `collection.csv` writes stay atomic (temp + `os.replace` + `.bak`). This is contract C1, and Scanner and Gauntlet read the file.
- Gauntlet reads names only (`load_owned_names`), so name-level ownership must not change behaviour.
- Browsing never hits the network. The live Scryfall API is a fallback only when the prints store is absent.
- Styling follows the existing inline-style tokens (`c.gold #eab308`, `c.card #1c1917`, `c.border #292524`, `c.panel #0c0a09`, `c.dim #a8a29e`, `c.faint #78716c`).
- Rebuild the frontend with `cd frontend && npm run build` (FastAPI serves `frontend/dist`).
- Commit and push after each task (private repo, standing rule). Stage only the task's files: the tree carries unrelated dirty `corpus/` files.
- Per the global CLAUDE.md, T3, T9 (helpers) and T11 are **offload candidates** (qwen3:14b drafts from the task text, Claude reviews before landing). T1, T2, T4 and T7 stay in Claude: they are surgical changes to shared files.

## Review Focus

1. **Mixed-format CSV rows.** In the live file, `Edition` is blank and `Edition Code` is filled; in a Moxfield file, `Edition` holds the code; in a Deckbox file, `Edition` holds a set name. Each must read correctly, per row. The test is in T1.
2. **The scanner rewrites the CSV while the page is open.** A stale `row_id` must give a 409 and a reload, never an edit to the wrong row. The test is in T2.
3. **The prints store is missing** (first run, offline, kill switch). Everything must degrade to today's behaviour, with the art marked representative, and nothing may raise. The test is in T4.
4. **Double-faced, split and adventure cards.** A transform card or MDFC gets a back image. A split or adventure card (one image, `card_faces` without `image_uris`) gets the top-level image and **no** flip. The test is in T3.
5. **A page cut mid-group, or "Show all" capped at 5000.** Group totals must come from the whole filtered set, not the page. The test is in T7.

---

## Phase A — Printing storage & data (backend)

### Task 1: Read and write every printing column the suite actually writes

**Files:**
- Modify: `collection.py` (column constants, `_parse_rows`, `write_collection`, `parse_decorated_line`, `bulk_import`; add helpers)
- Test: `tests/test_collection_printings.py` (new)

**Interfaces:**
- Produces:
  - `normalize_finish(value: str) -> str`: returns `"nonfoil"|"foil"|"etched"`. `""`, `normal`, `nonfoil`, `non-foil`, `no`, `false` → `nonfoil`; `foil`, `f`, `yes`, `true` → `foil`; `etched`, `e`, `foil etched` → `etched`. Case-insensitive.
  - `row_identity(row: dict) -> tuple` per D4.
  - Every row dict from `load_collection` / `_parse_rows` now carries `name, count, set, cn, finish, lang, condition, scryfall_id` (strings, `finish` always normalized, `lang` lowercased, `set` uppercased), plus `_extra`.
  - `parse_decorated_line` gains `"finish"` (`*F*` → `foil`, `*E*` → `etched`, none → `nonfoil`). Keep the `foil` bool for existing callers.

- [ ] **Step 1: Write the failing tests**

```python
LIVE_HEADER = ("Count,Name,Edition,Collector Number,Finish,Condition,Date Added,Language,"
               "Edition Name,Edition Code,Multiverse Id,Scryfall ID,Tags")

def test_live_scanner_header_reads_edition_code():
    text = LIVE_HEADER + "\n1,Coastal Piracy,,156,Normal,NM,2026-07-16,EN,Tales,tle,0,abc-id,\n"
    (r,) = collection._parse_rows(text)
    assert (r["set"], r["cn"], r["finish"], r["lang"], r["condition"], r["scryfall_id"]) == \
           ("TLE", "156", "nonfoil", "en", "NM", "abc-id")
    assert "Edition Code" not in r.get("_extra", {}) and "Date Added" in r["_extra"]

def test_moxfield_edition_is_a_code():
    (r,) = collection._parse_rows("Count,Name,Edition,Foil,Collector Number\n1,Sol Ring,c21,foil,263\n")
    assert (r["set"], r["finish"]) == ("C21", "foil")

def test_deckbox_edition_name_is_not_adopted_as_a_code():
    (r,) = collection._parse_rows("Count,Name,Edition\n1,Sol Ring,Commander 2021\n")
    assert r["set"] == ""

def test_foil_and_nonfoil_of_one_printing_stay_separate():
    rows = collection._parse_rows("1 Sol Ring (C21) 263\n1 Sol Ring (C21) 263 *F*\n")
    assert sorted((r["finish"], r["count"]) for r in rows) == [("foil", 1), ("nonfoil", 1)]

def test_etched_marker():
    assert collection.parse_decorated_line("1 Sol Ring (CMR) 472 *E*")["finish"] == "etched"

def test_blank_condition_merges_into_unique_conditioned_row(tmp_path):
    p = tmp_path / "c.csv"
    collection.write_collection([{"name": "Sol Ring", "count": 1, "set": "C21", "cn": "263",
                                  "finish": "nonfoil", "lang": "en", "condition": "NM"}], p)
    rows = collection.bulk_import("1 Sol Ring (C21) 263", path=p)
    assert [(r["count"], r["condition"]) for r in rows] == [(2, "NM")]

def test_write_header_is_canonical_and_round_trips(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text(LIVE_HEADER + "\n2,Sol Ring,,263,Foil,NM,2026-07-16,EN,C21,c21,0,id1,Unsure\n",
                 encoding="utf-8-sig")
    collection.write_collection(collection.load_collection(p), p)
    head = p.read_text(encoding="utf-8-sig").splitlines()[0]
    assert head == "Count,Name,Edition,Collector Number,Foil,Language,Condition,Scryfall ID,Date Added,Tags"
    (r,) = collection.load_collection(p)
    assert (r["set"], r["finish"], r["scryfall_id"], r["_extra"]["Tags"]) == ("C21", "foil", "id1", "Unsure")

def test_owned_names_unchanged_by_printing_columns():
    assert collection.parse_owned(LIVE_HEADER + "\n1,Fire // Ice,,1,,,,,,,,,\n") == {"fire"}
```

- [ ] **Step 2: Run them and confirm they fail.** `python -m pytest tests/test_collection_printings.py -q`. Expected: FAIL (`KeyError: 'finish'`, set `""` where `TLE` is expected).

- [ ] **Step 3: Implement.** Replace the single-column lookup with a per-row "first non-blank among all matching headers" read, using the D1 precedence and code-shape check. Add column groups for finish (`finish`, `foil`, `printing`), language (`language`, `lang`), condition (`condition`), scryfall id (`scryfall id`, `scryfall_id`, `scryfallid`). Add a `_CONSUMED` set of derivable columns (`edition name`, `set name`, `multiverse id`) that are dropped rather than put in `_extra`. Switch `_parse_rows`'s merge and `bulk_import`'s merge to `row_identity` plus the D4 blank-condition rule. Write the D5 header. Keep `printing_key` (still used by `collection_repair` and price keys).

- [ ] **Step 4: Run the new tests plus the existing collection checks.** `python -m pytest tests/test_collection_printings.py tests/test_smoke.py -q`. Expected: PASS. If a smoke check pinned the old 4-column header, update that check to the D5 header in this same task.

- [ ] **Step 5: Dry-run against the live file without writing.** `python -c "import collection as c; r=c.load_collection(); print(sum(1 for x in r if x['set']), sum(1 for x in r if x['finish']=='foil'))"`. Expected: `982 197`.

- [ ] **Step 6: Commit.** `git add collection.py tests/test_collection_printings.py tests/test_smoke.py && git commit -m "collection: read the scanner's printing columns; finish joins the row identity"`.

### Task 2: Stable row identity on the API

**Files:**
- Modify: `collection.py` (add id-targeted mutators), `server.py` (collection request models and routes around lines 4850–5100)
- Test: `tests/test_collection_routes.py` (new; `TestClient(server.app)` as in `tests/test_deck_list_route.py`, with `MYTHSUITE_DIR` monkeypatched to `tmp_path`)

**Interfaces:**
- Consumes: `row_identity` (T1).
- Produces:
  - `row_id(row: dict) -> str` (D6).
  - `find_by_id(rows, rid) -> dict | None`.
  - `set_count_by_id(rid, count, path=None) -> list[dict]`, `remove_by_id(rid, path=None) -> list[dict]`. Both raise `KeyError(rid)` when the row is absent.
  - `bulk_apply` targets accept `{"row_id"}` as well as the old `{name,set,cn}`.
  - Every row in `GET /api/collection` responses carries `row_id`.
  - `CollectionCountRequest` and `CollectionTarget` gain `row_id: Optional[str]`. `DELETE /api/collection` gains a `row_id` query param.
  - A `KeyError` from an id mutator becomes `HTTPException(409, "Collection changed — reload.")`.

- [ ] **Step 1: Write the failing tests.** `test_row_id_is_stable_and_finish_sensitive` (the same row gives the same id across loads; foil and nonfoil give different ids). `test_count_by_row_id` (PATCH `/api/collection/count` with `row_id` changes only the foil row). `test_stale_row_id_is_409` (rewrite the CSV behind the client, then PATCH with the old id → `status_code == 409`). `test_bulk_remove_by_row_id`. `test_get_collection_rows_carry_row_id`.
- [ ] **Step 2: Run them and confirm they fail.** `python -m pytest tests/test_collection_routes.py -q`.
- [ ] **Step 3: Implement** the produced interfaces. Old name/set/cn params keep working when `row_id` is absent.
- [ ] **Step 4: Run them and confirm they pass,** plus the full suite: `python -m pytest tests -q`.
- [ ] **Step 5: Commit** (`collection: stable row_id; stale edits are a 409, not a wrong-row write`).

### Task 3: Offline prints store

**Files:**
- Create: `scryfall_prints.py`
- Modify: `server.py` startup (next to `scryfall_bulk.refresh_async()` at line ~160)
- Test: `tests/test_scryfall_prints.py` (new; builds from an in-memory fixture of hand-written print records, no network)

**Interfaces:**
- Consumes: `scryfall_bulk._read_records(path, jsonl)` and `scryfall_bulk._keys(card)`.
- Produces:
  - `enabled() -> bool`, `db_path() -> Path` (`cache/scryfall_prints.sqlite`), `age_days() -> float | None`.
  - `refresh(force=False, max_age_days=7.0) -> Path | None`. Downloads `default_cards` `jsonl_download_uri`, builds into a `.part` file, then `os.replace`. Deletes the download afterwards.
  - `refresh_async() -> None`.
  - `slim_print(card: dict) -> dict | None`. Returns None for `digital: true` or `layout in SKIP_LAYOUTS`. Keys: `id, oracle_id, name, set (UPPER), set_name, cn, rarity, released_at, lang, finishes, frame, frame_effects, full_art, promo, promo_types, border_color, artist, layout, prices {usd, usd_foil, usd_etched} (floats or None), images {small, normal, art_crop}, back_images {small, normal, art_crop} | None`.
  - `by_id(sid) -> dict | None`, `by_set_cn(set_code, cn) -> dict | None`, `prints_of(name) -> list[dict]` (newest `released_at` first).
  - `resolve(name, set_code="", cn="", scryfall_id="") -> dict | None`. Tries the id, then set+cn, then set alone **only if that set holds exactly one printing of the name**, else None.
  - `_build_db(records, out) -> int`, which takes an iterable so tests can call it.
  - Schema: `prints(id TEXT PRIMARY KEY, name_key TEXT, set_code TEXT, cn TEXT, released_at TEXT, card BLOB)`, plus indexes on `(set_code, cn)` and `name_key`. Reuse `scryfall_bulk._encode/_decode` (zlib JSON).

- [ ] **Step 1: Write the failing tests:**

```python
def test_slim_print_transform_has_back_image(): ...   # card_faces[i].image_uris present -> back_images set
def test_slim_print_split_has_no_back_image(): ...    # top-level image_uris, faces lack images -> back_images None
def test_digital_and_token_dropped(): assert scryfall_prints.slim_print({**P, "digital": True}) is None
def test_resolve_precedence(tmp_db):
    assert scryfall_prints.resolve("Sol Ring", scryfall_id="id-c21")["set"] == "C21"
    assert scryfall_prints.resolve("Sol Ring", "cmr", "472")["id"] == "id-cmr"
    assert scryfall_prints.resolve("Sol Ring", "C21")["id"] == "id-c21"   # one Sol Ring in C21
    assert scryfall_prints.resolve("Forest", "C21") is None               # several Forests: ambiguous
def test_prints_of_newest_first(tmp_db): ...
def test_disabled_returns_none(monkeypatch): ...      # MYTHFORGE_SCRYFALL_PRINTS=off -> resolve(...) is None
```

- [ ] **Step 2: Run them and confirm they fail.** `python -m pytest tests/test_scryfall_prints.py -q`.
- [ ] **Step 3: Implement** the module and wire `refresh_async()` into startup. *Offload candidate:* the spec is the Interfaces block above. Review it for connection locking (copy `scryfall_bulk`'s `_LOCK`/`_conn` pattern) and for the `.part` → replace step.
- [ ] **Step 4: Run them and confirm they pass,** then do one live build: `python -c "import scryfall_prints as s; print(s.refresh(force=True), s.by_id('30584c53-533b-4dc7-b07c-8600164a99b3')['set'])"`. Expected: a path and `FIC`. Record the built DB size in the commit message.
- [ ] **Step 5: Commit** (`scryfall_prints: offline per-printing store from default_cards`). Add `cache/scryfall_prints.sqlite` to `.gitignore` if `cache/` is not already ignored.

### Task 4: Printing-faithful enrichment and finish-aware value

**Files:**
- Modify: `collection_index.py` (`enrich_row`, `enrich_rows`, `_EMPTY_META`), `server.py` (`_enriched_collection`, `_collection_summary`)
- Test: `tests/test_collection_printings.py` (extend)

**Interfaces:**
- Consumes: `scryfall_prints.resolve` and `slim_print` (T3).
- Produces:
  - `enrich_row(row, index, resolve_print=None)`. `resolve_print` is a callable `(row) -> print | None`, defaulting to a `scryfall_prints.resolve` adapter, and is injected in tests.
  - New row fields: `print_resolved: bool`, `image_representative: bool`, `image`, `image_normal`, `art_crop`, `back_image` (normal), `rarity` (print-level when resolved), `set_name`, `released_at`, `artist`, `finishes`, `treatments: list[str]` (subset of `borderless`, `showcase`, `extended`, `full_art`, `retro`, `promo`, `etched`), `date_added` (from `_extra["Date Added"]` or None), `price`.
  - `print_price(print: dict, finish: str) -> float | None` (D8).
  - A resolved row with a blank `set`/`cn` and a `scryfall_id` gets `set`/`cn` from the print (D2). An **unresolved** row keeps `set` empty, exactly as today.
  - `_collection_summary` takes the enriched rows, and its `total_value` uses the same price as the row.
  - Price precedence: print price for the finish, then `cache/prices.json` (unresolved rows only), then None.

- [ ] **Step 1: Write the failing tests.** `test_enrich_uses_owned_printing_art` (two rows with the same name, different set → different `image`). `test_unresolved_row_keeps_unknown_set_and_flags_representative` (resolver returns None → `set == ""`, `image_representative is True`, no exception). `test_foil_price_never_falls_back_to_nonfoil` (`usd 1.0, usd_foil None`, foil row → `price is None`). `test_etched_price`. `test_treatments` (`border_color borderless` plus `frame_effects ["showcase","extendedart"]` gives `{"borderless","showcase","extended"}`). `test_scryfall_id_fills_blank_set`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.** Resolve once per distinct `(scryfall_id, set, cn, name)` per call, memoized in a dict inside `enrich_rows`. 1,205 rows must stay a sub-100 ms page build.
- [ ] **Step 4: Run them and confirm they pass,** plus `python -m pytest tests -q`. Live timing: `python -c "import time,server; t=time.time(); server._enriched_collection(); print(time.time()-t)"`. Expected: < 0.5 s warm.
- [ ] **Step 5: Commit** (`collection_index: enrich with the owned printing's art, rarity and finish price`).

### Task 5: Offline printing picker data, finish changes, honest Fill

**Files:**
- Modify: `server.py` (`collection_printings`, `CollectionPrintingRequest` / `collection_set_printing`, `CollectionAddRequest` / `collection_add`, `collection_backfill_printings`), `collection.py` (`set_printing_by_id`)
- Test: `tests/test_collection_routes.py` (extend; monkeypatch `scryfall_prints` lookups)

**Interfaces:**
- Consumes: `row_id`/`find_by_id` (T2), `prints_of`/`resolve`/`print_price` (T3, T4).
- Produces:
  - `GET /api/collection/printings?name=` → `{"printings": [...]}` from the prints store (live API fallback when the store is absent), newest first. Each item: `{id, set, set_name, cn, released_at, rarity, finishes, prices:{nonfoil,foil,etched}, treatments, image, art_crop, owned:[{row_id, finish, count}]}`.
  - `set_printing_by_id(rid, set_code, cn, finish, scryfall_id, path=None) -> list[dict]`. Merges into an existing identical row (counts summed). Raises `KeyError` when the row is stale.
  - `PATCH /api/collection/printing` body gains `row_id, finish, scryfall_id`. Returns **400** when `finish` is not in that print's `finishes`.
  - `POST /api/collection/add` gains `finish` (default `nonfoil`) and `scryfall_id`.
  - Backfill: rows with a `scryfall_id` or with set+cn are **normalized from the print, never replaced**. Only rows with no printing data at all get the cheapest printing for their finish. The response gains `normalized`.

- [ ] **Step 1: Write the failing tests.** `test_printings_marks_owned_rows`. `test_set_printing_rejects_unavailable_finish` (400). `test_set_printing_merges_identical_row`. `test_backfill_never_overwrites_scanner_printing` (a row with `scryfall_id` and set `TLE` stays `TLE` after backfill). `test_add_with_finish_creates_separate_row`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** the produced interfaces.
- [ ] **Step 4: Run them and confirm they pass,** plus the full suite.
- [ ] **Step 5: Commit** (`collection: offline printing picker, finish-aware printing changes, non-destructive Fill`).

## Phase B — Sort, group, filter (backend)

### Task 6: New sort keys and a secondary sort

**Files:**
- Modify: `collection_index.py` (`_SORTS`, `sort_rows`), `server.py` (`get_collection` params `then`, `then_direction`)
- Test: `tests/test_collection_views.py` (new)

**Interfaces:**
- Produces:
  - `sort_rows(rows, sort="name", direction="asc", then=None, then_direction="asc")`.
  - New keys:
    - `rarity`: `RARITY_ORDER` index; nullable.
    - `color`: `COLOR_BUCKETS` index, then a WUBRG tuple of the row's colours.
    - `released`: nullable.
    - `collector`: natural sort `(set, leading int, suffix)`, so `2 < 10 < 10a < ★1`.
    - `added`: `date_added`; nullable.
    - `finish`: nonfoil < foil < etched.
  - Nullable keys sort last in both directions (existing rule). Name stays the final tiebreak.

- [ ] **Step 1: Write the failing tests.** `test_collector_natural_order`. `test_color_wubrg_order` (W, U, B, R, G, Multicolor, Colorless). `test_rarity_unknown_last_both_directions`. `test_secondary_sort` (`sort="type", then="cmc", then_direction="desc"` → within Creature, higher cmc first). `test_unknown_then_key_ignored`.
- [ ] **Step 2: Run them and confirm they fail.** `python -m pytest tests/test_collection_views.py -q`.
- [ ] **Step 3: Implement** with chained stable sorts in this order: name, then secondary, then primary. Each nullable key partitions known and unknown values at its own level.
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit** (`collection_index: rarity/color/released/collector/added/finish sorts + secondary sort`).

### Task 7: Server-side grouping

**Files:**
- Modify: `collection_index.py` (add grouping), `server.py` (`get_collection` gains a `group` param; the response gains `groups`)
- Test: `tests/test_collection_views.py` (extend)

**Interfaces:**
- Consumes: `sort_rows` (T6).
- Produces:
  - `GROUP_BYS = ("none","type","color","cmc","rarity","set","finish","card")`.
  - `group_of(row, by) -> tuple[order_key, key, label]`.
  - `group_rows(rows, by) -> tuple[list[dict], list[dict]]`. The input is already sorted. It returns the rows ordered by group (stable within each group), each with a `group` key, plus `groups = [{key, label, rows, cards, value, printings?}]`.
  - Group orders:
    - type: Creature, Planeswalker, Battle, Instant, Sorcery, Artifact, Enchantment, Land, Other.
    - color: `COLOR_BUCKETS`.
    - cmc: `0`…`6`, then `7+`, with lands in their own final `Lands` group (not under 0).
    - rarity: `RARITY_ORDER`, then `Unknown`.
    - set: newest `released_at` first, label `set_name (CODE)`, unknown `—` last.
    - finish: nonfoil, foil, etched.
    - card: one group per `owned_key(name)`, in order of first appearance under the active sort, labelled with the card name. It adds `printings` (the number of distinct rows).
  - `get_collection`: filter → sort → group → **then** paginate. `groups` covers the whole filtered set. `group="none"` (the default) gives a response identical to today's plus `groups: []`.

- [ ] **Step 1: Write the failing tests.** `test_cmc_groups_put_lands_last`. `test_card_group_counts_printings` (Sol Ring in C21 nonfoil, C21 foil and CMR → one group, `printings == 3`, `cards` = summed count). `test_groups_total_over_whole_filter_not_page` (route test: `limit=2`, `group=type` → each group's `rows` total equals `matched`). `test_value_subtotal_ignores_unpriced`. `test_group_none_is_backward_compatible`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** the produced interfaces.
- [ ] **Step 4: Run them and confirm they pass,** plus the full suite.
- [ ] **Step 5: Commit** (`collection: server-side grouping with whole-filter subtotals`).

### Task 8: Printing filters and facets

**Files:**
- Modify: `collection_index.py` (`filter_rows`, `facets`), `server.py` (`get_collection` params)
- Test: `tests/test_collection_views.py` (extend)

**Interfaces:**
- Produces: `filter_rows(..., finishes=None, treatments=None, languages=None, multi_printing=False)`. `treatments` is ORed, and a row matches if it has any of them. `multi_printing` keeps rows whose card has ≥ 2 rows in the **unfiltered** collection. `facets()` gains `finishes`, `treatments`, `languages` (each `[{key,count}]`, only values that are present). The server takes comma-separated `finishes`, `treatments`, `languages` and a boolean `multi_printing`.

- [ ] **Step 1: Write the failing tests.** `test_filter_foil_only`. `test_filter_treatment_any_of`. `test_multi_printing_uses_whole_collection` (combined with a set filter that hides the second printing, the card still counts as multi-printing). `test_facets_list_only_present_finishes`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement** the produced interfaces.
- [ ] **Step 4: Run them and confirm they pass.**
- [ ] **Step 5: Commit** (`collection: finish/treatment/language/multi-printing filters`).

## Phase C — Frontend

### Task 9: View-settings model, vitest, and extracting the toolbar and list

**Files:**
- Modify: `frontend/package.json` (devDep `vitest`, script `"test": "vitest run"`)
- Create: `frontend/src/utils/collectionView.js`, `frontend/src/utils/collectionView.test.js`, `frontend/src/components/CollectionToolbar.jsx`, `frontend/src/components/CollectionList.jsx`
- Modify: `frontend/src/components/StepCollection.jsx` (use the extracted parts; `rowKey` → `row.row_id`; send `row_id` on count/remove/printing/bulk), `frontend/src/components/CollectionGrid.jsx` (key by `row_id`)

**Interfaces:**
- Consumes: the API fields from T2 and T6–T8.
- Produces (`collectionView.js`):
  - `VIEW_MODES = ['list','compact','grid','tiles','stacks']`.
  - `GROUP_BYS` (mirrors T7).
  - `SORT_KEYS = [[key,label]…]`: the existing 8 plus T6's 6.
  - `TILE_SIZES = {s:120, m:160, l:220}` (px column minimum).
  - `LIST_COLUMNS = ['set','cn','finish','rarity','type','cmc','mana','price','value','added','condition','language']`.
  - `DEFAULT_VIEW = {mode:'list', size:'m', groupBy:'none', sort:'name', direction:'asc', then:null, thenDirection:'asc', columns:['set','finish','type','price'], collapsed:{}}`.
  - `loadViewSettings(storage) -> settings`. Reads key `mtg_coll_view_v2`. Every field is validated separately, and an invalid field falls back to its default. It migrates the legacy `mtg_coll_view` (`'list'|'grid'`) value into `mode`. It never throws: a storage error or bad JSON returns `DEFAULT_VIEW`.
  - `saveViewSettings(storage, s)`, wrapped in try/catch.
  - `viewQuery(s) -> [[k,v]…]` for `sort, direction, then, then_direction, group`. `then` is omitted when null, and `group` when it is `'none'`.
  - `CollectionToolbar` props: `{settings, onChange(patch), facets, filtersActive, onToggleFilters, selectMode, onToggleSelect}`. It has the mode switcher (5 icon buttons from `lucide-react`), a size S/M/L control (only in grid/tiles/stacks), Group, Sort, Then-by, the direction toggles, and a Columns menu (only in list).
  - `CollectionList` props: `{cards, columns, selectMode, selected, onToggleSelect, onSetCount, onRemove, onPickPrinting, busy}`. It renders today's list row markup, columns-driven.

- [ ] **Step 1: Write the failing tests** in `collectionView.test.js`: `migrates legacy grid`, `bad JSON → defaults`, `throwing storage → defaults`, `invalid mode falls back but valid sort is kept`, `unknown column dropped`, `viewQuery omits group none and null then`.
- [ ] **Step 2: Run them and confirm they fail.** `cd frontend && npm i -D vitest && npx vitest run`.
- [ ] **Step 3: Implement** `collectionView.js` (*offload candidate*), then the two extracted components. Wire `StepCollection` through `loadViewSettings` and `viewQuery`. Behaviour must be unchanged for `list` and `grid` (the new modes can render `list` until T11/T12).
- [ ] **Step 4: Verify.** `npx vitest run` passes, `npm run lint` is clean, then `npm run build`. In the browser preview, list and grid look as they did before, +/− and remove work through `row_id`, and reloading keeps the chosen view.
- [ ] **Step 5: Commit** (`frontend: persisted collection view settings; extract toolbar and list`).

### Task 10: CardFace, showing the exact printing

**Files:**
- Create: `frontend/src/components/CardFace.jsx`
- Modify: `frontend/src/components/CollectionGrid.jsx` (render tiles through `CardFace`, honour `settings.size`), `frontend/src/index.css` (foil sheen keyframes)

**Interfaces:**
- Consumes: the row fields from T4.
- Produces:
  - `CardFace` props: `{row, variant:'full'|'art', flipped, onFlip}`. `full` uses `image_normal`/`image`, and `art` uses `art_crop`.
  - A foil row gets an animated diagonal sheen overlay (CSS `.mf-foil::after`, disabled under `prefers-reduced-motion`). An etched row gets an `ETCHED` badge.
  - `image_representative` shows a corner `≈` marker titled "Printing unknown — showing a representative printing".
  - A `back_image` shows a flip button (↻) that swaps to the back face.
  - The no-image fallback is the current dot + name + type block.
  - `SetChip` (named export) props `{set, cn, rarity}`: the set code coloured by rarity (common `#a8a29e`, uncommon `#cbd5e1`, rare `#eab308`, mythic `#f97316`, special/bonus `#c084fc`), with the title `set_name #cn`.

- [ ] **Step 1: Implement** `CardFace` and `SetChip`, and switch `CollectionGrid` to them. Its column minimum comes from `TILE_SIZES[settings.size]`.
- [ ] **Step 2: Verify in the browser preview.** A known foil row (any of the 197) shows the sheen. A transform card shows ↻, and the back face appears on click. A row with no printing shows `≈`. Two printings of one card show different art. Lint is clean and the build passes.
- [ ] **Step 3: Commit** (`frontend: CardFace renders the owned printing — foil, etched, DFC flip, representative marker`).

### Task 11: Art tiles and compact views

**Files:**
- Create: `frontend/src/components/CollectionTiles.jsx`, `frontend/src/components/CollectionCompact.jsx`
- Modify: `frontend/src/components/StepCollection.jsx` (mode switch)

**Interfaces:**
- Consumes: `CardFace`, `SetChip` (T10), `ManaCost`, `CardHover` (existing).
- Produces:
  - `CollectionTiles` (same props as `CollectionGrid`): an `art_crop` banner 16:10 with the name, `ManaCost`, type line, `SetChip`, count and price beneath. Hover shows the full card via `CardHover`. Edit controls match the grid hover bar.
  - `CollectionCompact` props `{cards, selectMode, selected, onToggleSelect}`: lines in decklist form, `3x Sol Ring (C21) 263 *F*`, in CSS columns (`columns: 280px`), with a colour dot and price right-aligned. A "Copy as text" button copies exactly those lines.

- [ ] **Step 1: Implement** (*offload candidate*: both are self-contained, and the props are given above).
- [ ] **Step 2: Verify in the browser.** Both modes render 200 rows without layout shift. Compact copy-text output re-imports through `/api/collection/import` as the same rows, including foil and set (paste it into the import box in merge mode on a scratch `MYTHSUITE_DIR` copy, **not** the live file). Lint and build pass.
- [ ] **Step 3: Commit** (`frontend: art-tiles and compact collection views`).

### Task 12: Grouped rendering and the stacks view

**Files:**
- Create: `frontend/src/components/CollectionGroups.jsx`, `frontend/src/components/CollectionStacks.jsx`
- Modify: `frontend/src/components/StepCollection.jsx`

**Interfaces:**
- Consumes: the `groups` response from T7, `settings.collapsed`, and every view component.
- Produces:
  - `CollectionGroups` props: `{cards, groups, collapsed, onToggleGroup(key), render(rowsOfGroup)}`. It splits the page's rows on `row.group` and renders a header for each group (label, `rows` printings, `cards` cards, `$value` from the **server** totals, a caret) followed by `render(rows)`.
  - A group whose rows continue past the current page shows "continues — Show all" in its footer.
  - Collapsed state persists through `settings.collapsed[groupBy]` (an array of keys).
  - `CollectionStacks` props: `{cards, groups, size, onSetCount, onRemove, onPickPrinting}`. It draws one column per group in a horizontally scrolling row. Cards overlap so that only the top 14% of each (the name bar) shows, and the hovered card lifts to full view (`z-index` plus `translateY`). The column header reads `label · cards`. If `groupBy === 'none'`, stacks uses `type` and the toolbar shows this.
  - For `groupBy === 'card'` in list mode, the group header gets a "+ printing" action that opens the T13 picker in add mode.

- [ ] **Step 1: Implement** these and route every mode through `CollectionGroups` (except stacks, which uses groups natively).
- [ ] **Step 2: Verify in the browser.** Group by type, then switch through all 5 modes. Collapse Creature, reload, and confirm it is still collapsed. Group by card and confirm Sol Ring shows its printings together with the summed count. Use a 50-row page to confirm the "continues" footer and that the header totals match the server. The stacks hover lift must not clip at the column edges. Lint and build pass.
- [ ] **Step 3: Commit** (`frontend: grouped collection rendering + stacks view`).

### Task 13: Printing picker

**Files:**
- Create: `frontend/src/components/PrintingPicker.jsx`
- Modify: `frontend/src/components/StepCollection.jsx` (replace the inline modal at ~lines 862–920)

**Interfaces:**
- Consumes: `GET /api/collection/printings` and `PATCH /api/collection/printing` (T5), `POST /api/collection/add` with `finish` (T5), `CardFace`/`SetChip` (T10).
- Produces: `PrintingPicker` props `{name, row|null, mode:'change'|'add', onDone(response), onClose}`.
  - A grid of print thumbnails. Each shows `SetChip`, the release year, treatment tags, an "owned ×N" badge, and one button per available finish with that finish's price (`—` when None).
  - A text filter on set code/name, a sort toggle Newest / Cheapest / Oldest, and an "Owned only" toggle.
  - In `change` mode the current printing+finish is outlined, and a finish button PATCHes by `row_id`. In `add` mode it POSTs `add` with `count:1`.
  - A 409 response shows "Collection changed — reloading" and calls `onDone(null)` so the parent reloads.

- [ ] **Step 1: Implement** the component and swap it in.
- [ ] **Step 2: Verify in the browser.** Change a nonfoil row to foil and see the sheen and the foil price. Pick a print that has no etched finish and confirm there is no etched button. Add a second printing from a card group. Edit the CSV by hand while the picker is open, then pick, and confirm the reload message appears and nothing is written to the wrong row. Lint and build pass.
- [ ] **Step 3: Commit** (`frontend: visual printing picker with per-finish prices and add-a-printing`).

### Task 14: Docs, contract note, release

**Files:**
- Modify: `CLAUDE.md` (collection section: identity key, canonical header, prints store and its kill switch), `docs/API.md` (new params and fields, the 409), `docs/engine/SUITE_PLAN.md` (C1: Forge's canonical columns and the consumed aliases), `README.md` (user-facing views), `frontend/package.json` version `1.5.0`
- [ ] **Step 1: Write the docs.** Then run `python -m pytest tests -q && cd frontend && npx vitest run && npm run lint`. Expected: all green.
- [ ] **Step 2: Rewrite the live collection file once,** deliberately: `.bak` is automatic, but also copy it first to `collection.pre-printings.csv`. Confirm the scanner still reads it (MythScanner's import accepts `Edition`, `Foil` and `Collector Number`). Then run "Fill printings" and check that it reports `normalized`, not overwritten.
- [ ] **Step 3: Commit and push** (`docs: printings & collection views`).

---

## Execution notes

- Tasks 1–2 are the hard prerequisites (identity and `row_id`), and T3 can run in parallel with them. T4–T8 depend on T1–T3. In the frontend, T9 comes first; T10 → T11 and T10 → T13 are independent of each other, and T12 needs T7 and T9.
- The first live build of the prints store downloads ~79 MB. Put the cache on C: (the repo); E: is tight.
- Follow-up candidates once this lands: owned-printing art in the deck view, set-coded deck exports, and the non-English store.
