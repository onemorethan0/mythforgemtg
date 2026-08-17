# Internals — how a card actually gets made

Deep reference for the rendering, theming and image-generation pipeline. The
[README](../README.md) is the tour; this is the manual. For engine internals (simulation,
brackets, card semantics) see [`engine/`](engine/) instead.

**Contents**

- [Card assets](#card-assets-card_assets)
- [Card renderer](#card-renderer-card_rendererpy)
- [Optional: official-style M15 frames (Card Conjurer)](#optional-official-style-m15-frames-card-conjurer)
- [Themer](#themer-themerpy)
- [Image generation](#image-generation-image_genpy)
- [Art style presets](#art-style-presets)
- [Face reference system](#face-reference-system-face_refpy)
- [Generation settings (Advanced panels)](#generation-settings-advanced-panels)
- [Animated & foil cards](#animated--foil-cards-card_videopy)
- [3D commander models](#3d-commander-models-model3dpy)
- [Known behaviours / gotchas](#known-behaviours--gotchas)

---

## Card assets (`card_assets/`)

All bundled assets sourced from **wingedsheep/mtg-card-generator**.

```
card_assets/
├── frames/           18 PNGs — W U B R G + 10 two-color pairs + Gold Artifact Colourless
├── bg/               20 PNGs — background textures per color identity
├── boxes/            9 PNGs  — name bar + type bar strips per color
├── pt_boxes/         10 PNGs — power/toughness badge per color
├── legendary_crowns/ 19 PNGs — crown overlay for legendary creatures
├── symbols/          84 SVGs — tap (T), W U B R G, X, 0–20, hybrid pips
└── fonts/
    ├── beleren-bold_P1.01.ttf   Card name font
    ├── mplantin.ttf             Oracle text font
    └── MPlantin-Italic.ttf      Flavor text + subtitle font
```

**Color key logic:** single color → that color's assets. Two colors → sorted WUBRG pair. Three+ →
Gold. Artifact type → Artifact. Land type → Land. No colors → Colourless.

---

## Card renderer (`card_renderer.py`)

Renders at **3× resolution (1440×2016)** for supersampled anti-aliasing, then LANCZOS downscales to
**750×1050** (2.5″×3.5″ @ 300 DPI — print-ready, no upscaling needed).

Layer order (bottom to top):

1. Solid black base
2. Background texture PNG
3. Card art (ComfyUI-generated or Scryfall fallback, cropped/scaled)
4. Frame PNG overlay
5. **Border theme tint** — optional thematic colour overlay on the frame chrome
6. Boxes PNG — top slice = name bar, bottom slice = type bar
7. Legendary crown (if applicable)
8. Text and inline SVG mana pip symbols
9. Power/toughness (or loyalty) badge

**Border theme.** Each deck can specify a free-text border theme (e.g. `"fire and ash"`,
`"arcane runes"`, `"frost crystals"`). The renderer classifies the description into one of 7 colour
palettes (flame, frost, arcane, circuit, wave, shadow, vine) and alpha-composites a tinted fill over
the full chrome band on all four sides, plus corner ornaments. Intensity survives the 3×→1× LANCZOS
downscale because the fill covers the entire chrome width (~22 px at output).

**Nickname subtitle (proxy identification).** If the themed card name differs from the original
Scryfall name, the original name is drawn as a small italic subtitle under the title — on every
frame style — so it's always obvious which real card a renamed proxy represents ("Meadow of Many
Treats" reads *Terramorphic Expanse* at a glance).

**Borderless / showcase treatment (M15 full-art).** Legendary cards get the **floating legend
crown** over the title plate; title, type line and P/T render in **white with a dark outline** — the
same convention Wizards uses for borderless frames — so they stay legible over full-bleed art.

**Authentic symbol geometry (measured, not eyeballed).** Mana pip size and margins are matched to
real M15 card scans — pips are ~3.2 % of card height with a **hard drop shadow** under each cost pip
(real cards have one; without it the discs look pasted on), near-touching spacing, and the set symbol
is alpha-trimmed and right-anchored at the true type-line margin so it fills the band like a real
rarity symbol. **P/T digits** are sized the same way (~4 % of card height, like a real badge) on
every frame style, shrinking only when a long value ("10/10", "13/13", "\*/\*") needs the room.

**Oracle text typography.** Parenthetical **reminder text is italicized inline** (even mid-line,
e.g. *Dethrone (Whenever …)*), and flavor text is always drawn at the **same final font size as the
rules text**, so a single card never mixes sizes.

**Set symbol rarity metals.** Every deck gets a unique theme-derived emblem (deterministic from the
theme / emblem prompt), tinted per card by rarity like real MTG — black common, silver uncommon,
gold rare, orange-bronze mythic, purple special/timeshifted.

**Text legibility (white vs black).** The name bar, type bar and P/T badge each choose light or dark
text by **sampling the actual composited pixels under the text** (after frame + boxes + crown +
border tint) and picking whichever gives the higher WCAG contrast, with a subtle opposite-colour halo
(`_legible_text_color` / `_draw_legible_text`). This replaced a static per-colour map that could put
light text on a light box (invisible names). On M15 frames the rules/flavor text is sampled the same
way (light over the art panel, dark on parchment); the borderless white-text convention above
overrides the picker where Wizards always uses white.

**Custom mana pips (`mana_pips.py`).** Optional per-deck override of the stock W/U/B/R/G/C symbols —
a mana-coloured gem disc (subtle sheen + drop shadow) carrying a **black silhouette of the deck's
emblem** (FLUX-drawn when ComfyUI is up, vector fallback otherwise). The fae-dogs deck in the
[gallery](GALLERY.md) uses paw-print pips. Toggled per deck on the Theme step; used everywhere a mana
symbol is drawn (cost row + inline rules text).

**SVG symbol rendering.** Uses `pixie-python` (pure Python, no libcairo required on Windows). Each
symbol is rasterized to a temp PNG then loaded as a PIL Image.

---

## Optional: official-style M15 frames (Card Conjurer)

`cc_frames.py` can render cards using the modern **M15 frame** set from a locally-installed
[Card Conjurer](https://github.com/Investigamer/cardconjurer), for a more "official" look than the
bundled frames.

**This is opt-in and ships no frame artwork.** The module is clean-room code; the frame PNGs are
© Wizards of the Coast / their authors. You supply them yourself — exactly like LoRAs/checkpoints:

1. Install Card Conjurer locally **outside this repo** — clone a fork (e.g.
   `git clone https://github.com/Investigamer/cardconjurer.git`). You only need the `img/frames/…`
   assets; a sparse checkout of `img/frames/m15` is enough for the M15 styles.
2. **Point Myth Forge at that folder.** Two ways (the env var wins if both are set):
   - **Easiest — in the app:** on the **Theme step**, the **Card Frame Style** selector shows a
     🗂 *Card Conjurer folder* field whenever M15 is locked. Paste the folder path (the one
     containing `img/frames`) and click **Save** — the M15 / Full-art options unlock immediately.
     Saved to a gitignored `cc_config.json`.
   - **Or an environment variable** (persistent / power users): set `MYTHFORGE_CC_DIR` to that
     folder before starting the server.
     ```cmd
     setx MYTHFORGE_CC_DIR "C:\path\to\cardconjurer"
     ```
3. Pick **Official-style (M15)** or **Full-art (Borderless)** per deck. If assets are missing it
   silently falls back to the bundled frames. The choice is saved with the deck, so
   Rebuild/Retheme/Regen reuse it.

`GET /api/frame-styles` reports which systems are available; `GET/POST /api/frame-config` reads/sets
the folder (drives the in-app field).

**Three M15 styles are supported**, selectable in the Theme step when the assets are detected:

- **Official-style (M15)** — the standard modern frame with the usual art window.
- **Extended-art (M15)** — art runs full-width to the left/right edges (taller than regular) with a
  normal text box. A middle ground between regular and full-art.
- **Full-art (Borderless)** — edge-to-edge full-bleed art with a translucent title plate + text box
  (the borderless/showcase look). Great for AI-generated art that deserves the whole card.

All cover mono / gold / artifact / land + P/T; text, mana symbols and white-vs-black legibility reuse
the built-in renderer. The frame layout is data-driven (`_SPECS` in `cc_frames.py`), so adding more
packs is one spec each.

> ⚠️ **Do not commit Card Conjurer assets to a public repo.** They're copyrighted and were the
> subject of a Wizards of the Coast cease-and-desist. `.gitignore` guards against accidental
> commits, but keep your CC install outside the project folder.

---

## Themer (`themer.py`)

Runs against a **local LLM** — by default an OpenAI-compatible **llama.cpp** server behind a
[llama-swap](https://github.com/mostlygeek/llama-swap) gateway (`127.0.0.1:8010`, model `qwen3:14b`,
auto-load/auto-unload of GGUFs); set `MYTHFORGE_LLM_BACKEND=ollama` for native **Ollama** instead.
Auto-falls back through `qwen3:32b` → `qwen2.5-coder:14b` → `gemma4` if the primary model is missing.

0. **Creative brief / world bible** (`build_creative_brief`) — turns the Theme step's *structured*
   inputs (Setting + Genre/Mood/Lighting + Inspirations) into a shared world bible: `must_include`
   (your concrete motifs, preserved verbatim — the faithfulness anchor), `signature_details`
   (invented "colouring", amount set by the **creativity dial**), palette, and 4 visual zones.
   Threaded into the style guide and every per-card prompt; `verify_motif_coverage` then checks each
   promised motif actually appears in the deck art. The **🔮 Preview creative direction** panel
   (`POST /api/deck/theme-preview`) shows the bible + a 3-card sample before you build. Old/imported
   decks (no structured spec) fall back to the simpler `_expand_theme` flow.
1. Generates one deck-wide **style guide** sentence (used only as LLM context, NOT prepended to FLUX
   prompts; when a brief exists it must name your `must_include` motifs).
2. Processes cards in **batches**, each receiving the style guide + world bible as context.
3. Each card gets: `themed_name`, `art_prompt` (35–50 words), `flavor_text`.
4. **Name → art coherence (#1 rule):** the `art_prompt` must *depict* the themed name's imagery (2–3
   concrete visual elements), and every card's scene must be unique (no reused templates).
5. **Evoke the original card:** `themed_name` fuses the original card's identity/iconic imagery with
   its function (mechanics + role), so the source card is recognizable reskinned into the theme
   (Lightning Bolt → "Neon Surge", Doom Blade → "Necrotic Lance") — not a generic mechanics label.
6. **Name variety:** the prompt forbids the monotonous "The [Adjective] [Noun]" default and pushes
   mixed forms (coinages, possessives, verb-led, place names). A deterministic guard strips the
   commander's name *and rhymes/respellings of it* (Krenko → "Kretno") from other cards; duplicate
   names are disambiguated — comma "Name, Title" epithets for legendary creatures/planeswalkers only,
   no-comma adjectives for lands/spells (so a land never reads "Place, Title").
7. **Color = mana identity:** each card's palette is driven by its color identity
   (`_color_palette_hint`: W = ivory/gold, U = arcane blue, B = shadow/necrotic, R = fire/crimson,
   G = verdant, colorless = chrome), deferring to user-theme colors for characters — mirroring real
   MTG. Colorless cards inherit colours named in your theme rather than defaulting to grey.
8. The LLM is **unloaded from GPU** after theming (llama-swap `/api/models/unload`, or Ollama
   eviction) so ComfyUI can claim the VRAM.

**Tribe reskin (auto-theme-all, single auto-tribe, or multi-tribe user choice).** With **✨ Auto-theme
creature types** on (the default), *every* creature type in the deck is reskinned — one theme-fitting
replacement per type, generated once and applied uniformly so a given type is the **same kind on
every card** (a Dragon never drifts into a cat). On **Ragnarok Online** art styles this is
*deterministic*: types map to RO jobs/monsters/races via the same tables that drive the LoRA tokens
(*Knight → Lord Knight*, *Cat → Brute*, *Elf → Demihuman*), keeping the printed type in lock-step
with the art. With the toggle off, only the commander's most distinctive subtype (skipping the
generic "Human" race) is auto-reskinned. Either way, the user can override any individual type in the
Theme step (`tribal_overrides`, which win per-type). Each mapped type is reskinned **consistently in
the themed name, the art, the displayed type line, AND the rules text** — e.g. *Knight → Cowboy* turns
"equip Knight {0}" into "equip Cowboy {0}" and "Knights you control" into "Cowboys" (plural-aware,
whole-word). A card with two mapped subtypes ("Human Knight") collapses to a **single** reskin using
the trailing job/class token (→ "Lord Knight", not "Demihuman Lord Knight"). Unmapped creatures keep
their own kind.

**Named & depicted as the right *kind of thing*.** Each card carries a per-type subject directive so
it isn't defaulted to a character. **Non-creature artifacts** (mana rocks, relics, Equipment,
Vehicles) get **object/relic/construct** names and art (like real MTG: *Sol Ring*, *Skullclamp*,
*Mana Vault*) — never a personal or creature name; **lands** are named/painted as places;
**enchantments** as auras/phenomena. Only **artifact *creatures*** (type line says *Creature*) get a
creature/being name.

**Prompt pipeline (dual-anchor).** Each card is pre-classified by its mechanical role (`_card_soul()`),
producing a `soul_phrase` (e.g. *"divine judgment, everything obliterated simultaneously"* for a
boardwipe). `_batch_prompt_v2` gives the LLM both the soul (what the card *does*) and the theme skin
(world aesthetic), so prompts stay true to the MTG mechanic and the setting at once.

**Art prompt rules enforced via system prompt:**

- Color palette driven by the card's mana identity (see above), not a fixed deck palette
- Themed name depicted as concrete visual elements; scenes unique per card
- No close-up hands — poses that hide/glove/arm hands
- Landscape composition (framing free to vary — no forced centering)
- Each prompt ends with a quality closer phrase
- Mechanic keywords mapped to visual cues (Flying → wings spread, Deathtouch → necrotic aura, etc.)

---

## Image generation (`image_gen.py`)

Auto-detects checkpoint type and the best available face method.

| Mode (`model_speed`) | Model | Notes |
|---|---|---|
| `quality` | FLUX.1-dev | 28 steps, KSampler **CFG 1.0** + FluxGuidance 3.5, dpmpp_2m + sgm_uniform |
| `turbo` | FLUX.1-dev + distillation LoRA | 8 steps, ~10 s/card vs ~30 s, near-dev quality. The "⚡ Turbo" button appears only when a turbo LoRA is installed |
| `fast` | FLUX.1-schnell | 8 steps, CFG 1.0, euler + simple. No FluxGuidance, **no LoRAs** |
| `krea` | FLUX.1-Krea-dev | flux-dev architecture, so **all FLUX LoRAs and presets apply unchanged**. Ships as a split UNET + CLIP + VAE |
| `sd35` | SD 3.5 Large | ModelSamplingSD3, 30 steps, CFG 4.5 |
| `qwen` | Qwen-Image | Separate MMDiT with **true CFG** (~2.5), so negative prompts actually work. **No FLUX/SDXL LoRAs**, prompt-only; faces via ReActor post-swap only |

**SDXL / Illustrious:** 30 steps, CFG 7.5, DPM++ 2M Karras. Required by the Ragnarok Online styles.

> **Why CFG 1.0 + FluxGuidance, not CFG 3.5 in the KSampler?** FLUX-dev is guidance-distilled;
> driving it with true CFG > 1 over-guides the latent to a blown-out near-white frame. Correct usage
> is KSampler CFG 1.0 with a FluxGuidance conditioning node (~3.5). The negative prompt is therefore
> inert on FLUX (it steers from the positive). Guidance/steps are user-tunable via the Theme step's
> Advanced panel.

**Positive prompt structure:**

```
[LoRA trigger words] + [style flux_prefix] + [art_prompt] + [face suffix if face card]
```

The deck-wide style guide is **not** prepended to FLUX prompts (the `flux_prefix` owns the art style;
prepending the style guide caused medium conflicts). Per-card **color comes from the card's mana
identity** (see Themer), not a fixed deck palette. Card art renders at 1152×768 (safe mode: 896×600).

**Bad-image detector.** Mean brightness > 242 or stddev < 8 → discard and retry once with a new seed,
else fall back to Scryfall art.

### Art style presets

Each preset is a curated LoRA stack with its own prompt prefix, negative prompt and themer hints.
LoRAs are auto-detected by filename fragment — drop the `.safetensors` file in
`ComfyUI/models/loras/` and it activates automatically. Presets with several *flavors*
(cyberpunk, desert punk) rotate stacks per card for variety, or you can pin one deck-wide.
Custom presets can be added from the UI (`POST /api/art-styles/custom`).

| Key | Label | Icon | LoRA file(s) |
|-----|-------|------|--------------|
| `mtg_fantasy` | MTG Fantasy | ⚔️ | `df_style_v1.1.safetensors`, `aidmaMTGCard-FLUX-V0.1.safetensors` |
| `photorealism` | Photorealism | 📷 | `xlabs_realism_lora.safetensors` |
| `cyberpunk` | Cyberpunk | 🌆 | `kcyberpunk-02` + `Neon_Cyberpunk_Detailer` (5-flavor rotation) |
| `desert_punk` | Desert Punk | 🏜️ | `retrofuture_*.safetensors` (3-flavor rotation) |
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
| `ragnarok_online` | Ragnarok Online | ⚔️ | `ro_lora_v5.safetensors` — **requires Illustrious XL (SDXL)** |
| `ragnarok_sprite` | Ragnarok Sprite (Pixel) | 👾 | `ro_pixel_sprite_lora.safetensors` — **requires Illustrious XL** |

> **Ragnarok Online styles** run on **Illustrious XL** (an SDXL/Danbooru-tag anime model), not FLUX.
> The themer auto-injects the exact Danbooru tags the LoRA was trained on — element from mana colour
> (holy/water/shadow/fire/earth), race from creature subtype, and the job class
> (`lord_knight_(ragnarok_online)`, `high_wizard_…`, `arch_bishop_…`), emphasis-weighted so the class
> reliably renders. Name a class in the **commander appearance** (or the Theme step's Job Class
> picker) to override the auto-detected class (e.g. make a Knight commander a *Monk*).

**Anime style guide:**

- 🎌 **Anime / Manga** — flat colour, cel-shaded, clean linework. Classic 2D TV animation look.
- ✨ **Anime Illustrated** — semi-realistic anime; highly detailed facial features, realistic lighting,
  rich depth. ([civitai.com/models/754435](https://civitai.com/models/754435))
- 🌸 **Anime Artbook** — soft painterly rendering, artbook/key-visual quality.
  ([huggingface.co/alvdansen/softserve_anime](https://huggingface.co/alvdansen/softserve_anime))

---

## Face reference system (`face_ref.py`)

**Upload path:** `face_uploads/{face_key}/face_00.jpg` etc.

**Which cards get face treatment:**

- Commander: **always** (in a Commander deck)
- Non-commander cards: only if the type line contains a humanoid subtype AND fewer than **4**
  non-commander face cards have been used
- Humanoid subtypes: Human, Warrior, Wizard, Shaman, Cleric, Knight, Rogue, Monk, Druid, Ranger,
  Paladin, Assassin, Pirate, Noble, Artificer, Scout, Mercenary, Rebel, Samurai, Ninja, Archer,
  Spellcaster, Hero, Champion, Lord, Queen, King, Prince, Princess, God, Demigod, Avatar, Bard,
  Warlock, Sorcerer, Alchemist, Investigator, Renegade, Duelist

**Excluded even if Legendary:** Dragons, Krakens, Beasts, Elementals and other non-humanoid creature
types never receive face treatment.

**Gender matching.** The face step includes a Female / Male / Either toggle. The selected gender is
injected as a prompt qualifier (`"male character, "` / `"female character, "`) **only** for cards
receiving face conditioning. All other cards render with whatever gender the themer's art prompt
naturally describes.

**Face conditioning methods** (auto-detected, best available wins):

| Method | Requirement | Quality |
|--------|------------|---------|
| PuLID FLUX | ComfyUI_PuLID_Flux node + pulid model | Best |
| IP-Adapter FaceID | ComfyUI-IPAdapter-plus (SDXL only) | Great |
| ReActor face swap | ComfyUI-ReActor node | Good |
| None | — | Text-only hint |

**ReActor is style-aware.** A photoreal restored face stamped at full strength onto hand-painted art
looks pasted on, so the swap is tuned by rendering medium: **photoreal** presets get a crisp restore
(`GPEN-BFR-512` @ 0.85 visibility with a sharpening FaceBoost); **illustrated** presets get a soft
swap that melts into the painting (`codeformer` @ 0.55); **pixel** (`ragnarok_sprite`) **disables the
swap entirely** — insightface can't find a face in pixel art and a photo face looks wrong there.
When several photos exist for one identity they are averaged into a single face model
(`ReActorBuildFaceModel`, Mean) so the likeness tolerates angle and lighting changes.

**Non-Commander decks: "Cast your deck".** Import a 60-card list and the Face step swaps its
commander/crew columns for an assignment grid — upload people, assign each to specific cards. In
assignment mode the mapping is authoritative: an assigned card gets that exact person *bypassing* the
humanoid check (so a Land can carry a face), and unassigned cards get none.

**Per-card force-face.** In a per-card regen you can drop one uploaded face onto every selected
card, overriding commander/crew routing and the humanoid check.

---

## Generation settings (Advanced panels)

The Theme and Face steps each have a collapsible **⚙ Advanced** panel, driven by a single schema
(`frontend/src/config/genSettings.js`) with a structural **Reset to defaults** button and
`localStorage` persistence. Values flow `gen_settings → BuildRequest → ImageGen → workflow builders`:

- **Theme:** FLUX guidance (1.5–5), sampler steps, seed (random/fixed), a **LoRA picker** (override
  the preset stack + per-LoRA strength), a **style flavor** pin, and **Safe mode**.
- **Image Quality** (prominent toggles on the Theme step, shown when art-gen is on):
  - **✨ Enhanced coherence (PAG)** — Perturbed-Attention Guidance; improves anatomy/faces/structure
    (fewer malformed or abstract subjects). ~2× slower.
  - **😊 Face fix (FaceDetailer)** — detects faces and re-renders them at higher detail (Impact Pack;
    SDXL/Illustrious). Fixes small/blurry/malformed faces.
- **Face:** face method (auto/ReActor/PuLID/none) and PuLID identity strength.
- **Safe mode** lowers steps + resolution to reduce peak GPU/CPU load (mitigates crashes on unstable
  hardware).
- The fully-resolved settings are logged once per build as `[gen_settings] {...}`, persisted into
  `deck.json`, and reused by rebuild / regen / retheme so a pinned flavor survives a re-run.

---

## Animated & foil cards (`card_video.py`)

Turn finished cards into **looping clips**. From the gallery, select one or more cards → **✨ Animate**
→ pick an effect. Two independent axes, combinable:

**1. Art motion** — a local ComfyUI **image-to-video** model animates only the **art**, and each frame
is re-composited through the normal renderer so the **frame, text, mana symbols and P/T stay
perfectly crisp**. Supply your own model (like LoRAs / Hunyuan3D — none is bundled): **LTX-Video**
(lighter/faster, recommended starting point on a 24 GB card) or **Wan 2.x** I2V (heavier, higher
motion quality). Both ship as ComfyUI-core nodes; you provide the weights under `ComfyUI/models/`.
`GET /api/video-health` reports readiness and disables the motion options if nothing usable is present.

**2. Foil / holo sheen** — a **procedural, deterministic, CPU-only** holographic sweep over the whole
composited card (frame + text + art). **No model required**, so this works on any machine. Styles:
`holo`, `gold`, `silver`, with an intensity slider.

**Controls.** 14 motion presets grouped ambient / atmosphere / camera / energy (camera moves are I2V's
most reliable; every preset pins the subject — "subject stays still" — because I2V models warp figures
on structural motion), plus **✍️ Custom motion…** free text. Motion strength maps to LTX-Video's
conditioning frame rate, decoupled from playback fps. Clip length 1–6 s for motion (snapped to the
model's frame multiple) / 1–10 s for foil, selectable fps.

**Loop style.** I2V clips aren't periodic, so the loop is built explicitly: `crossfade` (**default** —
dissolves the tail back into the head, seamless *and* forward-only), `bounce` (ping-pong: seamless but
the motion visibly runs backward), or `off`. Foil sweeps are inherently periodic and need none.

**Output formats:** `mp4` (H.264), `webp` (animated, alpha kept, smallest at high quality), or `gif`
(256-colour, portable). Animated tiles autoplay-loop in the gallery (the static PNG stays the
print/poster), download individually, and export together as a **🎬 Videos ZIP**. A
**▶ Motion: On/Off** toggle flips every tile back to the still without re-encoding. Print PDF/ZIP are
unchanged.

**Override the workflow:** the default ComfyUI graphs are best-effort for stock core nodes; if your
version differs, point `MYTHFORGE_VIDEO_WORKFLOW_LTXV` / `_WAN` at your own API-format JSON
(placeholders documented in `card_video._PLACEHOLDERS`) or drop it at
`card_assets/video_workflows/<method>.json`.

---

## 3D commander models (`model3d.py`)

Optional pipeline: commander art → **rembg** background removal → **Hunyuan3D v2** (ComfyUI) → GLB →
**STL** (trimesh), scaled to ~60 mm for printing. Octree resolution defaults to 384
(`MYTHFORGE_3D_RES` to override). Exposed via `POST /api/deck/{job_id}/generate-3d` (SSE progress) and
`GET /api/3d-health`.

---

## Known behaviours / gotchas

- **Server restart required after Python changes** — uvicorn's `reload=True` watches for file changes
  and restarts automatically, but only if the process is still alive. Kill old processes before
  relaunching.
- **After editing the frontend, rebuild it** — `cd frontend && npm run build`. FastAPI serves
  `frontend/dist`, not the dev sources.
- **LLM ↔ ComfyUI VRAM sharing** — the themer unloads the model from the GPU after card theming
  (llama-swap unload, or Ollama eviction); the server also POSTs to `/free` on ComfyUI before theming
  begins. Both steps are necessary on single-GPU systems.
- **`--disable-async-offload` is mandatory for ComfyUI** on affected builds — without it
  `CLIPTextEncode` crashes on every card with `'VRAMBuffer' object has no attribute 'get'`, which
  presents as "theming worked but no art" (silent Scryfall fallback). Myth Forge adds the flag when it
  launches ComfyUI and auto-repairs a ComfyUI started without it before a build.
- **Scryfall rate limiting** — 150 ms sleep between requests. Running multiple builds back-to-back is
  fine for single-user use.
- **Art generation is optional** — toggle it off to skip ComfyUI entirely; Scryfall card art is used
  and frames still render.
- **pixie-python SVG rasterization** — `pixie.Image.resize()` is NOT in-place. Create a new
  `pixie.Image(w, h)` as destination, then `ctx.scale() + ctx.draw_image(src, 0, 0)`.
- **trimesh 4.x** removed `remove_degenerate_faces()` — use
  `mesh.update_faces(mesh.nondegenerate_faces())`.
