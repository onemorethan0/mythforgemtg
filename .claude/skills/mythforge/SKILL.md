---
name: mythforge
description: >-
  Understand and operate the Myth Forge MTG Commander deck builder (this repo —
  FastAPI + React + Ollama + ComfyUI for AI-generated card art). Use this whenever
  working in the mtg_deck_builder project: starting or restarting the server,
  testing or debugging FLUX/SDXL image generation, verifying card renders, adding
  or auditing LoRAs and art-style presets, tuning the themer/prompts, or diagnosing
  generation issues (overexposure, low variety, faces, card-text layout) or
  whole-machine crashes. Trigger even when the skill isn't named — e.g. "restart
  mythforge", "why are my cyberpunk cards overexposed", "add a new style lora",
  "the power/toughness box looks wrong", "test one generation", "the card names
  are ignored in the art", "regenerate a card and check it".
---

# Operating Myth Forge

Myth Forge builds themed 100-card EDH decks with AI card art. Stack: **FastAPI**
(`server.py`, port 8000, serves the built React SPA) + **Ollama** (`themer.py`,
:11434) + **ComfyUI** (`image_gen.py` / `model3d.py`, :8188).

**Start by reading [`CLAUDE.md`](../../../CLAUDE.md)** in the repo root — it is the
engineering map (architecture, the critical FLUX-guidance rule, the LoRA system,
GenSettings, gotchas). This skill is the *operational how-to*: the commands and
scripts for running, testing, and verifying changes. The bundled scripts encode
patterns that are otherwise re-derived every session — prefer them.

Run everything from the repo root with the project Python (`C:\Python314\python.exe`,
or just `python` in the configured shell). The scripts here assume that cwd.

## Run / restart the server
Python changes are **not** hot-reloaded — restart to pick them up. Frontend changes
need a rebuild (the server also auto-rebuilds on startup when `frontend/src` is
newer than `frontend/dist`).

```bash
bash .claude/skills/mythforge/scripts/restart_server.sh   # kill :8000, relaunch, healthcheck
cd frontend && npm run build && cd ..                     # after frontend edits
```
Or use the menu: `manage.bat` → 2 (Clean Start) / 9 (Start ComfyUI). Never launch
ComfyUI's Desktop `.exe` directly — it forces `--highvram` and tanks performance
(see `COMFYUI_SETUP.md`).

Watch logs: `tail -f /tmp/mythforge_restart.log`, or the in-app **📜 Logs** button
(`GET /api/logs`). Resolved generation settings print once per build as
`[gen_settings] {...}`.

## Test image generation (the ComfyUI harness)
This is the fastest way to verify an image change without a full 100-card build:
submit one workflow straight to ComfyUI, then measure the result. ComfyUI must be
up (`curl -s http://127.0.0.1:8188/system_stats`).

```bash
# Generate one image through the REAL code path (image_gen builders) and report
# brightness/stddev (the same signal the app uses to detect overexposed/blank output).
python .claude/skills/mythforge/scripts/comfy_gen_test.py \
  --prompt "digital painting, a neon-lit armored knight in a cyberpunk plaza" \
  --loras "kcyberpunk-02.safetensors:0.7,Neon_Cyberpunk_Detailer_FLUX_multi_trigger.safetensors:0.4" \
  --out /tmp/gen.png
```
Read the saved PNG to judge it visually. **Interpretation:** mean brightness > 242
or stddev < 8 ⇒ the app rejects it (overexposed/near-white or blank) and falls back
to Scryfall art. A healthy image is roughly brightness 90–170, stddev 50–80.

**The #1 FLUX rule** (most generation bugs trace to violating it): FLUX-dev is
guidance-distilled — use `KSampler cfg=1.0` + a `FluxGuidance` node (~3.5), never
KSampler cfg > 1 (that over-guides to a blown-out white frame). The builders in
`image_gen.py` already do this; preserve it. The negative prompt is inert on FLUX.

## Verify card renders (text/layout)
For renderer changes (`card_renderer.py`) — title/subtitle, oracle/flavor text,
P/T badge, frames — render a sample card and zoom into the regions that matter
rather than eyeballing the whole 750×1050 card.

```bash
python .claude/skills/mythforge/scripts/render_card_test.py --out /tmp/card.png
# writes /tmp/card.png plus _top (title bar) and _br (flavor + P/T) crops to inspect
```
The renderer draws a 2× canvas then LANCZOS-downscales; layout constants are in mm
via `_mm(...)`. A blank card shows the themed name centered on a dark box — that's
the **no-art placeholder**, not a bug (real cards always have art).

## Inspect / add a LoRA
Before wiring any LoRA into a preset, confirm what it actually is:

```bash
python .claude/skills/mythforge/scripts/inspect_lora.py kcyberpunk        # by fragment
python .claude/skills/mythforge/scripts/inspect_lora.py --all             # everything installed
```
Check: `modelspec.architecture` must be `flux-1-dev/lora` for FLUX; `dim/alpha`
(a dim2/alpha16 LoRA applies ~8× — potent at low strength); whether it trained the
text encoder (has `lora_te*` keys ⇒ `clip_strength` matters, else set it 0).

**Subject vs style — the key lesson:** a *subject* LoRA (e.g. one trained on noir
people) will hijack every commander into the same character regardless of the
prompt. Prefer *style* LoRAs that respect the described subject. The `cyberpunk`
preset rotates two style LoRAs **per card** (`lora_rotation` in `_LORA_PRESETS`):
Cyberpunk CG (`kcyberpunk`) and Neon Abyss (`bo-neon`), each + the Detailer.
LoRAs are matched by filename **fragment** — drop a `.safetensors` in
`ComfyUI/models/loras/` and add an entry. Downloads via the signed-in browser
(Civitai) using the Claude-in-Chrome MCP; verify metadata after.

## Prompt / variety rules (themer.py + image_gen.py)
- **Color = mana identity.** Each card's palette comes from its color identity
  (`_color_palette_hint`). Do NOT bake fixed hues into a preset's `flux_prefix` —
  that flattens every card to one look (the cyberpunk "zero variety" bug). Keep
  prefixes hue-neutral + a luminosity anchor; let per-card `art_prompt` carry color.
- **Names must be depicted.** Only `art_prompt` reaches FLUX (never `themed_name`).
  The themer's #1 rule is to translate the themed name into concrete visual
  elements and keep every card's scene unique (no reused templates).
- Don't force "subject centered" framing — let composition vary.

## Gotchas
- Single-GPU VRAM is shared: themer unloads Ollama after theming; server frees
  ComfyUI before theming. ReActor face-swap runs on CPU here (CUDA 13 vs onnx 12).
- Schnell uses no LoRAs and no FluxGuidance.
- After any backend edit, **restart the server**; after frontend edits, rebuild.

## When unsure
Grep `CLAUDE.md` and the relevant module. The live ComfyUI/Ollama HTTP APIs are the
ground truth for what's installed and running — query them rather than assuming.
