# Documentation Index

Docs for **Myth Forge — MTG Commander Deck Builder**. The root [`README.md`](../README.md) is the tour; this folder holds the manuals. For an agent-oriented overview see [`CLAUDE.md`](../CLAUDE.md).

---

## Start here if you are working on recommendations

**[`HANDOFF.md`](HANDOFF.md)** — the committed record of the 2026-08-14 recommendation/measurement work: what changed and its measured effect, how to run the three benchmark harnesses, the caveats that must accompany any number they produce, the recurring bug classes in this codebase, and what is still open. Read it before touching `deck_builder`, `theme_match`, the theme taxonomy or the advisor.

**[`ROADMAP.md`](ROADMAP.md)** — the measured shortfall map and the plan against it (2026-08-18):
eight shortfalls with the number behind each, prioritised for **casual bracket 1–3 gauging**,
plus a spec per fix and its definition of done. Also records what the local-model offload is
and is not trusted for on this codebase, with the gold-set scores behind that call.

**[`PLAN_CLOCK.md`](PLAN_CLOCK.md)** — the bracket-accuracy plan (2026-08-21): the goldfish
clock is bracket-invariant (a B5 nut draw kills on the same turn as a B1's), why that closes
exact B2/B3 separation and retargets the accept bar at within-one accuracy, and what's still
buildable (Phase 2's interaction-required measure, Phase 3's B1/B2 refit).

---

## Start here if you are working on the Deck Mentor

**[`MENTOR_HANDOFF.md`](MENTOR_HANDOFF.md)** — six real conversation campaigns driven through
the live HTTP route (2026-08-25): the reusable method (duplicate a real deck, ask real
questions, cross-check every claim against the real source, record genuine feedback), every
real bug found and fixed (a mutually-exclusive if/otherwise pair double-credited as a win, a
real-but-wrong sibling rule citation, several card-name false positives, a partner-commander
deck invisible to the strength engine and mentor alike, a model that recites two colour sets
correctly and still fails the subset check between them), and what's still open. Read it before
touching `mentor/{gate,chat,tools,transcript}.py` or `mentor_bench.py`.

---

## Getting started
1. **First-time setup:** run `setup.bat` (Windows) or `python install.py` (Mac/Linux).
2. **Download models:** `manage.bat` → Download AI Models, or `python download-models.py`.
3. **Start:** `manage.bat` → Start Development Server (or `dev.bat`, or `python server.py`), then open http://localhost:8000.
4. ComfyUI (port 8188) and the local LLM gateway (8010) run separately — `manage.bat` starts
   the gateway and the strength engine for you.
5. **Verify:** `python verify-setup.py` checks Python deps, the frontend build, the engine, and
   whether the strength API is up.

Full setup + troubleshooting: [`../INSTALL.md`](../INSTALL.md) · ComfyUI launch: [`../COMFYUI_SETUP.md`](../COMFYUI_SETUP.md)

> Note: [`STARTUP_GUIDE.md`](STARTUP_GUIDE.md) is a superseded stub describing an old `START.bat`/`paths_config.ps1` system — ignore it; INSTALL.md is current.

## Deck strength engine (MythGauntlet)
The engine that measures brackets and deck strength ships in this repo at `src/mythgauntlet/`
(merged 2026-07-29 from its own repo, so there is one install and one analysis implementation).
- **What data is and isn't included:** [`ENGINE_DATA.md`](ENGINE_DATA.md) — the ~30k compiled
  card semantics are withheld while training completes; the engine degrades to Oracle-text
  heuristics without them. **Read this first if brackets look imprecise.**
- **Engine internals:** [`engine/`](engine/) — `ARCHITECTURE.md`, `SIMULATION.md` (what each
  tier models and every documented simplification), `CARD_SEMANTICS.md` (the CCM schema,
  validation gates and compiler), `LEARNING.md`, `DATA_SOURCES.md`, `SUITE_PLAN.md` (the
  collection contract shared with MythScanner), `STATUS.md` (measured state + what's next).

## Reference
- **How a card is actually made:** [`INTERNALS.md`](INTERNALS.md) — card renderer, themer, image
  generation, art-style presets, face conditioning, animation, 3D, and the gotchas that bite.
- **Every HTTP endpoint:** [`API.md`](API.md) — grouped by area, plus the full `BuildRequest` body.
- **The gallery:** [`GALLERY.md`](GALLERY.md) — thirteen full themed decks.
- **Collection build modes:** [`COLLECTION_MODES.md`](COLLECTION_MODES.md) — `scryfall` vs
  `prefer_collection` vs strict `collection`, and what strict mode can't do.

## For users
- **Troubleshooting by symptom:** [`MAINTENANCE.md`](MAINTENANCE.md)
- **GPU/performance tuning:** [`HARDWARE_OPTIMIZATION_GUIDE.md`](HARDWARE_OPTIMIZATION_GUIDE.md)

## For developers
- **Read before changing code:** [`DEVELOPMENT_GUIDELINES.md`](DEVELOPMENT_GUIDELINES.md)
- **Architecture & conventions:** [`../CLAUDE.md`](../CLAUDE.md)
- **Module specs** (`SPEC_*.md`) — the written-first specifications that drafted and now pin
  `collection_pool`, `deck_quality`, `deck_themes`, `edhrec_lift`, `lift_stats`, `redundancy`,
  `theme_match` and the collection UI. Tests are written from these, not from the implementation.

## Real entry-point scripts (root)
| Script | Purpose |
|--------|---------|
| `setup.bat` / `install.py` | One-time install (deps + frontend build) |
| `manage.bat` | Menu: start/stop server, status, download models |
| `dev.bat` | Start the dev server directly |
| `download-models.py` | Download checkpoints/LoRAs/face models |
| `start-mythforge.sh` | Mac/Linux start helper |

---

_Last updated: August 2026 — added `INTERNALS.md`, `API.md` and `GALLERY.md`, which absorbed the deep
reference sections that used to live in the root README._
