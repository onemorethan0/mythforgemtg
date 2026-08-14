# SPEC — `docs/COLLECTION_MODES.md`

Write ONE new Markdown file: `docs/COLLECTION_MODES.md` in the Myth Forge repo.

Output **only the contents of that file**, in a single ```markdown fenced block. No prose
before or after. `/no_think`

---

## 1. Why this file exists

Myth Forge's engineering map is `CLAUDE.md` at the repo root — but that file is
**gitignored** (`.gitignore:32`). Everything written there is local-only: it never reaches
the remote, a fresh clone, or another machine. Four new modules and a whole new build mode
landed recently and are documented ONLY there, so today they would vanish for anyone else.

This file is the **tracked** home for that knowledge. It must stand alone: assume the
reader has the code but has never seen CLAUDE.md.

---

## 2. Audience and voice

Written for an engineer (or an AI agent) opening this repo for the first time and needing
to change the deck builder without breaking it.

Match the house style, which is dense and specific:
* State the invariant, then **name the bug it prevents**. "X must be Y" is weak; "X must be
  Y — a plain substring put `cat` inside `escalate` and `duplicate`" is the style.
* Prefer concrete numbers and card names over adjectives.
* No marketing tone, no "powerful", no bullet lists of adjectives.
* Use `backticks` for identifiers and file paths.

---

## 3. Source material — READ THESE BEFORE WRITING

Everything you write must be verified against the actual code. Read, in this order:

1. `collection_pool.py` — module docstring carries a gold-set table.
2. `deck_quality.py` — module docstring carries a worked-example table.
3. `theme_match.py` — module docstring carries a gold-set table.
4. `deck_builder.py` — specifically: the `SOURCE_*` constants and `CARD_SOURCES`,
   `_POOL_ROLE`, `_strict()`, `_draft_curve_aware()`, `_normalize_plan()`,
   `_fetch_theme_synergy_list()`, `_fetch_goodstuff()`, `_resolve_owned_cards()`,
   `build()`, `compute_stats()` and `deck_quality_block()`.
5. `server.py` — `_resolve_card_source()`, `_backfill_quality()`, and the
   `collection_stats` blocks in `_run_build` and `generate_list`.
6. `tests/test_collection_pool.py`, `tests/test_deck_quality.py`,
   `tests/test_theme_match.py`, `tests/test_deck_builder_curve.py`,
   `tests/test_deck_builder_theme.py` — these tell you which claims are actually pinned.

**Do not describe behaviour you have not read.** If you cannot verify a statement, leave it
out and list it in your final report instead.

---

## 4. Required structure

Use exactly these top-level sections, in this order:

### `# Collection modes and deck quality`
Two or three sentences: what this document covers and why it is tracked separately from
`CLAUDE.md`.

### `## Card sources`
The three modes on `BuildRequest` / `GenerateListRequest`: `scryfall`,
`prefer_collection`, `collection`.

Must cover:
* What each mode draws from.
* **The back-compat rule**: `use_collection: true` has always meant PREFER, never
  "owned only". `server._resolve_card_source` derives the mode when `card_source` is empty
  or unrecognised, so every caller predating the field keeps its exact behaviour. Say why
  that mattered — redefining the boolean would have silently narrowed existing users' decks.
* Where strict mode is reachable in the UI (the Collection screen's buildable panel; see
  `App.handleBuildFromCollection`).

### `## What strict mode cannot do, and how it says so`
* Name RESOLUTION still uses Scryfall (owned names → card data); only SEARCH is
  unavailable. That distinction is the whole design.
* `builder.shortfall` — per-role deficits, plus the `padded_with_basics` key when the
  owned pool runs dry.
* `builder.source_fallback` — set when the owned pool resolves to nothing and the build
  reverts to Scryfall.
* How both surface: the SSE progress stream, `deck.json`'s `collection` block, and
  StepDeck.

### `## The three local modules`
One subsection each for `collection_pool.py`, `deck_quality.py`, `theme_match.py`.

For each: what it replaces, its public API, and **the specific bugs its guards prevent**.
Draw these from the module docstrings and the tests. Include at least these, verbatim
enough to be checkable:
* `collection_pool`: the net-mana gate (`{1},{T}: Add {B}` nets zero and is not ramp);
  word-vs-digit card counts ("Draw two cards", not `\d+`); Blasphemous Act says "each
  creature" SINGULAR; a creature that HAS indestructible protects only itself; role lists
  are nonland by construction; `land_tier()` returns `None` meaning "allow".
* `deck_quality`: `quantity` weighting (14 aggregated Mountains are 14 sources); the
  average uses TRUE mana value while bucketing clamps at 7; MV 0 counts as a one-drop;
  colour sources come from `produced_mana` or an `Add` clause and NEVER from bare colour
  words (Nim Deathmantle "is a black Zombie" is not a black source).
* `theme_match`: fidelity governs the MATCH SET, the STRONG/WEAK score governs only
  ORDERING; tribe words accept the regular plural because Scryfall's `o:` is a substring
  match; `\b` bounds remain because a raw substring puts `cat` inside `escalate`.

### `## Deck quality on every deck`
`stats["quality"]`, its shape, that it is advisory and never changes card selection, and
`server._backfill_quality` deriving it on load for decks that predate it — deliberately
NOT written back to disk.

### `## Working on this code`
Short, practical:
* Tests run with no `data/` directory and no network — that is CI's state. Never read
  `data/cards_slim.json` from a test; inline verbatim oracle text.
* Magic is precise: a wrong card model is a defect, not an approximation.
* `scripts/offload.py` — the spec → local model → review loop, and the two llama-swap
  failure signatures it distinguishes (HTTP 500 containing "prematurely" is a CUDA OOM and
  is NOT retried; 502/503 is a mid-swap model load and IS retried).

---

## 5. Length and format

* 120–200 lines of Markdown.
* Tables where they genuinely help (the card-source modes; the quality block shape).
* No emoji. No horizontal rules between every section. No "Conclusion" section.
* Every code identifier in backticks.

---

## 6. Do NOT

* Do not edit any other file — only output this document.
* Do not restate `CLAUDE.md` wholesale; this document is about the collection modes and
  the three local modules, not the art pipeline, ComfyUI, LoRAs or theming.
* Do not invent file paths, function names or card names. Every one must exist.
* Do not claim a behaviour is tested unless you found the test.
