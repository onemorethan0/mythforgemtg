# The Myth Suite — combining MythForge, MythScanner, and MythGauntlet

*Drafted 2026-07-07 from a live survey of all three repos. This is the canonical plan;
the sibling repos get pointers to it.*

## The loop we're building

Three working apps, one player journey, currently disconnected:

```
   SCAN IT               VALUE IT              BUILD WITH IT           PROVE IT
┌────────────┐        ┌────────────┐        ┌────────────────┐     ┌────────────────┐
│ MythScanner│──CSV──►│ (Scanner    │        │ MythForge      │────►│ MythGauntlet   │
│ webcam →   │        │  price     │        │ commander → 99 │◄────│ simulate 1000s │
│ collection │        │  tracking) │        │ AI theme + art │     │ of games →     │
│ SQLite     │        └────────────┘        │ print proxies  │     │ Power Profile  │
└────────────┘                              └────────────────┘     └────────────────┘
      │                                            ▲                      ▲
      └────────── "what can I build              collection-aware         │
                   with what I own?" ────────────  building  ─────────────┘
```

Scan your cards → know what they're worth → build (or import) a deck → **prove its
strength with simulation, not vibes** → improve it from cards you actually own → print
the themed proxies → repeat.

## Ground truth (surveyed 2026-07-07)

| | MythForge | MythScanner | MythGauntlet |
|---|---|---|---|
| Repo | `onemorethan0/mythforgemtg` (public, v1.2.0) | `onemorethan0/mythscannermtg` (private, v1.0.0+) | `onemorethan0/mythgauntlet` (private) |
| Form | FastAPI :8000 + React SPA | PySide6 desktop app | Python CLI + engine |
| State | Animated card export, taste test, **deck import (Moxfield/Archidekt/paste)**, **heuristic bracket chips** (`deck_analysis.py` — "a heuristic, not a verdict") | Fused recognition (collector OCR → art-hash → title), binder mode, prices, listings; **exports Moxfield CSV**; no API, no imports | T0 goldfish + T2 adversarial sims, 894-card CCM semantics, EDHREC/Spellbook data, BT gauntlet ratings; **imports Moxfield/Scanner CSV** |
| Cross-app hooks today | none | none | `analyze --collection <scanner export>` |

Notable: Forge's local work sits on branch `themer-context-tuning` with an uncommitted
"single custom card" feature; nothing blocks this plan.

## Design stance: contracts, not a monorepo

The apps stay separate repos, processes, and release cycles (a desktop scanner, a web
builder, and a simulation engine genuinely are different programs). The suite is four
small, stable contracts:

### The machine's port registry (authoritative)
| Port | Service | Owner |
|---|---|---|
| 7000 | Odysseus | separate project (shares llama-swap) |
| 8000 | MythForge (FastAPI + SPA) | mtg_deck_builder |
| 8010 | llama-swap → llama.cpp | E:\llama (shared: Forge theming, Gauntlet compiler, Odysseus) |
| **8020** | **MythGauntlet strength API** | `config.STRENGTH_API_PORT` — the single source of truth; `mythgauntlet serve` and Forge's `MYTHGAUNTLET_URL` default both derive from it |
| 8188 | ComfyUI | Desktop app |

### C1 — The collection contract
One canonical file: **`%USERPROFILE%\Documents\MythSuite\collection.csv`** (Moxfield CSV —
Scanner writes it; Gauntlet reads it; liberal headers). Both ends honor the same
**`MYTHSUITE_DIR`** env override (Scanner `export.suite_collection_path()`, Gauntlet
`config.suite_collection_path()`, Forge `collection.suite_collection_path()`), so relocating
the suite folder is one variable.

**Three copies, pinned by three tests (2026-07-29).** Scanner and Forge cannot import
Gauntlet's `config.py`, so this constant is necessarily duplicated in all three repos. An
identical assertion now lives in each — Gauntlet `tests/test_config_suite.py`, Forge
`tests/test_smoke.py::test_suite_path_contract`, Scanner
`tests/test_export.py::test_suite_path_contract` — so a copy that drifts fails its OWN suite
instead of quietly pointing one app at a different collection file. If the contract ever
changes, all three tests must change together; that is the point.

**Writers must be atomic (2026-07-29).** Two apps write this file — Scanner on export, Forge
on every +/- click in its collection manager — and Gauntlet reads it for owned-aware building
and the advisor. Both writers used to open the destination with `"w"`, which truncates up
front: an interrupted write destroyed the collection and a concurrent reader could see a
partial one. Both now serialise to a temp file in the same directory, fsync, and `os.replace`
it in. Any future writer of this file must do the same.
- Scanner: **"Export to Myth Suite"** (File menu / `--export-suite`): writes the file. ✅
- Gauntlet: `analyze` (CLI, `--no-collection` to opt out) and the API's `/analyze`
  (`use_suite_collection`, default true) **default to that file when it exists** —
  ownership reports appear automatically after a scan+export. ✅
- Forge: collection-aware building reads the same path (C4, **done 2026-07-13** — Forge's
  `collection.py` mirrors this contract; `use_collection` build flag).

### C2 — The strength API
Gauntlet's local HTTP service — **`mythgauntlet serve`** on the registry port above.
Startup: the semantics store (~9k CCM files) is loaded through a pickle cache
(`store.load_store`, keyed on the CCM dirs' file-count+mtime) — ~50s cold to build the
cache, ~1.4s warm; every CLI command shares the same cache.
- `GET  /health` → engine version, card-store size, semantics coverage
- `POST /analyze` → decklist (+ optional collection) → Power Profile, bracket estimate,
  Game Changers, combos flag, semantics coverage, ownership gaps
- `POST /duel` → two decklists → win rates
Responses carry `engine_version` — a rating is a measurement by an instrument.

### C3 — Forge tells the truth about power
Forge's import preview and finished builds call `POST /analyze`:
- The bracket chips become **simulation-grounded** (falling back to the existing
  `deck_analysis.py` heuristic, clearly labeled, when :8020 isn't running).
- Longer-term: **build-to-bracket** — Forge generates, Gauntlet scores, Forge swaps
  slots until the measured bracket matches what the user asked for. This closes the
  generate → evaluate → improve loop that neither app can do alone.

### C4 — Build from what you own
- Forge: a "use my collection" toggle — slot filling prefers owned cards (C1). **DONE
  2026-07-13** (Forge `collection.py` + `use_collection`): reads the canonical C1 export,
  prefers owned cards in every role, and seeds eligible owned cards into the flexible
  goodstuff/creature slots (an adaptive theme-trim makes room); reports owned coverage on
  `/api/deck/generate-list` + in `deck.json`; UI toggle + "N/M from your collection" badge.
  Essential roles + lands stay staple-filled so the deck is playable. Verified: Brago drew
  15 of 18 eligible owned cards.
- Gauntlet: the upgrade advisor (roadmap Phase 8) restricted to owned cards, surfaced
  in Forge's UI next to the strength panel. **Still open** — the advisor itself is unbuilt.

## Delivery phases

| Phase | Repo | Work | Status |
|---|---|---|---|
| S1 | Gauntlet | `serve` API: /health, /analyze, /duel (FastAPI behind a `[serve]` extra; store+db loaded once at startup) | **started 2026-07-07** |
| S2 | Scanner | "Export to Myth Suite" (canonical C1 path, File menu + auto-refresh option) | queued |
| S3 | Forge | Strength panel: call :8020 from import preview + deck view; graceful heuristic fallback; "start Gauntlet" hint when down | queued |
| S4 | Forge+Gauntlet | Collection-aware building (C1 in Forge slot filler) **done 2026-07-13**; advisor-owned mode still open (advisor unbuilt) | partial |
| S5 | All | Build-to-bracket loop; suite launcher/dashboard; shared card-data layer if profiling justifies it | later |

## Non-goals
- Merging repos or rewriting shared Scryfall layers "for cleanliness" — each app's cache
  fits its needs (Scanner needs 113k printings + art hashes; Gauntlet needs 34k oracle
  cards + semantics; Forge needs live API + art). Contracts over consolidation.
- Cloud anything. The suite stays local-first like all three apps.
