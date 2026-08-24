# Data Sources

All external data is fetched explicitly (`mythgauntlet fetch-data`), cached under `data/`
(gitignored), and versioned by snapshot date. Simulation runs fully offline afterwards.

## Scryfall bulk data (cards) — implemented

- Endpoint: `https://api.scryfall.com/bulk-data` → `oracle_cards` download (~35k unique
  cards, one printing each; we don't need all 113k printings like MythScanner does).
- Slimmed to the fields simulation needs: `name, mana_cost, cmc, type_line, oracle_text,
  colors, color_identity, produced_mana, power, toughness, edhrec_rank, layout, card_faces
  (front-face fields for DFCs), legalities.commander, oracle_id`.
- Stored as `data/cards_slim.json`; loaded into an in-memory index by normalized name
  (~50 MB RAM, instant lookups). SQLite index comes when the app layer needs partial loads.
- Etiquette: identify with a proper User-Agent; bulk files are updated daily upstream, weekly
  refresh is plenty for us.
- `edhrec_rank` ships in this file — the day-one popularity prior, no extra API needed.

## EDHREC JSON API (popularity & synergy) — planned (L0/L5)

- Open JSON endpoints at `json.edhrec.com` (no key). Community wrappers exist (`pyedhrec`).
- Per commander: card inclusion rates, **synergy scores** (inclusion% for this commander −
  inclusion% for its color identity), average decklists, themes.
- Uses: seed card-value priors (LEARNING.md §3c), build reference-gauntlet "average decks",
  power the upgrade advisor's candidate pool.
- Politeness: cache aggressively (per-commander JSON changes slowly), throttle, identify
  ourselves. This is an unofficial API — isolate behind `data/edhrec.py` so breakage is
  contained.

## Commander Brackets & Game Changers — planned (data file)

- Official WotC bracket system (beta): 5 brackets; Game Changers list is **53 cards as of
  Feb 2026** and updated by WotC periodically.
- Stored as a versioned data file (`data/brackets/game_changers_2026_02.json`) with source
  URL; refreshed manually when WotC posts updates (they're announcements, not an API).
- Used by ratings/calibration for hard bracket gates and by reports.

## Deck polling (`data/decksources.py`) — implemented

`mythgauntlet fetch-decks` pulls fresh decklists into `corpus/decks/` (committed, with
`manifest.json` provenance: source, date, bracket label when known):

- **EDHREC average decks** (`json.edhrec.com/pages/average-decks/<slug>.json`) — the
  payload's `deck` list is the complete 100 cards (basics included with counts; the
  `basic`/`nonbasic` fields are informational only — learned the hard way).
- **Archidekt public API** (`/api/decks/v3/` search + `/api/decks/<id>/` detail) — popular
  user decks ordered by views/recency; carries a user-declared `edhBracket` label when set
  (free calibration data). Cards live at `cards[].card.oracleCard.name`; categories with
  `includedInDeck=false` (Maybeboard etc.) are excluded; category "Commander" defines the
  command zone. Throttled 0.25s/request. The API ignores small pageSize values — truncate
  client-side.
- **Corpus sanity gate**: fetched decks are kept only if a commander is detectable and the
  list is 95–102 cards — real-world data includes 300-card piles, theorycrafts, and decks
  whose owners renamed every category (no detectable commander).
- **Moxfield**: NOT implemented — their API requires a pre-approved User-Agent. The cEDH
  Decklist Database links out to Moxfield, so cEDH anchor lists need another route
  (manual export or an approved UA) — still wanted for Bracket-5 anchors.

## Commander Spellbook (`data/spellbook.py`) — implemented

The community's canonical combo database, open API. `POST /find-my-combos` with a decklist
returns combos the deck **contains** and combos **one card away** — powering the Ceiling
axis, the official bracket combo gates (Brackets 1–2: no intentional 2-card infinites), and
future upgrade-advisor suggestions. Each combo variant carries the cards used, the produced
features ("Infinite colorless mana"), Spellbook's own `bracketTag`, and popularity. Cached
by decklist hash under `data/spellbook/`. CLI: `mythgauntlet combos DECK.txt` or
`analyze --combos`.

## Decklist & collection import — implemented (text), planned (rest)

- Plain text / MTGO style: `1 Sol Ring` / `1x Sol Ring` / bare names; `Commander:` header or
  Moxfield-style sections. (implemented in `model/deck.py`)
- Moxfield export format (same shape), Archidekt CSV — planned.
- **MythScanner collection import**: its `--export` CSV/Moxfield output is the contract;
  collection-aware features (upgrade advisor restricted to owned cards) build on this.

## Tournament / real-game outcome data — later (calibration fuel)

- Topdeck.gg & cEDH tournament results for Bracket-5 ground truth; MTGO Commander leagues if
  accessible. Strictly for calibrating/validating the rating scale — never required for the
  core loop to function.

## Rulings + Comprehensive Rules (`data/rulings.py`) — implemented 2026-08-24

The Deck Mentor feature (`docs/SPEC_deck_mentor.md`) needs a ground-truth corpus to check an
LLM's rules claims against — before this, the repo had none at all (confirmed by grep while
spec'ing that feature: zero hits for "rulings" anywhere in the tree). Two sources, one module:

- **Scryfall rulings bulk data** — same `bulk-data` index the card store uses, `type ==
  "rulings"`, one JSONL-gzip file of `{oracle_id, source, published_at, comment}` records
  grouped by `oracle_id` at fetch time (`data/rulings_slim.json`, schema-versioned, hard-fails
  on mismatch — same doctrine as `scryfall.py`). Joins straight onto the existing `CardDb`
  identity.
- **The official Comprehensive Rules** (plain text, `magic.wizards.com/en/rules` — the direct
  `.txt` link is discovered by scraping that page rather than hardcoded, since the URL's date
  changes with every rules update; verified live 2026-08-24 the href carries a literal space
  before the date, not `%20`, so the fetcher re-encodes it). Parsed into `{number, text}`
  records (the citation unit a Deck Mentor answer must trace back to) plus the Glossary as
  `{term, text}`. **Measured against the live 2026-08-19 document: 3,308 rules, 739 glossary
  terms**, both comfortably above the module's own sanity floor (it refuses to write a corpus
  under 1,000 rules / 500 glossary terms rather than silently caching a broken parse).

**Why this data has to be fetched live and never assumed: rule numbers renumber.** Verified
while building this — the "creature with 0 toughness dies" state-based action, commonly cited
as rule 704.5c, is **rule 704.5f** in the current (Aug 2026) rules; 704.5c is now the ten-or-more
poison-counters rule. An LLM citing 704.5c from training-time memory would be citing the wrong
rule with the same fluent confidence as a correct citation — exactly the failure this corpus
exists to catch, and a concrete demonstration of why Phase 0 is a real prerequisite and not
ceremony.

**Retrieval:** exact rule-number and card-name lookups are dict gets. Free-text questions go
through BM25 (`rank_bm25`) over rule + glossary text — deliberately not an embedding index, see
the module docstring. **Measured limitation, not fixed further:** BM25 has no stemming or
synonymy, so a query using "zero" instead of "0" originally missed rule 704.5f entirely, purely
on token mismatch (CR text overwhelmingly writes small numbers as digits). A small
number-word→digit normalizer in `_tokenize` closed the exact case measured, but a paraphrase
using different vocabulary entirely (e.g. "dies" for a rule that says "put into its owner's
graveyard") still won't be found by BM25 alone — add a semantic layer only if the Phase 4
gold-set bench measures this as a real recall problem, not preemptively.

CLI: `mythgauntlet fetch-rules` (mirrors `fetch-data`'s `--force`; rulings refresh weekly like
card data, the Comprehensive Rules every 14 days since WotC updates it roughly per set release
rather than daily).

## Local LLM (semantics compilation) — infrastructure already running

- llama-swap gateway on `127.0.0.1:8010` (OpenAI-compatible), `qwen3:14b` default; used
  offline at compile time only (CARD_SEMANTICS.md). Temperature 0, JSON-only outputs,
  validation gates decide acceptance — the LLM proposes, the gates dispose.
