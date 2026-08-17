<div align="center">

# ⚔️ Myth Forge

**Describe a world. Get a legal 100-card Commander deck, printed as custom cards.**

Fully local. Your GPU, your models, your machine — no accounts, no API keys, nothing uploaded.

[![CI](https://github.com/onemorethan0/mythforgemtg/actions/workflows/ci.yml/badge.svg)](https://github.com/onemorethan0/mythforgemtg/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/onemorethan0/mythforgemtg?color=8b5cf6)](https://github.com/onemorethan0/mythforgemtg/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![Local first](https://img.shields.io/badge/cloud-none-16a34a)](#quick-start)

![Five commanders across five themed decks](docs/samples/hero_commanders.jpg)

</div>

Pick a commander, type a setting — *"a fae realm of canine trainers"*, *"Prontera City at
Halloween"* — and Myth Forge builds the 99, invents a name and flavor line for every card, paints
custom art for each one locally, and composites it all into print-ready proxy frames. The rules text
never changes; only the skin does, and every card carries the real card's name as a subtitle so
nobody at the table has to guess what they're looking at.

It also **measures**. A simulation engine ships in the box and plays thousands of games to tell you a
deck's power bracket, so "is this on level for my pod?" gets an answer instead of a vibe.

---

## What you can do

| | | |
|---|---|---|
| 🃏 | **Build a deck** | Generate a themed 100-card Commander deck with custom AI art and printable proxies. |
| 🔍 | **Analyze a deck** | Import one you already have to measure its real strength — a simulation-grounded bracket and Power Profile — then retheme it if you like. |
| 🂠 | **Single card** | Proxy one real card with new art, or design a custom card from scratch: your own name, cost, rules and flavor. |
| 🎴 | **My collection** | Browse, add and edit the cards you own. Powers collection-aware building and owned-card upgrade suggestions. |

---

## Gallery

The *same* commander (Syr Gwyn, Hero of Ashvale) rethemed into four worlds. The rules stay identical,
but the name, art, flavor — even the creature types in the rules text ("equip **Cowboy**", "equip
**Grim Warden**") — follow each world:

![The same commander rethemed into four different worlds](docs/samples/one_card_four_worlds.jpg)

**The borderless treatment** — full-bleed art edge to edge, floating legend crowns, white title/type/
P&T in the official showcase convention, and the proxied card's real name as a subtitle:

![Borderless cards across five decks and five card types](docs/samples/borderless_showcase.jpg)

**The commander wears your face** — upload 1–5 photos and the commander (plus a few humanoid crew
cards) renders with your likeness, in any theme and any art style. All five below came from one
person's reference photos:

![The same face as five different commanders across five themes](docs/samples/face_commanders.jpg)

> **→ [Thirteen full themed decks in the gallery](docs/GALLERY.md)** — cyberpunk rave, hive city,
> ink-wash samurai, desert wasteland, crystal caves and more.

All art is generated **locally** (FLUX / SDXL via ComfyUI). The borderless cards were rendered
against a locally-installed Card Conjurer's frame assets — **this repo bundles no
Wizards-copyrighted frame artwork**; the built-in frames ship with the app.

---

## Quick start

> ### 🚀 No big GPU? Start in "quick-look" mode
> You do **not** need ComfyUI or a 24 GB card to see the core experience. Install, leave the
> **Generate AI art** toggle **off** on the Theme step, and Myth Forge still themes the whole deck
> (custom names, flavor text, creature-type reskins) and renders **print-ready proxy frames using
> real Scryfall art**. Only the *custom AI art* needs a GPU. Theming uses a local LLM, which can run
> a smaller model or on CPU.

**1. Install** (once, 2–5 minutes)

```bash
python install.py
```

Windows users can double-click `setup.bat` instead. This installs Python and frontend dependencies,
builds the frontend, and creates the directories the app needs.

**2. Download models** (once, optional — skip for quick-look mode)

```bash
python download-models.py
```

Pick which checkpoints and LoRAs you want — see [MODELS.md](MODELS.md).

**3. Start it**

```bash
python server.py
```

On Windows, double-click **`START MYTH FORGE.bat`** — it brings up every backend the app needs (the
theming LLM on :8010 and the strength engine on :8020) and then serves the app. `manage.bat start`
does the same from a terminal.

Then open **http://localhost:8000**.

**4. Check everything is up**

```bash
python verify-setup.py
```

Or `manage.bat status`, which reports all four services.

Full instructions and troubleshooting: **[INSTALL.md](INSTALL.md)** ·
**[docs/MAINTENANCE.md](docs/MAINTENANCE.md)**

---

## How a deck gets built

The decklist is generated **up front**, so the theme step can show the deck's real creature types for
per-tribe reskinning.

**1 · Commander & deck.** Search any legendary creature, pick a **power bracket (1–5)** and a
**playstyle** (Aggro, Control, Lifegain, … or Auto) — or switch to the **Import** tab to retheme a
deck you already own. On continue, the 99-card list is built immediately. Cards are drafted by
functional role (ramp / draw / removal / wipes / protection / finisher / theme), each window ordered
by **this commander's** EDHREC lift rather than global popularity, gated by the bracket rules, and
curve-aware so the deck can actually cast itself. Turn on **Build from my collection** and it prefers
— or with the strict option, uses *only* — cards you own.

**2 · Face.** Optionally upload 1–5 photos; humanoid card art will feature your likeness.

**3 · Theme.** A structured deck-idea intake: a Setting line plus genre / mood / lighting chips and
optional inspirations. These feed a **creative brief** that keeps every concrete thing you named (a
*faithfulness contract*) and invents extra detail to colour it — how much is set by a
**Faithful ↔ Balanced ↔ Imaginative** dial. Hit **🔮 Preview creative direction** to see the resulting
*world bible* — your motifs with ✓/⚠ coverage, the invented signature details, the palette, sample
themed cards — and iterate before committing. With art on, **🎨 Render these as real art** paints
those exact sample prompts (~2 min for 3 images, re-rollable) so you see the deck's look before the
full run.

Also here: **✨ Auto-theme creature types** (on by default) invents one theme-fitting replacement for
*every* creature type and applies it uniformly to each card's name, art, type line **and rules text**
— so a Dragon never renders as a cat, and *Knight → Cowboy* turns "equip Knight {0}" into "equip
Cowboy {0}". Override any individual type yourself. Plus frame style, border theme, custom mana pips,
art-style preset and the art toggle.

**4 · Deck.** Browse all 100 cards with rendered frames; download a ZIP or a print-ready PDF. Re-roll
three ways, each writing a *new* deck so the original is never lost:

- **🔄 Rebuild** — re-roll the art only, keeping current names and prompts.
- **✏️ Retheme** — new names *and* new art, same cards and settings.
- **🎛️ Edit & Rebuild** — re-open the wizard with every input pre-filled; change anything, then build.

You can also multi-select cards and regenerate just those, with optional custom prompts.

Deep detail on the renderer, themer and image pipeline: **[docs/INTERNALS.md](docs/INTERNALS.md)**.

---

## Import an existing deck

On the Commander step, switch to **📥 Import a deck**.

- **Archidekt** — paste the deck URL. Reliable; the importer honours the deck's own
  "included in deck" category flags rather than guessing from category names.
- **Moxfield** — paste the deck URL. Best-effort: Moxfield guards its API, so fall back to pasting.
- **Pasted decklist** — any text list (ManaBox, MTGO, Deckstats, paper). Quantities, `1x` syntax,
  `(SET) 123` suffixes, `*CMDR*` tags and zone headers are all understood; sideboard and maybeboard
  sections are ignored.

**Notes.** URL imports need a public deck. The commander is auto-detected from the source's commander
zone; **any decklist imports**, though — a 60-card list with no commander gets a display "face"
auto-elected from the maindeck, and you can override it. Card names that can't be matched on Scryfall
are reported by name and skipped rather than silently dropped. Imported decks and resolved card data
are cached, so re-importing the same deck makes **no network calls**.

**The imported list is immutable.** Theming may re-invent every name and every image, but nothing in
the pipeline is allowed to change *which* cards are in your deck — rebuild, retheme and Edit &
Rebuild all preserve it verbatim.

---

## Measured, not guessed

Myth Forge builds and prints; the **MythGauntlet** engine at `src/mythgauntlet/` measures. It
simulates thousands of games to produce a six-axis Power Profile and a **1–5 Commander bracket**
calibrated against author-labeled decks, plus an advisor that ranks upgrades from cards you already
own.

On a finished or imported deck you get:

- **Bracket + Power Profile** — simulation-grounded, not a static heuristic score.
- **Upgrade advisor** — what to add from your collection, and what to cut. Cut candidates are chosen
  by **redundancy** (which functional role is over-supplied), not by which card is least popular —
  because your least-played cards are usually your pet cards, silver bullets and vegetables.
- **Card impact** — would this one card help or hurt this deck, and why.
- **Duel** — a head-to-head 1v1 win rate against a friend's pasted decklist.
- **Deck health** — mana curve and colour sources: can this deck actually cast what it drafted?
- **Archetypes** — detected from the 99, not just the commander's oracle text, and gated on *lift*
  over each theme's base rate. Around half of real decks have no statistically-real archetype, and
  the panel says so rather than inventing one.
- **Off-meta read** — how far this deck sits from its commander's norm. A precon and a wild brew can
  rate the same bracket; this is the axis that separates them.

There is exactly **one** analysis implementation in this repo. When the engine isn't running, the UI
says a number is unavailable rather than substituting a second, weaker guess.

> ⚠️ **The engine's ~30k compiled card semantics are NOT included.** That store is still being
> trained and is withheld for now. The engine runs without it on Oracle-text fallbacks, at reduced
> fidelity. See **[docs/ENGINE_DATA.md](docs/ENGINE_DATA.md)** for exactly what's missing and how to
> build your own. Engine internals live in **[docs/engine/](docs/engine/)**.

---

## Your collection

Myth Forge reads and writes the shared Myth Suite collection at
`Documents/MythSuite/collection.csv` — the same file [MythScanner](#the-myth-suite) writes when you
scan cards with a webcam.

Browse it as a binder with real card images, filter by colour / type / rarity / set / mana value,
track printings and market value, and import a Moxfield CSV or plain decklist. A health check finds
rows whose "name" is really a whole decklist line (`13x Island (msh) 290 *F* [Land]`) and offers to
repair them — every write leaves a backup, and Undo is one click.

That collection then feeds deck building (prefer or restrict to what you own) and the upgrade
advisor. A **Buildable** panel ranks which commanders you own could make a real bracket 1–3 deck.

---

## Beyond the deck

**✨ Animated cards.** Select cards and animate them into looping clips. Two independent effects:
a local **image-to-video** model (LTX-Video or Wan 2.x, supply your own weights) animates only the
*art* while each frame is recomposited through the normal renderer so the frame, text and mana
symbols stay perfectly crisp — and a **procedural foil/holo sweep** that needs no model at all and
runs on CPU. Export as MP4, animated WebP or GIF, individually or as a ZIP. The static PNG stays the
print.

**🗿 3D commander models.** Commander art → background removal → Hunyuan3D v2 → a printable **STL**,
scaled to ~60 mm.

**🖨️ Export.** Card PNGs as a ZIP, a print-ready PDF at 2.5″×3.5″ @ 300 DPI (quantity-replicated, so
all your basics are there), a decklist that round-trips back through Import, and a videos ZIP.

---

## Requirements

**Developed and tested on** (full AI-art pipeline): NVIDIA RTX 3090 (24 GB), Ryzen 7 5800X3D, 32 GB
RAM, Windows. Python 3.10+ (CI runs 3.12).

| Build | Time on a 3090 |
|---|---|
| 100 cards, FLUX Schnell | ~18–20 min |
| 100 cards, FLUX Dev (premium) | ~70–75 min |
| Peak usage | 2–3 GB system RAM, 12–14 GB VRAM |

| Other hardware | Guidance |
|---|---|
| RTX 4080 (16 GB) | FLUX Schnell only, ~20–30 % slower |
| RTX 4070 (12 GB) | FLUX Schnell, marginal fit |
| Smaller GPUs | Fall back to Scryfall artwork (no local art generation) |
| Mac M-series | CPU-only generation, much slower |

Tuning and batch sizing: [docs/HARDWARE_OPTIMIZATION_GUIDE.md](docs/HARDWARE_OPTIMIZATION_GUIDE.md).

### Services

| Service | Port | Purpose | Required? |
|---------|------|---------|-----------|
| FastAPI / Uvicorn | 8000 | Backend API + serves the React frontend | **Yes** |
| Local LLM gateway | 8010 | Card theming, names, flavor text, art prompts (`qwen3:14b` default) | **Yes** |
| MythGauntlet engine | 8020 | Deck strength, bracket, upgrade advisor | For analysis |
| ComfyUI | 8188 | AI image generation (FLUX / SDXL), animation, 3D | For custom art |

> **LLM backend.** Myth Forge talks to an **OpenAI-compatible endpoint** — by default a
> [llama-swap](https://github.com/mostlygeek/llama-swap) gateway in front of `llama-server`
> (llama.cpp), which auto-loads GGUF models on demand and unloads them when idle. Prefer **Ollama**?
> Set `MYTHFORGE_LLM_BACKEND=ollama` — the easiest path for a first install. `MYTHFORGE_LLM_BASE`
> overrides the endpoint URL.

The strength engine runs as a **separate process on purpose**: it holds the card-semantics store in
memory (~50 s cold, ~1.4 s warm), so keeping it out of the web server keeps restarts fast. Starting
the app auto-starts the LLM gateway and the engine if they aren't already listening; ComfyUI is only
needed for image generation and starts separately (`manage.bat` → Option 3).

### When something isn't working

| Symptom | Fix |
|---|---|
| "Port 8000 already in use" | `netstat -ano \| findstr :8000` then `taskkill /PID <pid> /F` |
| ComfyUI not detected | Ensure it's running on 8188; start it via `manage.bat` → Option 3 |
| LLM backend not detected | Simplest path: install [Ollama](https://ollama.ai), `ollama pull qwen3:14b`, `ollama serve`, set `MYTHFORGE_LLM_BACKEND=ollama` |
| Bracket / strength says "unavailable" | The engine on :8020 is still loading (~50 s cold) or not running |
| Theming worked but there's no art | ComfyUI needs `--disable-async-offload` — see [docs/INTERNALS.md](docs/INTERNALS.md#known-behaviours--gotchas) |
| Server not responding | Check the in-app **📜 Logs** viewer, or `server.log` |

More by symptom: [docs/MAINTENANCE.md](docs/MAINTENANCE.md) · full menu reference:
[SCRIPTS.md](SCRIPTS.md)

---

## Project layout

```
mtg_deck_builder/
├── server.py                 FastAPI backend — every HTTP route, async build jobs, SSE progress
├── deck_builder.py           Builds the 99 (lands/ramp/draw/removal/synergy/goodstuff)
├── commander_analysis.py     Parses oracle text → detects mechanical themes
├── playstyle.py              15 playstyle presets → theme keys + slot adjustments
├── bracket.py                EDH bracket level definitions (1–5)
├── edhrec_lift.py            Per-commander EDHREC lift — orders every candidate window
├── deck_quality.py           Mana curve + colour-source measurement
├── deck_themes.py            Archetypes detected from the deck's cards, gated on lift
├── lift_stats.py             "How off-meta is this deck" — the axis bracket doesn't measure
├── theme_match.py            Offline reproduction of the theme queries, for owned-only builds
├── themer.py                 Local LLM: themed names, art prompts, flavor text (batched)
├── image_gen.py              ComfyUI: FLUX/SDXL/Krea/Qwen generation + face conditioning
├── face_ref.py               Face upload management + humanoid card detection
├── card_renderer.py          Pillow: composites frame PNGs into print-ready proxy cards
├── cc_frames.py              Optional M15 / borderless frames from a local Card Conjurer
├── card_video.py             Card animation (I2V motion) + procedural foil/holo
├── model3d.py                Commander art → Hunyuan3D v2 → printable STL
├── set_symbol.py             Per-deck set symbol, tinted by card rarity
├── mana_pips.py              Optional deck-branded mana pips
├── deck_import.py            Import/retheme an existing Moxfield/Archidekt/text deck
├── collection*.py            Owned-card store, offline index, role pool, repair, stats
├── exporter.py               ZIP + print-ready PDF export
├── scryfall_client.py        Scryfall API wrapper (rate-limited, cached)
├── src/mythgauntlet/         The simulation engine — sim/, semantics/, ratings/, model/, agents/
├── frontend/                 React + Vite SPA (built to frontend/dist, served by FastAPI)
├── card_assets/              Bundled frame assets, fonts, mana symbols
├── docs/                     Guides, specs and engine documentation
├── tests/                    Pytest suite, incl. tests/engine/
├── scripts/                  Dev tooling: corpus benchmarks, CCM training, offload harness
├── utilities/                Sample-sheet generation, CUDA/DLL helpers
├── START MYTH FORGE.bat      Windows one-click launcher (starts all backends + the app)
├── manage.bat                Windows menu: start/stop/status/setup/models/ComfyUI
├── setup.bat / install.py    First-time setup
└── verify-setup.py           Checks deps, frontend build, engine and services
```

---

## Documentation

**Setup & troubleshooting**
- [INSTALL.md](INSTALL.md) — install and start, step by step
- [MODELS.md](MODELS.md) — checkpoints, LoRAs, face models + download links
- [COMFYUI_SETUP.md](COMFYUI_SETUP.md) — ComfyUI launch flags, VRAM, ReActor
- [SCRIPTS.md](SCRIPTS.md) — full `manage.bat` menu and direct commands
- [docs/MAINTENANCE.md](docs/MAINTENANCE.md) — troubleshooting by symptom

**Reference**
- [docs/INTERNALS.md](docs/INTERNALS.md) — renderer, themer, image generation, faces, animation
- [docs/API.md](docs/API.md) — every HTTP endpoint
- [docs/GALLERY.md](docs/GALLERY.md) — thirteen full themed decks
- [docs/COLLECTION_MODES.md](docs/COLLECTION_MODES.md) — the three collection build modes
- [docs/HARDWARE_OPTIMIZATION_GUIDE.md](docs/HARDWARE_OPTIMIZATION_GUIDE.md) — GPU tuning

**The engine**
- [docs/ENGINE_DATA.md](docs/ENGINE_DATA.md) — what data ships, what doesn't, how to build your own
- [docs/engine/](docs/engine/) — architecture, simulation, card semantics, roadmap

**Contributing**
- [docs/DEVELOPMENT_GUIDELINES.md](docs/DEVELOPMENT_GUIDELINES.md) — read before changing code
- [CLAUDE.md](CLAUDE.md) — the engineering map (dense, agent-oriented)
- [docs/INDEX.md](docs/INDEX.md) — the full doc map

Run the tests with `python -m pytest tests -q`. CI runs the same suite plus a frontend build on every
push.

---

## The Myth Suite

Myth Forge is one of three tools sharing one collection file:

- **Myth Forge** *(this repo)* — build, theme, print and measure decks.
- **MythScanner** — scan your physical cards with a webcam; writes the shared collection.
- **MythGauntlet** — the trained card-semantics data the engine consumes (withheld while training).

---

## Credits & legal

Bundled frame assets are sourced from **wingedsheep/mtg-card-generator**. Card data and images come
from the **[Scryfall](https://scryfall.com)** API at runtime. Optional official-style M15 frames are
rendered from a **[Card Conjurer](https://github.com/Investigamer/cardconjurer)** installation you
supply yourself — none of that artwork is in this repo, and it should not be committed here.

Myth Forge is an unofficial fan project, not produced by, endorsed by or affiliated with Wizards of
the Coast. *Magic: The Gathering* and all associated names, rules text and designs are trademarks and
copyrights of Wizards of the Coast. Cards produced by this tool are proxies for personal,
non-commercial playtesting.

No AI model weights are distributed here — you download those yourself, and several carry
non-commercial terms, so check the license of each model you install.

Code is licensed under the [MIT License](LICENSE). Full third-party attribution and the game-content
notice: [NOTICE.md](NOTICE.md).

---

## Support

Myth Forge is free, open, and runs entirely on your own machine. If it saved you a stack of proxy
cash, a coffee helps keep it improving.

<div align="center">

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-FFDD00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/onemorethan0)

*Myth Forge by OneMoreThan0* ⚔️

</div>
