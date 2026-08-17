# HTTP API reference

Every route the FastAPI backend (`server.py`) serves on **port 8000**. The React SPA is the only
client that exercises all of it, but the API is plain JSON and usable directly.

Anything marked **needs :8020** goes through the MythGauntlet strength engine. When that process is
down these endpoints report the measurement as unavailable rather than substituting a weaker guess —
there is exactly one analysis implementation in this repo, by design (see
[`ENGINE_DATA.md`](ENGINE_DATA.md)).

---

## Health & capabilities

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Overall status of ComfyUI and the LLM backend (drives the corner status light) |
| GET | `/api/comfy-status` | ComfyUI reachability on its own |
| GET | `/api/llm-models` | Curated LLM catalog with per-entry installed status (model selector) |
| GET | `/api/face-method` | Probe which face-conditioning engine ComfyUI supports |
| GET | `/api/video-health` | Whether an image-to-video model is installed + ready (gates the motion options) |
| GET | `/api/video-presets` | Motion presets, loop styles, output formats, foil styles + valid ranges |
| GET | `/api/3d-health` | Hunyuan3D v2 / rembg availability |
| GET | `/api/frame-styles` | Frame systems available (Built-in / M15 / Extended / Full-art) |
| GET/POST | `/api/frame-config` | Read / set the local Card Conjurer folder (env var wins) |
| GET | `/api/logs` | Recent server log lines (in-memory ring buffer) — powers the 📜 Logs viewer |

## Commanders & deck generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/commander/search` | Fuzzy commander lookup via Scryfall |
| GET | `/api/commander/autocomplete` | Commander name typeahead |
| GET | `/api/playstyles` | The 15 playstyle presets (key, label, description) |
| POST | `/api/deck/generate-list` | **Phase 1:** build the 99-card list (no art) from commander + playstyle + bracket; returns the deck, its creature tribes for the reskin UI, and collection coverage |

## Theming preview

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/deck/theme-preview` | World bible + 3 themed sample cards + motif coverage (no art) — iterate before building |
| POST | `/api/deck/style-sample` | **Visual taste test:** render the preview's exact sample prompts as real art (≤4 images) with the chosen style/model |
| GET | `/api/deck/style-sample/{id}` | Poll a style-sample job (`/img/{idx}` serves the images) |
| GET | `/api/deck/style-sample/{id}/img/{idx}` | One rendered sample image |

## Build & job lifecycle

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/deck/build` | Start an async deck build → `{job_id}` |
| POST | `/api/card/build` | Start a **single custom card** build → `{job_id}` (same job machinery) |
| GET | `/api/deck/{job_id}/events` | SSE stream of build progress (incl. per-card `card_ready`, `video_ready`) |
| GET | `/api/deck/{job_id}/status` | Poll build status — what a page refresh reconnects through |
| GET | `/api/deck/{job_id}` | Full deck payload once complete |
| POST | `/api/deck/{job_id}/cancel` | Cancel an in-progress build |
| POST | `/api/deck/{job_id}/rebuild` | Re-generate card **art**, keep existing themed names |
| POST | `/api/deck/{job_id}/retheme` | Full re-generation: new names **and** new art, same cards |
| POST | `/api/deck/{job_id}/regen-cards` | Regenerate art for specific cards only (optional custom prompts, optional forced face) |
| POST | `/api/deck/{job_id}/duplicate` | Copy a deck to a new job id |
| GET | `/api/decks` | Every saved deck, newest first — with lineage (`derived_from`/`derived_kind`), `imported`, `mode`, `has_bible` |
| GET | `/api/deck/active` | The build currently running, if any |
| DELETE | `/api/deck/{job_id}` | Delete one deck |
| POST | `/api/decks/delete-batch` | Delete several decks at once |

Re-runs never overwrite the source: rebuild / retheme / duplicate each write a **new** job id and
record what they came from, which is what History's version grouping reads.

## Deck assets & export

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/deck/{job_id}/card-image/{render_key}` | Rendered card proxy PNG |
| GET | `/api/deck/{job_id}/set-symbol` | Deck set emblem PNG |
| GET | `/api/deck/{job_id}/export/zip` | All card PNGs as a ZIP |
| GET | `/api/deck/{job_id}/export/pdf` | Print-ready PDF (2.5″×3.5″ @ 300 DPI, quantity-replicated) |
| GET | `/api/deck/{job_id}/export/decklist` | Original card names with real quantities; round-trips back through Import |
| GET | `/api/deck/{job_id}/export/videos` | ZIP of the deck's animated clips |

Exports work **before** there is any art: a saved import falls back to the card's real Scryfall image.

## Importing an existing deck

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/deck/import-preview` | Resolve a deck URL / pasted list (commander + counts + card list), cached; also returns the **simulated strength profile** when :8020 is up |
| POST | `/api/deck/import-save` | Save an imported deck to the library with no art, to theme or analyze later |

## Analysis — MythGauntlet

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/deck/{job_id}/measure` | **needs :8020** — simulation-grounded strength for a finished deck: bracket + six-axis Power Profile |
| POST | `/api/deck/{job_id}/advise` | **needs :8020** — upgrade suggestions drawn from cards you already own, with what each would change |
| POST | `/api/deck/{job_id}/apply-swap` | Apply an advisor suggestion: cut one card, add another |
| POST | `/api/deck/{job_id}/card-impact` | **needs :8020** — would this one named card help or hurt this deck, and why |
| POST | `/api/deck/{job_id}/duel` | **needs :8020** — head-to-head 1v1 win rate against a pasted opponent decklist. An honest "how does mine play against my friend's", not a bracket verdict |

Curve, colour-source and archetype figures (`stats.quality`, `stats.archetypes`, `stats.offmeta`) are
computed in-process and ride along on the deck payload — no engine required.

## Collection

The canonical store is `%USERPROFILE%/Documents/MythSuite/collection.csv`, shared across the Myth
Suite (`MYTHSUITE_DIR` overrides it). Every write leaves a `.bak` behind, and `undo` swaps them.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/collection` | Owned cards enriched with offline metadata — search, facet filters (`colors`/`types`/`rarities`/`sets`/`cmc_min`/`cmc_max`/`min_count`), sort, paginate. Facets are computed over the whole collection |
| GET | `/api/collection/stats` | Value, colour spread, mana curve, type/rarity/set breakdown, most valuable cards |
| POST | `/api/collection/add` | Add copies; Scryfall-fuzzy-validates the name and stores the canonical spelling |
| PATCH | `/api/collection/count` | Set an exact count (0 removes). With `set_code`, targets that printing |
| PATCH | `/api/collection/printing` | Move a row to another printing, **keeping its count**, merging if already owned |
| DELETE | `/api/collection` | Remove a card entirely (front-face keyed) |
| POST | `/api/collection/bulk` | One action over many printings in a **single** write |
| POST | `/api/collection/import` | Bulk-import a pasted Moxfield CSV or plain decklist (`merge` \| `replace`) |
| GET | `/api/collection/health` | Rows whose "name" is really a whole decklist line, and what repairing them would do |
| POST | `/api/collection/repair` | Apply those repairs — **`dry_run` defaults to true**, since this rewrites the canonical file |
| POST | `/api/collection/undo` | Restore the previous collection from the `.bak` (itself undoable) |
| GET | `/api/collection/printings` | Every printing of a card, cheapest first (set picker) |
| POST | `/api/collection/backfill-printings` | Fill in the cheapest printing for rows that have no set |
| POST | `/api/collection/prices` | Refresh market prices for the whole collection from Scryfall |
| GET | `/api/collection/suggest` | Card-name typeahead for the add box |
| GET | `/api/collection/buildable` | **needs :8020** — which commanders you own could you build a bracket 1–3 deck from, ranked by coverage |
| GET | `/api/card-image` | Resolve a card name to Scryfall image URLs (hover previews) |
| GET | `/api/card-lookup` | Full card data by name, shaped for the Single Card form |

## Art styles, models & faces

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/art-styles` | All art style presets + per-LoRA install status + selectable flavors |
| POST | `/api/art-styles/custom` | Create or update a custom art style preset |
| DELETE | `/api/art-styles/custom/{key}` | Remove a custom preset |
| GET | `/api/checkpoints` | Installed checkpoints, incl. synthetic Krea / Qwen entries |
| GET | `/api/comfyui/loras` | Installed LoRA files (feeds the LoRA picker) |
| POST | `/api/upload-face` | Upload 1–5 face reference photos → `{face_key}` |

## Animation & 3D

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/deck/{job_id}/animate-cards` | Animate selected cards → looping clips (SSE `video_ready`) |
| GET | `/api/deck/{job_id}/card-video/{render_key}` | A card's looping animation (mp4 / webp / gif) |
| POST | `/api/deck/{job_id}/generate-3d` | Start commander 3D (STL) generation |
| GET | `/api/deck/{job_id}/3d-status/{job_3d_id}` | Poll the 3D job |
| GET | `/api/deck/{job_id}/commander-3d.stl` | Download the printable STL |

---

## `BuildRequest` body

```json
{
  "commander_name": "Teysa Karlov",
  "playstyle": "auto",
  "bracket": 3,
  "art_theme": "dark gothic necromancer city",
  "theme_spec": {
    "setting": "a plague-haunted cathedral city of bone reliquaries",
    "genres": ["Gothic"],
    "moods": ["Eerie"],
    "lighting": ["Moody / dark"],
    "inspiration": "Bloodborne"
  },
  "creativity": "balanced",
  "frame_style": "builtin",
  "prebuilt_deck": [ /* the deck returned by /api/deck/generate-list */ ],
  "tribal_overrides": { "Knight": "Cowboy", "Rogue": "Outlaw" },
  "auto_theme_tribes": true,
  "use_collection": false,
  "card_source": "",
  "generate_art": true,
  "art_style": "mtg_fantasy",
  "model_speed": "quality",
  "face_key": "abc12345",
  "face_gender": "female",
  "gen_settings": { "guidance": 3.5, "steps": 35, "safe_mode": false }
}
```

- **`theme_spec`** (preferred theming input) — the structured Deck-idea fields. Drives
  `build_creative_brief` (world bible + faithfulness contract). `art_theme` is a back-compat fallback
  used only when `theme_spec` is empty (imports / old decks). `creativity` ∈
  `"faithful" | "balanced" | "imaginative"` tunes how much detail is invented around your motifs.
  Preview either with `POST /api/deck/theme-preview` before building. Both persist in `deck.json` and
  restore on Edit.
- **`prebuilt_deck`** (optional) — the list from `/api/deck/generate-list`. When present the build
  skips `DeckBuilder` and themes/renders this exact list. Omit it and the deck is generated from
  `commander_name` + `playstyle` + `bracket` (the old single-phase path; imports use
  `deck_url` / `deck_list`).
- **`tribal_overrides`** (optional) — `{OriginalType: Replacement}` chosen in the Theme step.
  Reskins each type across the deck — name, art, type line **and rules text**
  (`equip Knight` → `equip Cowboy`). Persisted; rebuild/retheme reuse it.
- **`card_source`** — `"scryfall"` | `"prefer_collection"` | `"collection"`. Empty derives it from
  `use_collection` (true → `prefer_collection`), which is what that flag has always meant. Only
  `"collection"` builds strictly from owned cards, and a strict build reports every slot the
  collection could not fill.
- **`frame_style`** — `"builtin"` | `"m15"` | `"m15_fullart"`. M15 styles need a local Card Conjurer
  (`MYTHFORGE_CC_DIR` or the in-app folder field).
- **`gen_settings`** is optional; omitting any field falls back to the model default (see
  `GenSettingsModel` in `server.py` / `GenSettings` in `image_gen.py`).
