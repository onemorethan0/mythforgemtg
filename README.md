# Myth Forge — MTG Commander Deck Builder

A fully local web app that builds themed 100-card EDH Commander decks with AI-generated custom card art and proxy frames using real MTG card assets.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-FFDD00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/onemorethan0)

> Myth Forge is free and fully local. If it saved you a stack of proxy cash, [buying me a coffee](https://www.buymeacoffee.com/onemorethan0) ☕ helps keep it improving.

---

## System Requirements

**Developed & Tested On:**
- **GPU**: NVIDIA RTX 3090 (24GB VRAM)
- **CPU**: AMD Ryzen 5800X3D
- **System RAM**: 32GB

**Performance on RTX 3090 + 32GB:**
- 100-card build with FLUX Schnell: ~18-20 minutes
- 100-card build with FLUX Dev (premium quality): ~70-75 minutes
- Peak memory usage: 2-3 GB system RAM, 12-14 GB VRAM

**Other Systems:**
- RTX 4080 (16GB): Use FLUX Schnell only, ~20-30% slower
- RTX 4070 (12GB): Use FLUX Schnell, marginal fit
- Smaller GPUs: Fallback to Scryfall artwork (no FLUX generation)
- Mac M-series: CPU-only generation, much slower

See [docs/HARDWARE_OPTIMIZATION_GUIDE.md](docs/HARDWARE_OPTIMIZATION_GUIDE.md) for detailed analysis and batch size tuning.

---

## Services Required

| Service | Port | Purpose |
|---------|------|---------|
| FastAPI / Uvicorn | 8000 | Backend API + serves React frontend |
| Ollama (`qwen3:14b` default) | 11434 | Card theming, names, flavor text, art prompts |
| ComfyUI | 8188 | AI image generation (FLUX or SDXL) |

---

## Quick Start

### 1. **First-Time Setup** (One Time Only)

**Windows:**
```cmd
setup.bat
```

**Mac/Linux:**
```bash
python install.py
```

This will:
- ✓ Install Python dependencies
- ✓ Install frontend dependencies  
- ✓ Build the frontend
- ✓ Create necessary directories

**Expected time:** 2-5 minutes

### 2. **Download Models** (One Time Only)

**Windows:**
```cmd
manage.bat
→ Option 7: Download AI Models
```

**Mac/Linux:**
```bash
python download-models.py
```

Choose which models to download (see [MODELS.md](./MODELS.md) for details).

### 3. **Start the Server**

**Windows (Recommended):**
```cmd
manage.bat
```
Select Option 1: Start Development Server

**Or directly:**
```cmd
dev.bat
```

**Mac/Linux:**
```bash
python server.py
```

Then open your browser to: **http://localhost:8000**

### 4. **Check Service Status**

**Windows:**
```cmd
manage.bat
→ Option 3: Check Server Status
```

Shows status of:
- ComfyUI (port 8188)
- Myth Forge (port 8000)
- Ollama (port 11434)

> **Note:** ComfyUI must be running in a separate window. Ollama auto-starts with the server.

---

## Server Management

**See [SCRIPTS.md](./SCRIPTS.md) for:**
- Complete menu options
- Common workflows
- Troubleshooting
- Direct command access

**"Port 8000 already in use"?**
```cmd
netstat -ano | findstr :8000
taskkill /PID <process_id> /F
```

**ComfyUI not detected?**
- Ensure ComfyUI is installed and running on port 8188
- Start manually: `python ComfyUI/main.py --port 8188`

**Ollama not detected?**
- Download & install Ollama: https://ollama.ai
- Pull the default model: `ollama pull qwen3:14b`
- Start: `ollama serve`

**Server not responding?**
- Check `server.log` for errors
- Ensure Ollama/ComfyUI ports aren't blocked
- Try stopping and restarting the server

---

## Optional: Model & Image Generation Setup

See **[MODELS.md](./MODELS.md)** for detailed instructions on downloading:
- **Checkpoints** (FLUX, SDXL, SD 3.5) for image generation
- **LoRAs** (MTG v2, Composition, Realism, etc.) for style enhancement
- **Face conditioning** (PuLID, ReActor) for character art

The app works with any checkpoint you have installed. Start with FLUX Schnell for good quality and speed.

---

## User Flow (5 steps)

1. **Commander** — Either **Generate a deck** (search any legendary creature, fuzzy Scryfall lookup) or **Import a deck** (retheme one you already own — see below)
2. **Playstyle** — Choose from 15 preset styles (Aggro, Control, Lifegain, Aristocrats, etc.) or Auto-detect
3. **Face** — Optionally upload 1–5 photos; humanoid card art will feature your likeness
4. **Theme** — Free-text art theme ("dark gothic necromancer city"), bracket level, and art gen toggle
5. **Deck** — Browse all 100 cards with rendered proxy frames, download ZIP or print PDF

---

## Importing an existing deck

On the **Commander** step, switch to the **📥 Import a deck** tab to retheme a deck you already built elsewhere instead of generating a new list.

**Supported sources:**
- **Archidekt** — paste the deck URL (`https://archidekt.com/decks/...`). Reliable.
- **Moxfield** — paste the deck URL (`https://www.moxfield.com/decks/...`). Best-effort: Moxfield guards its API, so if a link fails, use the paste option below.
- **Pasted decklist** — paste any text list (works for **ManaBox** — export your deck as text in the app — and any other site). Format:
  ```
  Commander
  1 Atraxa, Praetors' Voice

  Deck
  1 Sol Ring
  1 Arcane Signet
  10 Forest
  ```
  Quantities, `1x` syntax, `(SET) 123` suffixes, and `*CMDR*` tags are all understood; sideboard/maybeboard sections are ignored.

**Notes:**
- The deck must be **public** for URL imports.
- The commander is auto-detected from the source's commander zone; if none is found you'll be prompted to type one.
- Any card name that can't be matched on Scryfall is reported and skipped.
- **Caching:** imported decks and resolved card data are cached under `cache/` — re-importing the same deck (or any card you've seen before) makes **no network calls**. Use **↻ Re-pull** to force a fresh fetch.
- Duplicate basic lands are themed once and the art reused for every copy; your ZIP/PDF export still contains all physical proxies.

Once imported, the rest of the flow (face, theme, custom pips, art generation, 3D, regen/retheme) works exactly as it does for generated decks.

---

## Project Structure

```
mtg_deck_builder/
├── server.py               FastAPI backend — all HTTP routes
├── scryfall_client.py      Scryfall API wrapper (rate-limited, cached)
├── commander_analysis.py   Parses oracle text → detects ~30 mechanical themes
├── playstyle.py            15 playstyle presets → theme keys + slot adjustments
├── deck_builder.py         Builds 99-card deck (lands/ramp/draw/removal/synergy/goodstuff)
├── themer.py               Ollama: themed names, art prompts, flavor text (batched 8/call)
├── image_gen.py            ComfyUI: SDXL/FLUX image generation + face conditioning
├── face_ref.py             Face upload management + humanoid card detection logic
├── card_renderer.py        Pillow: composites real MTG frame PNGs into proxy cards
├── set_symbol.py           Generates a unique set symbol SVG for the deck
├── exporter.py             ZIP + print-ready PDF export
├── bracket.py              EDH bracket level definitions (1–5)
├── requirements.txt        Python dependencies
├── manage.bat              Windows menu: start/stop/status/setup/models/ComfyUI
├── dev.bat                 Windows: start the dev server directly
├── setup.bat / install.py  First-time setup (deps + frontend build)
├── download-models.py      Interactive checkpoint downloader
├── start-mythforge.sh      Mac/Linux: start the server
├── card_assets/            Real MTG frame assets (see below)
└── frontend/               React + Vite frontend
    └── src/
        ├── App.jsx
        └── components/
            ├── StepCommander.jsx
            ├── StepPlaystyle.jsx
            ├── StepFace.jsx      ← gender selector here
            ├── StepTheme.jsx
            ├── StepBuilding.jsx  ← SSE progress stream
            └── StepDeck.jsx
```

---

## Card Assets (`card_assets/`)

All assets sourced from **wingedsheep/mtg-card-generator**.

```
card_assets/
├── frames/         18 PNGs — W U B R G + 10 two-color pairs + Gold Artifact Colourless
├── bg/             20 PNGs — background textures per color identity
├── boxes/          9 PNGs  — name bar + type bar strips per color
├── pt_boxes/       10 PNGs — power/toughness badge per color
├── legendary_crowns/ 19 PNGs — crown overlay for legendary creatures
├── symbols/        84 SVGs — tap (T), W U B R G, X, 0–20, hybrid pips
└── fonts/
    ├── beleren-bold_P1.01.ttf   Card name font
    ├── mplantin.ttf             Oracle text font
    └── MPlantin-Italic.ttf      Flavor text + subtitle font
```

**Color key logic:** Single color → that color's assets. Two colors → sorted WUBRG pair. Three+ → Gold. Artifact type → Artifact. Land type → Land. No colors → Colourless.

---

## Card Renderer (`card_renderer.py`)

Renders at **3× resolution (1440×2016)** for supersampled anti-aliasing, then LANCZOS downscales to **750×1050** (2.5″×3.5″ @ 300 DPI — print-ready, no upscaling needed).

Layer order (bottom to top):
1. Solid black base
2. Background texture PNG
3. Card art (ComfyUI-generated or Scryfall fallback, cropped/scaled)
4. Frame PNG overlay
5. **Border theme tint** — optional thematic colour overlay on the frame chrome
6. Boxes PNG — top slice = name bar, bottom slice = type bar
7. Legendary crown (if applicable)
8. Text and inline SVG mana pip symbols
9. Power/toughness badge

**Border theme:** Each deck can specify a free-text border theme (e.g. `"fire and ash"`, `"arcane runes"`, `"frost crystals"`). The renderer classifies the description into one of 7 colour palettes (flame, frost, arcane, circuit, wave, shadow, vine) and alpha-composites a tinted fill over the full chrome band on all four sides, plus corner ornaments. Intensity survives the 3×→1× LANCZOS downscale because the fill covers the entire chrome width (~22 px at output).

**Subtitle feature:** If the themed card name differs from the original Scryfall name, the original name is drawn in small italic text at the bottom of the name bar. Useful for identifying proxies.

**SVG symbol rendering:** Uses `pixie-python` (pure Python, no libcairo required on Windows). Each symbol is rasterized to a temp PNG then loaded as a PIL Image.

---

## Themer (`themer.py`)

Runs against **Ollama `qwen3:14b`** locally (auto-falls back to `qwen3:32b` → `qwen2.5-coder:14b` → `gemma4` if the primary model is missing).

1. Generates one deck-wide **style guide** sentence (used only as LLM context, NOT prepended to FLUX prompts)
2. Processes cards in **batches**, each receiving the style guide as context
3. Each card gets: `themed_name`, `art_prompt` (35–50 words), `flavor_text`
4. **Name → art coherence (#1 rule):** the `art_prompt` must *depict* the themed name's imagery (2–3 concrete visual elements), and every card's scene must be unique (no reused templates)
5. **Color = mana identity:** each card's palette is driven by its color identity (`_color_palette_hint`: W=ivory/gold, U=arcane blue, B=shadow/necrotic, R=fire/crimson, G=verdant, colorless=chrome), deferring to user-theme colors for characters — mirroring real MTG
6. Ollama is **unloaded from GPU** after theming so ComfyUI can claim the VRAM

**Prompt pipeline (togglable):** `USE_ENHANCED_PROMPTS` at the top of `themer.py` switches between two pipelines:

- **v1 (legacy):** World-immersion style — prompt wraps card in the theme aesthetic
- **v2 (dual-anchor, default):** Each card is pre-classified by its mechanical role (`_card_soul()`) producing a `soul_phrase` (e.g. *"divine judgment, everything obliterated simultaneously"* for a boardwipe). The LLM receives both the soul (what the card *does*) and the theme skin (world aesthetic), producing prompts that feel true to both the MTG mechanic and the setting.

**Art prompt rules enforced via system prompt:**
- Color palette driven by the card's mana identity (see above), not a fixed deck palette
- Themed name depicted as concrete visual elements; scenes unique per card
- No close-up hands — poses that hide/glove/arm hands
- Landscape composition (framing free to vary — no forced centering)
- Each prompt ends with a quality closer phrase
- Mechanic keywords mapped to visual cues (Flying → wings spread, Deathtouch → necrotic aura, etc.)

---

## Image Generation (`image_gen.py`)

Auto-detects checkpoint type (FLUX vs SDXL) and best available face method.

**Checkpoints:** `C:\Users\rvn92\Documents\ComfyUI\models\checkpoints\`

**SDXL settings:** 30 steps, CFG 7.5, DPM++ 2M Karras
**FLUX dev settings:** 35 steps, KSampler **CFG 1.0** + a **FluxGuidance** node (default 3.5), dpmpp_2m + sgm_uniform
**FLUX schnell:** 8 steps, CFG 1.0, euler + simple (no FluxGuidance, no LoRAs)

> **Why CFG 1.0 + FluxGuidance, not CFG 3.5 in the KSampler?** FLUX-dev is guidance-distilled; driving it with true CFG > 1 over-guides the latent to a blown-out near-white frame. Correct usage is KSampler CFG 1.0 with a FluxGuidance conditioning node (~3.5). The negative prompt is therefore inert on FLUX (it steers from the positive). Guidance/steps are user-tunable via the Theme step's Advanced panel (see Generation Settings below).

**Positive prompt structure:**
```
[LoRA trigger words] + [style flux_prefix] + [art_prompt] + [face suffix if face card]
```
The deck-wide style guide is **not** prepended to FLUX prompts (the `flux_prefix` owns the art style; prepending the style guide caused medium conflicts). Per-card **color comes from the card's mana identity** (see Themer), not a fixed deck palette.

### Art Style Presets

Each preset is a curated LoRA stack with its own prompt prefix, negative prompt, and themer hints. LoRAs are auto-detected by filename fragment — drop the `.safetensors` file in `ComfyUI/models/loras/` and it activates automatically.

| Key | Label | Icon | LoRA file(s) |
|-----|-------|------|--------------|
| `mtg_fantasy` | MTG Fantasy | ⚔️ | `df_style_v1.1.safetensors`, `aidmaMTGCard-FLUX-V0.1.safetensors` |
| `photorealism` | Photorealism | 📷 | `xlabs_realism_lora.safetensors` |
| `cyberpunk` | Cyberpunk | 🌆 | `kcyberpunk-02` + `Neon_Cyberpunk_Detailer` (per-card rotation with `boFLUX_Abyss_Neon`) |
| `desert_punk` | Desert Punk | 🏜️ | `retrofuture_*.safetensors` |
| `anime` | Anime / Manga | 🎌 | `flatcolor_anime_flux.safetensors` — flat cel-shaded |
| `anime_illustrated` | Anime Illustrated | ✨ | `semi_realistic_anime_flux.safetensors` — detailed shading & depth |
| `anime_soft` | Anime Artbook | 🌸 | `softserve_anime_flux.safetensors` — painterly artbook quality |
| `art_nouveau` | Art Nouveau | 🌿 | `mucha_style_flux.safetensors` |
| `gothic_horror` | Gothic Horror | 🦇 | `Dark_Gothic_Horror*.safetensors`, `Dark_Haunted_Fantasy*.safetensors` |
| `watercolor` | Watercolor | 🎨 | `WATERCOLOR-lora*.safetensors` |
| `steampunk` | Steampunk | ⚙️ | `SteampunkIllustration_v1.safetensors` |
| `oil_painting` | Oil Painting | 🖼️ | *(no LoRA — prompt-only)* |
| `pixel_art` | Pixel Art | 🕹️ | `Pixel_Art_FLUX.safetensors` |
| `eldritch` | Eldritch Horror | 👁️ | `Eldritch_Comics_for_Flux*.safetensors` |
| `stained_glass` | Stained Glass | 🪟 | `Stained_Glass_Style.safetensors` |

**Anime style guide:**
- 🎌 **Anime / Manga** — flat colour, cel-shaded, clean linework. Classic 2D TV animation look.
- ✨ **Anime Illustrated** — semi-realistic anime; highly detailed facial features, realistic lighting, rich depth. ([civitai.com/models/754435](https://civitai.com/models/754435))
- 🌸 **Anime Artbook** — soft painterly rendering, artbook/key-visual quality. ([huggingface.co/alvdansen/softserve_anime](https://huggingface.co/alvdansen/softserve_anime))

**Face conditioning methods** (auto-detected, best available wins):
| Method | Requirement | Quality |
|--------|------------|---------|
| PuLID FLUX | ComfyUI_PuLID_Flux node + pulid model | Best |
| IP-Adapter FaceID | ComfyUI-IPAdapter-plus (SDXL only) | Great |
| ReActor face swap | ComfyUI-ReActor node | Good |
| None | — | Text-only hint |

**ReActor settings:** `inswapper_128.onnx`, `codeformer-v0.1.0.pth`, `retinaface_resnet50` face detection, `codeformer_weight = 0.3` (lower = more identity preserved)

---

## Face Reference System (`face_ref.py`)

**Upload path:** `face_uploads/{face_key}/face_00.jpg` etc.

**Which cards get face treatment:**
- Commander: **always**
- Non-commander cards: only if the type line contains a humanoid subtype AND fewer than **4** non-commander face cards have been used
- Humanoid subtypes: Human, Warrior, Wizard, Shaman, Cleric, Knight, Rogue, Monk, Druid, Ranger, Paladin, Assassin, Pirate, Noble, Artificer, Scout, Mercenary, Rebel, Samurai, Ninja, Archer, Spellcaster, Hero, Champion, Lord, Queen, King, Prince, Princess, God, Demigod, Avatar, Bard, Warlock, Sorcerer, Alchemist, Investigator, Renegade, Duelist

**Excluded even if Legendary:** Dragons, Krakens, Beasts, Elementals, and other non-humanoid creature types never receive face treatment.

**Gender matching:** The face step includes a Female / Male / Either toggle. The selected gender is injected as a prompt qualifier (`"male character, "` / `"female character, "`) **only** for cards receiving face conditioning. All other cards render with whatever gender the themer's art prompt naturally describes.

---

## Generation Settings (Advanced panels)

The Theme and Face steps each have a collapsible **⚙ Advanced** panel, driven by a single schema (`frontend/src/config/genSettings.js`) with a structural **Reset to defaults** button and `localStorage` persistence. Values flow `gen_settings → BuildRequest → ImageGen → workflow builders`:

- **Theme:** FLUX guidance (1.5–5), sampler steps, seed (random/fixed), a **LoRA picker** (override the preset stack + per-LoRA strength), and **Safe mode**.
- **Face:** face method (auto/ReActor/PuLID/none) and PuLID identity strength.
- **Safe mode** lowers steps + resolution to reduce peak GPU/CPU load (mitigates crashes on unstable hardware — see Gotchas).
- The fully-resolved settings are logged once per build as `[gen_settings] {...}`.

## 3D Commander Models (`model3d.py`)

Optional pipeline: commander art → **rembg** background removal → **Hunyuan3D v2** (ComfyUI) → GLB → **STL** (trimesh), scaled to ~60 mm for printing. Octree resolution defaults to 384 (`MYTHFORGE_3D_RES` to override). Exposed via `/api/deck/{job_id}/generate-3d` (SSE progress) and `/api/3d-health`.

## In-app log viewer

A **📜 Logs** button (header) streams the server's in-memory log buffer via `GET /api/logs` — captures stdout/stderr, pipeline prints, tracebacks, and uvicorn access logs regardless of how the server was launched.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/commander/search` | Fuzzy commander lookup via Scryfall |
| POST | `/api/deck/import-preview` | Resolve a deck URL / pasted list (commander + counts), cached |
| GET | `/api/playstyles` | List all 15 playstyle options |
| GET | `/api/art-styles` | List all art style presets + LoRA install status |
| GET | `/api/comfyui/loras` | List installed LoRA files (feeds the LoRA picker) |
| GET | `/api/logs` | Recent server log lines (in-memory ring buffer) |
| GET | `/api/3d-health` | Hunyuan3D v2 / rembg availability |
| POST | `/api/deck/{job_id}/generate-3d` | Start commander 3D (STL) generation |
| GET | `/api/face-method` | Probe which face engine ComfyUI supports |
| POST | `/api/upload-face` | Upload 1–5 face reference photos |
| POST | `/api/deck/build` | Start async deck build → `{job_id}` |
| GET | `/api/deck/{job_id}/events` | SSE stream of build progress |
| GET | `/api/deck/{job_id}/status` | Poll build status |
| GET | `/api/deck/{job_id}` | Full deck payload once complete |
| GET | `/api/deck/{job_id}/card-image/{key}` | Rendered card proxy PNG |
| GET | `/api/deck/{job_id}/set-symbol` | Deck set emblem PNG |
| POST | `/api/deck/{job_id}/retheme` | Re-run Ollama theming, reuse existing art |
| POST | `/api/deck/{job_id}/rebuild` | Re-generate card art, keep existing themes |
| POST | `/api/deck/{job_id}/regen-cards` | Regenerate art for specific cards only |
| POST | `/api/deck/{job_id}/cancel` | Cancel an in-progress build |
| GET | `/api/deck/{job_id}/export/zip` | Download all card PNGs as ZIP |
| GET | `/api/deck/{job_id}/export/pdf` | Download print-ready PDF |

**BuildRequest body:**
```json
{
  "commander_name": "Teysa Karlov",
  "playstyle": "auto",
  "bracket": 3,
  "art_theme": "dark gothic necromancer city",
  "generate_art": true,
  "face_key": "abc12345",
  "face_gender": "female",
  "gen_settings": { "guidance": 3.5, "steps": 35, "safe_mode": false }
}
```
`gen_settings` is optional; omitting any field falls back to the model default (see `GenSettingsModel` in `server.py` / `GenSettings` in `image_gen.py`).

---

## Dependencies

```
requests>=2.31.0
pillow>=12.0.0
fastapi>=0.130.0
uvicorn>=0.47.0
anthropic>=0.100.0
python-multipart>=0.0.9
pixie-python>=4.3.0
```

Any **Python 3.10+** works. (The dev machine happens to use `C:\Python314\python.exe`; the scripts call whatever `python` is on your PATH.)

---

## Known Behaviours / Gotchas

- **Server restart required after Python changes** — uvicorn's `reload=True` watches for file changes and restarts automatically, but only if the process is still alive. Kill old processes before relaunching.
- **Ollama ↔ ComfyUI VRAM sharing** — Themer unloads Ollama from GPU after card theming; server also POSTs to `/free` on ComfyUI before theming begins. Both steps are necessary on single-GPU systems.
- **Scryfall rate limiting** — 150ms sleep between requests. Running multiple builds back-to-back is fine for single-user use.
- **Art generation is optional** — Toggle `generate_art: false` to skip ComfyUI entirely; Scryfall card art is used as fallback and frames still render.
- **pixie-python SVG rasterization** — `pixie.Image.resize()` is NOT in-place. Must create a new `pixie.Image(w, h)` as destination, then `ctx.scale() + ctx.draw_image(src, 0, 0)`.
- **Whole-machine reboots during generation are HARDWARE, not the app.** On the 5800X3D dev machine these were a CPU **Machine Check Exception ("Cache Hierarchy Error")** in the Windows event log (WHEA Id 18 → Kernel-Power 41) — the classic signature of an unstable PBO/Curve-Optimizer undervolt or unstable EXPO/XMP RAM under combined CPU+GPU load. Fix in BIOS (run CPU/RAM at stock, then stress-test); use the Theme step's **Safe mode** to reduce load meanwhile.

---

## Documentation

See **[docs/](docs/)** for complete documentation:

**For Setup & Troubleshooting:**
- **[INSTALL.md](INSTALL.md)** — install + start, step by step
- **[COMFYUI_SETUP.md](COMFYUI_SETUP.md)** — ComfyUI launch flags, VRAM, ReActor
- **[docs/MAINTENANCE.md](docs/MAINTENANCE.md)** — Troubleshooting by symptom, optimization

**For Developers:**
- **[docs/DEVELOPMENT_GUIDELINES.md](docs/DEVELOPMENT_GUIDELINES.md)** — **Mandatory** guidelines for code changes. Read before making any changes.
- **[docs/HARDWARE_OPTIMIZATION_GUIDE.md](docs/HARDWARE_OPTIMIZATION_GUIDE.md)** — GPU tuning and batch size analysis

**Also useful:**
- **[MODELS.md](MODELS.md)** — checkpoints, LoRAs, face models + download links
- **[SCRIPTS.md](SCRIPTS.md)** — full `manage.bat` menu reference and direct commands

**Special Notes:**
- **CUDA 12.x Required for Face Conditioning** — Download from https://developer.nvidia.com/cuda-downloads

---

## Support

Myth Forge is free, open, and runs entirely on your own machine. If it's been useful, you can support continued development:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-FFDD00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/onemorethan0)

*Myth Forge by OneMoreThan0 ⚔️*
