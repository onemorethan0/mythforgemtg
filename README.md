# Commander Forge — MTG Commander Deck Builder

A fully local web app that builds themed 100-card EDH Commander decks with AI-generated custom card art and proxy frames using real MTG card assets.

---

## Services Required

| Service | Port | Purpose |
|---------|------|---------|
| FastAPI / Uvicorn | 8000 | Backend API + serves React frontend |
| Ollama (`qwen2.5:14b`) | 11434 | Card theming, names, flavor text, art prompts |
| ComfyUI | 8188 | AI image generation (SDXL or FLUX) |

Start everything with:
```
start_app.bat
```
Then open **http://localhost:8000**

> **Restarting after code changes:** `start_app.bat` skips services it thinks are already running. Kill the old `python.exe server.py` process in Task Manager first, then run the bat, or kill it via PowerShell:
> ```powershell
> Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*server.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
> ```

---

## User Flow (5 steps)

1. **Commander** — Search for any legendary creature by name (fuzzy search via Scryfall)
2. **Playstyle** — Choose from 15 preset styles (Aggro, Control, Lifegain, Aristocrats, etc.) or Auto-detect
3. **Face** — Optionally upload 1–5 photos; humanoid card art will feature your likeness
4. **Theme** — Free-text art theme ("dark gothic necromancer city"), bracket level, and art gen toggle
5. **Deck** — Browse all 100 cards with rendered proxy frames, download ZIP or print PDF

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
├── start_app.bat           One-click startup for all three services
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

Renders at **2× resolution (960×1344)** then LANCZOS downscales to **480×672**.

Layer order (bottom to top):
1. Solid black base
2. Background texture PNG
3. Card art (ComfyUI-generated or Scryfall fallback, cropped/scaled)
4. Frame PNG overlay
5. Boxes PNG — top slice = name bar, bottom slice = type bar
6. Legendary crown (if applicable)
7. Text and inline SVG mana pip symbols
8. Power/toughness badge

**Subtitle feature:** If the themed card name differs from the original Scryfall name, the original name is drawn in small italic text at the bottom of the name bar. Useful for identifying proxies.

**SVG symbol rendering:** Uses `pixie-python` (pure Python, no libcairo required on Windows). Each symbol is rasterized to a temp PNG then loaded as a PIL Image.

---

## Themer (`themer.py`)

Runs against **Ollama `qwen2.5:14b`** locally.

1. Generates one deck-wide **style guide** sentence (art medium, palette, lighting, mood)
2. Processes cards in **batches of 8**, each receiving the style guide
3. Each card gets: `themed_name`, `art_prompt` (25–40 words), `flavor_text`
4. Style guide is appended to every `art_prompt` before passing to ComfyUI
5. Ollama is **unloaded from GPU** after theming so ComfyUI can claim the VRAM

**Art prompt rules enforced via system prompt:**
- No specific color names (palette handled by style guide)
- No close-up hands — poses that hide/glove/arm hands
- Landscape composition always
- Each prompt ends with a quality closer phrase
- Mechanic keywords mapped to visual cues (Flying → wings spread, Deathtouch → necrotic aura, etc.)

---

## Image Generation (`image_gen.py`)

Auto-detects checkpoint type (FLUX vs SDXL) and best available face method.

**Checkpoints:** `C:\Users\rvn92\Documents\ComfyUI\models\checkpoints\`

**SDXL settings:** 30 steps, CFG 7.5, DPM++ 2M Karras  
**FLUX dev settings:** 25 steps, CFG 3.5, Euler Simple  
**FLUX schnell:** 4 steps, CFG 1.0

**Positive prompt structure:**
```
[SDXL/FLUX prefix] + [gender qualifier if face card] + [art_prompt] + [style guide]
```

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

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/commander/search` | Fuzzy commander lookup via Scryfall |
| GET | `/api/playstyles` | List all 15 playstyle options |
| GET | `/api/face-method` | Probe which face engine ComfyUI supports |
| POST | `/api/upload-face` | Upload 1–5 face reference photos |
| POST | `/api/deck/build` | Start async deck build → `{job_id}` |
| GET | `/api/deck/{job_id}/events` | SSE stream of build progress |
| GET | `/api/deck/{job_id}/status` | Poll build status |
| GET | `/api/deck/{job_id}` | Full deck payload once complete |
| GET | `/api/deck/{job_id}/card-image/{key}` | Rendered card proxy PNG |
| GET | `/api/deck/{job_id}/set-symbol` | Deck set emblem PNG |
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
  "face_gender": "female"
}
```

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

Python: `C:\Python314\python.exe`

---

## Known Behaviours / Gotchas

- **Server restart required after Python changes** — uvicorn's `reload=True` watches for file changes and restarts automatically, but only if the process is still alive. Kill old processes before relaunching.
- **Ollama ↔ ComfyUI VRAM sharing** — Themer unloads Ollama from GPU after card theming; server also POSTs to `/free` on ComfyUI before theming begins. Both steps are necessary on single-GPU systems.
- **Scryfall rate limiting** — 150ms sleep between requests. Running multiple builds back-to-back is fine for single-user use.
- **Art generation is optional** — Toggle `generate_art: false` to skip ComfyUI entirely; Scryfall card art is used as fallback and frames still render.
- **pixie-python SVG rasterization** — `pixie.Image.resize()` is NOT in-place. Must create a new `pixie.Image(w, h)` as destination, then `ctx.scale() + ctx.draw_image(src, 0, 0)`.
