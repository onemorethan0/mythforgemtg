"""
Card art generation via ComfyUI.

Supports both SDXL and FLUX.1 checkpoints — auto-detects which is loaded.
ComfyUI must be running on port 8188 with at least one checkpoint installed.

Models dir:  C:\\Users\\rvn92\\Documents\\ComfyUI\\models\\checkpoints\\

Face-conditioning (optional):
  Detects which face nodes are installed and uses the best available method:
    • pulid_flux       — PuLID for FLUX (install ComfyUI_PuLID_Flux + pulid model)
    • ipadapter_faceid — IP-Adapter FaceID for SDXL (install ComfyUI-IPAdapter-plus)
    • reactor          — ReActor face-swap post-process (install ComfyUI-ReActor)
    • none             — no face nodes; injects textual face hint into prompt

MTG art LoRAs (optional — place .safetensors in ComfyUI/models/loras/):
  Any installed LoRAs whose filename matches an entry in _LORA_CATALOG are
  automatically stacked onto the base FLUX model at startup.  Zero config needed.

  Target directory: C:\\Users\\rvn92\\Documents\\ComfyUI\\models\\loras\\

  Downloads:
    1. df_style_v1.1.safetensors          (~168 MB, strength 0.8, trigger: df_style)
       https://civitai.com/models/669671?modelVersionId=754886
       Trained on MTG / D&D card art — closest match to actual card illustration style.

    2. aidmaMTGCard-FLUX-V0.1.safetensors (~19 MB,  strength 0.7, trigger: aidmamtgcard)
       https://civitai.com/models/567735?modelVersionId=797974
       Trained on MTG card compositions — enforces card-art framing and color palette.

    3. PainterlyFantasiaFlux.safetensors  (~18 MB,  strength 0.25, trigger: Digital painting style…)
       https://civitai.com/models/1145521?modelVersionId=1288358
       Brushstroke + impasto texture — fights FLUX's photorealism tendency.
       Kept LOW (0.25) — full strength causes soft/blurry output.

    4. shakker_dark_fantasy.safetensors   (~38 MB,  strength 0.65, no trigger needed)
       ALREADY DOWNLOADED — Shakker-Labs dark fantasy atmospheric lighting.

  Combined model strength sum ≈ 2.75 — within safe range for FLUX multi-LoRA stacking.

Sampler notes (community-tested FLUX dev, 2025):
  euler + beta   — NOT recommended together (beta only shines paired with deis).
  dpm++_2m + sgm_uniform — sharpest detail, best for illustration/concept art.
  deis + beta    — high contrast cinematic look, also excellent for MTG scenes.
  Current default: dpm++_2m + sgm_uniform, 35 steps, CFG 7.0, 1152x768.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Optional

import requests

_COMFY_PORT_CANDIDATES = [8188, 8000, 8001, 8002]   # ports to probe in order
OUTPUT_TIMEOUT         = 600        # seconds to wait for one image
POLL_INTERVAL          = 2.0


def _detect_comfy_base() -> str:
    """
    Find the port ComfyUI is actually running on.

    ComfyUI Desktop starts with --port 8000 but auto-increments when the
    port is occupied.  Older / manual installs default to 8188.  We try
    each candidate port in order, verify the response looks like ComfyUI's
    /system_stats JSON (contains "system" or "devices" keys), then return
    that base URL.  Falls back to 8188 so callers get a clear error message.
    """
    for port in _COMFY_PORT_CANDIDATES:
        url = f"http://127.0.0.1:{port}"
        try:
            r = requests.get(f"{url}/system_stats", timeout=2)
            if r.status_code == 200:
                try:
                    data = r.json()
                    # ComfyUI system_stats always has "system" or "devices"
                    if "system" in data or "devices" in data:
                        return url
                except Exception:
                    pass   # port responded but not ComfyUI (e.g. our own server)
        except requests.RequestException:
            pass
    # Nothing found — default to 8188 so health_check produces a useful message
    return "http://127.0.0.1:8188"


# Resolved once at module load; re-probed in ImageGen.__init__ so a fresh
# ComfyUI restart between builds is handled automatically.
COMFY_BASE = _detect_comfy_base()

# Landscape dimensions that match the card art box aspect ratio (~1.5:1).
# 1152x768 is 2.25x more pixels than the old 768x512 and sits well within
# FLUX's trained resolution range — eliminates the blurry/low-detail look
# that comes from asking FLUX to fill a sub-1M-pixel canvas.
CARD_WIDTH     = 1152
CARD_HEIGHT    = 768

# ── Negative prompt (SDXL only — FLUX ignores negatives at low CFG) ───────────
NEGATIVE_PROMPT = (
    # Anatomy errors — most common SD failure mode
    "bad hands, extra fingers, missing fingers, fused fingers, too many fingers, "
    "four fingers, three fingers, six fingers, wrong number of fingers, incorrect finger count, "
    "mutated hands, poorly drawn hands, deformed hands, malformed hands, "
    "bad anatomy, extra limbs, missing limbs, missing arms, missing legs, "
    "extra arms, extra legs, extra body parts, disconnected limbs, "
    "malformed limbs, mutated limbs, gross proportions, "
    "long neck, elongated neck, short neck, elongated body, twisted body, "
    # Face
    "bad face, ugly face, deformed face, poorly drawn face, asymmetrical face, "
    "crossed eyes, lazy eye, double chin, "
    "cropped face, face cut off, head cut off, partial face, "
    # Quality
    "ugly, worst quality, low quality, normal quality, "
    "blurry, out of focus, soft focus, "
    "jpeg artifacts, compression artifacts, pixelated, noisy, grainy, "
    "overexposed, underexposed, washed out, flat lighting, "
    "low resolution, draft, unfinished, amateur, "
    # Composition
    "out of frame, cropped, cut off, "
    "portrait orientation, vertical composition, tilted, skewed, "
    # Text / watermarks
    "watermark, signature, text, username, artist name, logo, stamp, "
    # Card-frame artifacts
    "border, frame, card template, card border, card frame, "
    # Style / duplication artifacts
    "duplicate, clone, multiple copies, tiling, collage, "
    "3d render, cgi, plastic, doll, mannequin, toy, figurine, "
    "cartoon, anime, sketch, pencil drawing, "
    # NSFW
    "nsfw, nude, explicit"
)

# Lighter negative for FLUX — it has poor negative adherence at low CFG
# but these quality + style terms still steer it away from photorealism and blur
_FLUX_NEGATIVE = (
    "bad hands, extra fingers, four fingers, three fingers, wrong number of fingers, "
    "bad anatomy, deformed, ugly, "
    "photograph, photo, photorealistic, hyperrealistic, camera, DSLR, "
    "blurry, out of focus, soft focus, hazy, foggy, low resolution, "
    "overexposed, washed out, white background, blown out, pure white, "
    "watermark, text, border, card frame, out of frame, cropped, nsfw"
)

# ── Positive prompt prefixes ───────────────────────────────────────────────────
# SDXL responds well to comma-separated quality tags at high CFG
_SDXL_PREFIX = (
    "masterpiece, best quality, highly detailed, sharp focus, "
    "professional fantasy illustration, artstation trending, concept art, "
    "cinematic lighting, dramatic shadows, rich color palette, "
    "landscape composition, wide shot, subject fully in frame, no cropping, "
    "anatomically correct hands, five fingers on each hand, "
)

# FLUX needs strong explicit style anchors to avoid defaulting to photorealism.
# Lead with the medium ("digital painting") before any subject description so
# the style token is weighted highest by CLIP attention.
_FLUX_PREFIX = (
    "Digital painting, fantasy illustration, concept art. "
    "Crisp linework, sharp focus, highly detailed, intricate textures. "
    "Vivid saturated colors, cinematic lighting, dramatic shadows. "
    "Wide landscape composition, subject fully centered and in frame. "
    "Any visible hands have exactly five fingers each. "
)

# ── Face-method node requirements ─────────────────────────────────────────────
_FACE_METHODS: dict[str, list[str]] = {
    "pulid_flux":       ["PulidModelLoader", "ApplyPulidFlux"],
    "ipadapter_faceid": ["IPAdapterFaceID",  "IPAdapterUnifiedLoader"],
    "reactor":          ["ReActorFaceSwap"],
}


# ── LoRA preset system ────────────────────────────────────────────────────────
#
# Each preset is a curated LoRA stack for a specific visual aesthetic.
# Presets are chosen by the user in the UI and passed as `art_style` to ImageGen.
#
# Fragment matching: any installed LoRA whose lowercase filename contains ANY of
# the `fragments` strings is considered a match (first hit wins).
#
# `dark_only` entries have their strengths scaled by _theme_darkness_score() so
# light/whimsical themes don't get crushed into grim dark-fantasy territory.
#
# `flux_prefix`: None → use module-level _FLUX_PREFIX; otherwise overrides it.
#
# Download instructions are surfaced via GET /api/art-styles and the UI.

_LORA_PRESETS: dict[str, dict] = {

    # ── Classic MTG card illustration ─────────────────────────────────────────
    "mtg_fantasy": {
        "label":       "MTG Fantasy",
        "description": "Classic Magic card art — painterly illustration, dramatic lighting, high fantasy.",
        "icon":        "⚔️",
        "flux_prefix": None,   # None → use default module-level _FLUX_PREFIX
        "style_guide_hint":  "painterly fantasy illustration, dramatic lighting, classic Magic: The Gathering art style",
        "themer_medium":     '"digital painting," or "fantasy illustration," or "concept art,"',
        "themer_quality":    '"painterly brushwork, vivid colors" or "dramatic lighting, intricate detail" or "painterly, rich texture"',
        "loras": [
            {
                "fragments":      ["df_style"],
                "trigger":        "df_style",
                "model_strength": 0.80,
                "clip_strength":  0.80,
                "dark_only":      True,
                "label":          "Dark Fantasy Art",
                "download_url":   "https://civitai.com/models/669671",
                "download_note":  "Save as df_style_v1.1.safetensors",
            },
            {
                "fragments":      ["aidmamtgcard"],
                "trigger":        "aidmamtgcard",
                "model_strength": 0.55,    # reduced from 0.70 — composition LoRA at full strength causes muddy/over-constrained output
                "clip_strength":  0.55,
                "dark_only":      False,   # kept False but low strength; can accumulate with other LoRAs
                "label":          "MTG Compositions",
                "download_url":   "https://civitai.com/models/567735",
                "download_note":  "aidmaMTGCard-FLUX-V0.1.safetensors",
            },
            {
                "fragments":      ["painterly"],
                "trigger":        "Digital painting style, brushstrokes",
                "model_strength": 0.25,
                "clip_strength":  0.25,
                "dark_only":      False,
                "label":          "Painterly Texture",
                "download_url":   "https://civitai.com/models/1145521",
                "download_note":  "PainterlyFantasiaFlux.safetensors",
            },
            {
                "fragments":      ["shakker"],
                "trigger":        "",
                "model_strength": 0.65,
                "clip_strength":  0.65,
                "dark_only":      True,
                "label":          "Dark Atmosphere",
                "download_url":   None,
                "download_note":  "shakker_dark_fantasy.safetensors (auto-downloaded via HuggingFace)",
            },
        ],
    },

    # ── Cinematic photorealism ─────────────────────────────────────────────────
    "photorealism": {
        "label":       "Photorealism",
        "description": "Cinematic photography — sharp portraits, realistic textures, natural lighting.",
        "icon":        "📷",
        "style_guide_hint":  "cinematic photorealistic photography, sharp focus, natural volumetric lighting, film-quality",
        "themer_medium":     '"photorealistic digital art," or "cinematic photograph," or "hyperrealistic illustration,"',
        "themer_quality":    '"sharp focus, photorealistic detail" or "cinematic depth of field, volumetric light" or "high definition, lifelike texture"',
        # flux_prefix: lead with BRIGHT natural light sources so FLUX doesn't
        # default to underexposed dark output.  "cinematic photography" alone at
        # low CFG can produce near-black frames — anchor on warm volumetric light
        # first, then the style and quality terms.
        "flux_prefix": (
            "Photorealistic cinematic photography. "
            "Well-lit scene with natural volumetric light — warm golden hour, "
            "bright overcast, or crisp studio key light flooding the subject. "
            "Sharp focus, shallow depth of field, vivid colors, high dynamic range. "
            "Film-quality composition, subject fully in frame, wide shot. "
            "Any visible hands have exactly five fingers each. "
        ),
        # face_prefix_medium: overrides the "Painted portrait" default used in
        # generate() for face-conditioned cards.  Must NOT specify "Painted" here —
        # that word directly contradicts the photorealistic style and causes FLUX
        # to produce spiral/contradiction artifacts.
        "face_prefix_medium": "Photorealistic close-up portrait",
        "face_prefix_quality": "sharp photorealistic skin detail, natural lighting on face",
        # Custom negative for photorealism: the default _FLUX_NEGATIVE explicitly
        # lists "photograph, photo, photorealistic, hyperrealistic, camera, DSLR"
        # as negatives — which directly contradicts this preset's entire purpose.
        # This override removes those terms and instead pushes against underexposure
        # and flat/washed output that FLUX can produce without a realism LoRA.
        "negative_prompt": (
            "bad hands, extra fingers, four fingers, three fingers, wrong number of fingers, "
            "bad anatomy, deformed, ugly, "
            "blurry, out of focus, soft focus, hazy, foggy, low resolution, "
            "underexposed, too dark, pitch black, barely visible, muddy dark colors, "
            "flat lighting, harsh shadows with no fill, blown out highlights, "
            "overexposed, washed out, white background, pure white, "
            "watermark, text, border, card frame, out of frame, cropped, "
            "cartoon, anime, illustrated, painterly, sketch, drawing, nsfw"
        ),
        "loras": [
            {
                "fragments":      ["xlabs_realism", "realismflux", "realism_lora", "flux_realism"],
                "trigger":        "",
                "model_strength": 0.70,
                "clip_strength":  0.70,
                "dark_only":      False,
                "label":          "FLUX Realism (XLabs-AI)",
                "download_url":   "https://huggingface.co/XLabs-AI/flux-RealismLora",
                "download_note":  "Download lora.safetensors → rename to xlabs_realism_lora.safetensors",
            },
            {
                "fragments":      ["cinematic"],
                "trigger":        "Cinematic style",
                "model_strength": 0.45,
                "clip_strength":  0.45,
                "dark_only":      False,
                "label":          "Cinematic Style",
                "download_url":   "https://civitai.com/models/680417",
                "download_note":  "Save as cinematic_style_flux.safetensors",
            },
        ],
    },

    # ── Tech-noir cyberpunk ────────────────────────────────────────────────────
    "cyberpunk": {
        "label":       "Cyberpunk",
        "description": "Neon-lit tech-noir — rain-slicked streets, chrome, holographics, Blade Runner aesthetic.",
        "icon":        "🌆",
        "style_guide_hint":  "cyberpunk digital painting, neon-lit tech-noir, glowing electric neon colors illuminating the scene brightly",
        "themer_medium":     '"digital painting," or "cyberpunk concept art," or "neon-lit illustration,"',
        "themer_quality":    '"glowing neon lights, vivid electric colors" or "cyberpunk neon glow, bright illumination" or "painterly, luminous neon palette"',
        # flux_prefix: lead with BRIGHT glowing neon light sources so FLUX doesn't
        # default to near-black.  "vivid neon palette against deep shadows" was the
        # old wording — FLUX over-weighted "deep shadows" and generated near-black
        # frames.  Now we anchor on luminosity first, then add dark atmosphere second.
        "flux_prefix": (
            "Digital painting, cyberpunk concept art. "
            "Vivid glowing neon lights — electric magenta, cyan, deep blue — "
            "flood the scene with bright colorful illumination. "
            "Rain-slicked streets mirror the neon glows. Chrome and glass architecture, "
            "holographic overlays, retrofuturistic technology. "
            "Well-lit scene with intense neon color. High detail, sharp focus. "
            "Wide landscape composition, subject fully centered and in frame. "
            "Any visible hands have exactly five fingers each. "
        ),
        # Cyberpunk-specific negative: push FLUX away from near-black underexposure.
        # Without this the model happily makes the whole scene black and dots a
        # few neon pixels in, which reads as 'deep shadows' but looks like a failure.
        "negative_prompt": (
            "bad hands, extra fingers, four fingers, three fingers, wrong number of fingers, "
            "bad anatomy, deformed, ugly, "
            "underexposed, too dark, pitch black, barely visible, muddy dark, dark muddy colors, "
            "dark background, all black, completely black, near black, "
            "overexposed, washed out, blown out, pure white, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        "loras": [
            {
                "fragments":      ["neon_noir", "neonnoir"],
                "trigger":        "mad-neon-noir",
                "model_strength": 0.75,
                "clip_strength":  0.75,
                "dark_only":      False,
                "label":          "Neon Noir",
                "download_url":   "https://civitai.com/models/300898",
                "download_note":  "Save as neon_noir_flux.safetensors",
            },
            {
                "fragments":      ["cyberpunk_detailer", "cbrpnk", "Neon_Cyberpunk_Detailer"],
                "trigger":        "mad-cbrpnk-dtlr",
                "model_strength": 0.50,
                "clip_strength":  0.50,
                "dark_only":      False,
                "label":          "Cyberpunk Detailer",
                "download_url":   "https://civitai.com/models/730615",
                "download_note":  "Neon_Cyberpunk_Detailer_FLUX_multi_trigger.safetensors",
            },
        ],
    },

    # ── Post-apocalyptic desert wasteland ─────────────────────────────────────
    "desert_punk": {
        "label":       "Desert Punk",
        "description": "Post-apocalyptic wasteland — Mad Max / Fallout, salvaged tech, harsh sun, dust and rust.",
        "icon":        "🏜️",
        "style_guide_hint":  "post-apocalyptic gritty concept art, warm ochre and rust palette, dramatic side lighting",
        "themer_medium":     '"digital painting," or "post-apocalyptic concept art," or "gritty illustration,"',
        "themer_quality":    '"dramatic side lighting, warm earth tones" or "gritty detail, dust-hazed atmosphere" or "painterly, vivid ochre and rust palette"',
        # NOTE: avoid "bleached sky" / "harsh overhead sunlight" — at FLUX CFG 5.0
        # those resolve to pure white overexposure.  Use warm earth-tone anchors +
        # dramatic side/rim lighting instead to keep the desert feel without blowout.
        "flux_prefix": (
            "Digital painting, post-apocalyptic concept art. "
            "Sun-scorched desert wasteland, cracked red earth, amber dust haze. "
            "Salvaged rust-stained armor, retrofuture survival gear, weathered bone and metal. "
            "Dramatic side lighting, deep shadows, warm ochre and burnt sienna palette. "
            "High detail, wide landscape composition, subject fully centered and in frame. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["retrofuture", "dystopia"],
                "trigger":        "RetroFutureDystopia",
                "model_strength": 0.50,
                "clip_strength":  0.65,
                "dark_only":      False,
                "label":          "Retro Future Dystopia",
                "download_url":   "https://civitai.com/models/886913",
                "download_note":  "Save as retrofuture_dystopia.safetensors",
            },
        ],
    },

    # ── Japanese animation ────────────────────────────────────────────────────
    "anime": {
        "label":       "Anime / Manga",
        "description": "Japanese animation style — vibrant flat color, clean linework, expressive characters.",
        "icon":        "🎌",
        "style_guide_hint":  "anime / manga illustration style, flat colour, clean linework, cel-shaded, expressive characters",
        "themer_medium":     '"anime illustration," or "manga art," or "anime concept art,"',
        "themer_quality":    '"clean linework, flat color shading" or "cel-shaded, vibrant flat colors" or "anime style, smooth clean illustration"',
        # Strong multi-keyword anime trigger.  The FLUX base model has a heavy
        # photorealistic prior, so we hammer the anime style with several
        # reinforcing cues at the very start of the prompt where CLIP weights
        # tokens most heavily.  Combined with model_strength 1.0 this gives the
        # LoRA enough authority to actually flip the output to anime.
        "flux_prefix": (
            "Flat colour anime style image showing, anime illustration, manga art, "
            "cel-shaded, flat colour shading, clean bold linework, vibrant saturated colors, "
            "2D anime aesthetic, expressive anime character design, no photographic detail. "
        ),
        # face_prefix overrides for anime — "Painted portrait, painterly skin tones"
        # would inject oil-painting language into a cel-shaded anime prompt.
        "face_prefix_medium": "Anime illustration portrait",
        "face_prefix_quality": "clean cel-shaded face, bold expressive anime eyes",
        # Anime-specific negative — overrides _FLUX_NEGATIVE for this preset.
        # The default negative is fine for other presets, but here we need to
        # actively push AGAINST realism / 3D / painterly that FLUX defaults to.
        "negative_prompt": (
            "photograph, photo, photorealistic, hyperrealistic, realistic, "
            "3d render, cgi, octane render, unreal engine, blender, "
            "oil painting, painterly brushwork, impasto, textured brush strokes, "
            "live-action, film still, dslr, depth of field bokeh, "
            "bad hands, extra fingers, bad anatomy, deformed, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        "loras": [
            {
                "fragments":      ["flatcolor", "flatcolour", "flat_col", "flat_color"],
                "trigger":        "",   # trigger already embedded in flux_prefix
                # Bumped 0.80 → 1.0 — FLUX's photoreal prior is strong enough
                # that the anime LoRA needs full strength to flip the output.
                "model_strength": 1.0,
                "clip_strength":  1.0,
                "dark_only":      False,
                "label":          "Flat Colour Anime v3.4",
                "download_url":   "https://civitai.com/models/180891",
                "download_note":  "Get FLUX v3.4 version → save as flatcolor_anime_flux.safetensors",
            },
        ],
    },

    # ── Art Nouveau / Mucha ────────────────────────────────────────────────────
    "art_nouveau": {
        "label":       "Art Nouveau",
        "description": "Alphonse Mucha / Klimt — flowing organic forms, decorative borders, gold and nature.",
        "icon":        "🌿",
        "style_guide_hint":  "Alphonse Mucha art nouveau illustration, ornate decorative borders, flowing organic linework, gold leaf and jewel tones",
        "themer_medium":     '"art nouveau illustration," or "Alphonse Mucha style," or "decorative illustration,"',
        "themer_quality":    '"ornate decorative detail, flowing linework" or "art nouveau style, gold accent detail" or "detailed ornamental, jewel-tone palette"',
        "flux_prefix": (
            "Alphonse Mucha Style, art nouveau illustration, decorative ornamental border, "
            "flowing organic lines, nature motifs, gold leaf accents, rich jewel tones. "
            "High detail, intricate composition, subject fully in frame. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["mucha"],
                "trigger":        "Alphonse Mucha Style",
                "model_strength": 0.70,
                "clip_strength":  0.70,
                "dark_only":      False,
                "label":          "Alphonse Mucha Style",
                "download_url":   "https://civitai.com/models/63072",
                "download_note":  "Save as mucha_style_flux.safetensors",
            },
        ],
    },

    # ── Gothic Horror ─────────────────────────────────────────────────────────
    "gothic_horror": {
        "label":       "Gothic Horror",
        "description": "Innistrad-style dark gothic — haunted mansions, vampires, moonlit fog, stone gargoyles.",
        "icon":        "🏚️",
        "style_guide_hint":  "dark gothic horror illustration, moonlit haunted atmosphere, muted charcoal and deep violet palette, crumbling stone architecture",
        "themer_medium":     '"dark gothic illustration," or "horror concept art," or "gothic painting,"',
        "themer_quality":    '"atmospheric moonlit shadows, muted palette" or "gothic horror detail, dramatic chiaroscuro" or "cinematic horror mood, cold violet light"',
        "flux_prefix": (
            "Digital painting, dark gothic horror illustration. "
            "Moonlit haunted stone architecture — crumbling gargoyles, iron gates, fog-shrouded graveyards. "
            "Deep shadow pools broken by pale candlelight and cold moonbeams. "
            "Muted palette of charcoal, slate, deep violet, and silver moonlight. "
            "Atmospheric and unsettling, cinematic horror mood. "
            "Wide landscape composition, subject fully centered and in frame. "
            "Any visible hands have exactly five fingers each. "
        ),
        "negative_prompt": (
            "bad hands, extra fingers, four fingers, three fingers, wrong number of fingers, "
            "bad anatomy, deformed, ugly, "
            "overexposed, washed out, blown out, pure white, "
            "colorful, bright, cheerful, sunny, pastel, vibrant rainbow, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        "loras": [
            {
                "fragments":      ["Dark_Haunted_Fantasy", "dark_haunted_fantasy", "halloweenstyle"],
                "trigger":        "halloweenstyle",
                "model_strength": 0.70,
                "clip_strength":  0.70,
                "dark_only":      False,
                "label":          "Dark Haunted Fantasy",
                "download_url":   "https://civitai.com/models/849375",
                "download_note":  "Dark_Haunted_Fantasy_v5.safetensors — download v5.0 HD+ version",
            },
            {
                "fragments":      ["Dark_Gothic_Horror", "dark_gothic_horror"],
                "trigger":        "",
                "model_strength": 0.45,
                "clip_strength":  0.45,
                "dark_only":      False,
                "label":          "Gothic Horror Atmosphere",
                "download_url":   "https://civitai.com/models/1128317",
                "download_note":  "Dark_Gothic_Horror_Eerie_Shadows_of_Macabre_Fantasy_Worlds.safetensors",
            },
        ],
    },

    # ── Watercolor Illustration ───────────────────────────────────────────────
    "watercolor": {
        "label":       "Watercolor",
        "description": "Traditional watercolor painting — soft wet-on-wet blooms, translucent washes, paper texture.",
        "icon":        "🎨",
        "style_guide_hint":  "traditional watercolor illustration, soft wet-on-wet color blooms, translucent layered washes, visible paper texture",
        "themer_medium":     '"watercolor illustration," or "watercolor painting," or "traditional watercolor,"',
        "themer_quality":    '"soft watercolor washes, translucent layers" or "wet-on-wet blooms, painterly texture" or "loose brushwork, gentle color bleeds"',
        "flux_prefix": (
            "Watercolor illustration, traditional watercolor painting. "
            "Soft wet-on-wet color blooms, translucent washes layered over textured paper. "
            "Flowing organic edges where colors blend and bleed naturally. "
            "Vivid yet soft palette with subtle granulation and gentle color transitions. "
            "Hand-painted watercolor aesthetic with visible brushwork and paper tooth. "
            "Wide landscape composition, subject fully centered and in frame. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["WATERCOLOR-lora", "watercolor_lora", "WATERCOLORlora"],
                "trigger":        "watercolor, wet on wet, paintstreaks, watercolor painting",
                "model_strength": 0.85,
                "clip_strength":  0.85,
                "dark_only":      False,
                "label":          "WATERCOLOR FLUX",
                "download_url":   "https://civitai.com/models/840424",
                "download_note":  "WATERCOLOR-lora.TA_trained.safetensors",
            },
        ],
    },

    # ── Steampunk ─────────────────────────────────────────────────────────────
    "steampunk": {
        "label":       "Steampunk",
        "description": "Kaladesh-style Victorian machinery — brass gears, copper pipes, clockwork, steam and smog.",
        "icon":        "⚙️",
        "style_guide_hint":  "steampunk illustration, Victorian brass and copper machinery, intricate clockwork gears, warm amber gas-lamp tones",
        "themer_medium":     '"steampunk illustration," or "clockpunk concept art," or "Victorian mechanical painting,"',
        "themer_quality":    '"intricate gear detail, warm amber palette" or "brass and copper texture, mechanical precision" or "painterly steampunk, steam and smog atmosphere"',
        "flux_prefix": (
            "Digital painting, steampunk illustration. "
            "Intricate brass and copper clockwork mechanisms — cogs, gears, pipes, and valves. "
            "Victorian-industrial architecture with iron girders and glass-domed dirigibles. "
            "Steam venting from ornate machinery, amber gas-lamp glow. "
            "Rich warm tones of burnished gold, deep brown leather, and patina green. "
            "Mechanical detail-rich composition. "
            "Wide landscape, subject fully centered and in frame. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["SteampunkIllustration", "steampunk_illustration", "steampunk_illus"],
                "trigger":        "steampunk illustration, mechanical, cogs and gears, copper pipes, ornate",
                "model_strength": 0.80,
                "clip_strength":  0.80,
                "dark_only":      False,
                "label":          "Steampunk Illustration",
                "download_url":   "https://civitai.com/models/799887",
                "download_note":  "SteampunkIllustration_v1.safetensors",
            },
        ],
    },

    # ── Oil Painting / Old Masters ─────────────────────────────────────────────
    "oil_painting": {
        "label":       "Oil Painting",
        "description": "Classical Renaissance / Baroque — chiaroscuro, rich impasto brushwork, Old Masters palette.",
        "icon":        "🖼️",
        "style_guide_hint":  "classical oil painting, Renaissance and Baroque style, chiaroscuro lighting, rich impasto brushwork, Old Masters technique",
        "themer_medium":     '"oil painting," or "classical painting," or "Renaissance illustration,"',
        "themer_quality":    '"rich impasto brushwork, chiaroscuro lighting" or "Old Masters oil technique, jewel-tone palette" or "painterly, dramatic shadows and warm highlights"',
        "flux_prefix": (
            "Oil painting, classical Renaissance style. "
            "Rich oil paint textures with visible brushwork and impasto highlights. "
            "Chiaroscuro dramatic lighting — deep warm shadows with bright focal highlights. "
            "Rich jewel tones: deep crimson, burnished gold, deep blue, burnt sienna. "
            "Baroque compositional drama, majestic and timeless. "
            "Wide landscape composition, subject fully centered and in frame. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["oil_painting_flux", "oil_painting_flux-h"],
                "trigger":        "oil painting",
                "model_strength": 0.75,
                "clip_strength":  0.75,
                "dark_only":      False,
                "label":          "Oil Painting (Renaissance) FLUX",
                "download_url":   "https://civitai.com/models/849568",
                "download_note":  "oil_painting_flux-h.safetensors",
            },
        ],
    },

    # ── Pixel Art Retro ───────────────────────────────────────────────────────
    "pixel_art": {
        "label":       "Pixel Art",
        "description": "Retro 16-bit video game style — clean pixel grid, limited palette, SNES-era sprites.",
        "icon":        "🕹️",
        "style_guide_hint":  "retro pixel art illustration, 16-bit SNES game art style, clean pixel grid, limited color palette, dithered shading",
        "themer_medium":     '"pixel art," or "retro game illustration," or "16-bit pixel art,"',
        "themer_quality":    '"clean pixel grid, limited retro palette" or "16-bit game art, dithered shading" or "pixel art sprite, crisp pixel edges"',
        "flux_prefix": (
            "Pixel art illustration, retro video game graphics. "
            "Clean square pixels with limited color palette, dithering patterns on gradients. "
            "SNES-era 16-bit aesthetic with bold readable sprites and crisp pixel edges. "
            "No anti-aliasing, no blur — every element is made of clean distinct pixels. "
            "Vibrant saturated retro game colors. "
            "Wide composition, subject fully in frame. "
        ),
        "negative_prompt": (
            "bad hands, extra fingers, bad anatomy, deformed, ugly, "
            "photograph, photo, photorealistic, hyperrealistic, "
            "blurry, out of focus, soft focus, anti-aliased, smooth gradients, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        "loras": [
            {
                "fragments":      ["Pixel_Art_FLUX", "pixel_art_flux", "PixelArtFLUX"],
                "trigger":        "pixel art",
                "model_strength": 0.90,
                "clip_strength":  0.90,
                "dark_only":      False,
                "label":          "Pixel Art Illustrations FLUX",
                "download_url":   "https://civitai.com/models/683579",
                "download_note":  "Pixel_Art_FLUX.safetensors (V1 Illustrative shaded — most downloads)",
            },
        ],
    },

    # ── Eldritch / Cosmic Horror ──────────────────────────────────────────────
    "eldritch": {
        "label":       "Eldritch Horror",
        "description": "Lovecraftian cosmic horror — Eldrazi-scale impossible entities, void geometry, ancient malice.",
        "icon":        "👁️",
        "style_guide_hint":  "eldritch cosmic horror illustration, Lovecraftian impossible geometry, deep space void palette, ancient terrifying entities",
        "themer_medium":     '"eldritch illustration," or "cosmic horror concept art," or "Lovecraftian painting,"',
        "themer_quality":    '"impossible geometry, void-black and sickly chartreuse" or "cosmic horror atmosphere, ancient malice" or "tentacled entities, non-Euclidean architecture"',
        "flux_prefix": (
            "Digital illustration, eldritch cosmic horror comic art style. "
            "Impossible non-Euclidean geometries and writhing tentacled entities emerging from star-filled void. "
            "Deep space palette: sickly chartreuse, cosmic violet, void black, and pallid bone white. "
            "Oppressive sense of scale and ancient malice. "
            "Tentacles, eyes, and alien architecture woven into impossible shapes. "
            "Wide landscape composition, subject fully centered and in frame. "
            "Any visible hands have exactly five fingers each. "
        ),
        "negative_prompt": (
            "bad hands, extra fingers, four fingers, three fingers, wrong number of fingers, "
            "bad anatomy, deformed, ugly, "
            "overexposed, washed out, blown out, pure white, "
            "bright cheerful colors, pastel, rainbow, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        "loras": [
            {
                "fragments":      ["Eldritch_Comics", "eldritch_comics", "Eldritch_Comics_for_Flux"],
                "trigger":        "illustration",
                "model_strength": 0.75,
                "clip_strength":  0.75,
                "dark_only":      False,
                "label":          "Eldritch Comics",
                "download_url":   "https://civitai.com/models/671064",
                "download_note":  "Eldritch_Comics_for_Flux_1.1.safetensors (v1.1 version)",
            },
            {
                "fragments":      ["Dark_Haunted_Fantasy", "dark_haunted_fantasy", "halloweenstyle"],
                "trigger":        "halloweenstyle",
                "model_strength": 0.30,
                "clip_strength":  0.30,
                "dark_only":      False,
                "label":          "Dark Haunted (atmosphere layer)",
                "download_url":   "https://civitai.com/models/849375",
                "download_note":  "Dark_Haunted_Fantasy_v5.safetensors (shared with Gothic Horror preset)",
            },
        ],
    },

    # ── Stained Glass ─────────────────────────────────────────────────────────
    "stained_glass": {
        "label":       "Stained Glass",
        "description": "Medieval cathedral stained glass — bold lead lines, jewel-tone luminous panels, gothic rose windows.",
        "icon":        "🪟",
        "style_guide_hint":  "medieval stained glass window art, bold black lead lines, jewel-tone luminous glass panels, gothic cathedral aesthetic",
        "themer_medium":     '"stained glass illustration," or "stained glass window art," or "medieval stained glass,"',
        "themer_quality":    '"jewel-tone glass panels, bold lead lines" or "luminous stained glass, gothic cathedral light" or "vivid glass segments, medieval window art"',
        "flux_prefix": (
            "Stained glass window art style. "
            "Bold black lead lines partition vibrant jewel-toned glass panels — "
            "deep ruby red, royal cobalt blue, emerald green, golden amber, and royal purple. "
            "Each glass segment glows with luminous transmitted light, translucent and vivid. "
            "Gothic rose window aesthetics, divine grandeur. "
            "Flat bold colors within cells, strong graphic composition. "
            "Wide landscape, subject fully centered and in frame. "
        ),
        "loras": [
            {
                "fragments":      ["StainedGlassFlux", "StainedGlass_flux", "stained_glass_flux"],
                "trigger":        "ArsMJStyle, Stained Glass",
                "model_strength": 0.90,
                "clip_strength":  0.90,
                "dark_only":      False,
                "label":          "Stained Glass FLUX",
                "download_url":   "https://civitai.com/models/553811",
                "download_note":  "StainedGlassFlux.safetensors — download the Flux version",
            },
            {
                "fragments":      ["Stained_Glass_Style", "stained_glass_style"],
                "trigger":        "Stained Glass Style",
                "model_strength": 0.50,
                "clip_strength":  0.50,
                "dark_only":      False,
                "label":          "Stained Glass Style",
                "download_url":   "https://civitai.com/models/1007585",
                "download_note":  "Stained_Glass_Style.safetensors",
            },
        ],
    },
}

# ── Public preset metadata (safe for the API — no internal LoRA details) ──────
STYLE_PRESETS: dict[str, dict] = {
    key: {
        "label":            p["label"],
        "description":      p["description"],
        "icon":             p["icon"],
        "lora_count":       len(p["loras"]),
        # Themer vocabulary — passed to themer.theme_deck() so Ollama generates
        # prompts whose medium/quality language matches the active art style.
        "style_guide_hint": p.get("style_guide_hint", ""),
        "themer_medium":    p.get("themer_medium", '"digital painting," or "fantasy illustration," or "concept art,"'),
        "themer_quality":   p.get("themer_quality", '"painterly brushwork, vivid colors" or "dramatic lighting, intricate detail" or "painterly, rich texture"'),
    }
    for key, p in _LORA_PRESETS.items()
}


# ── Custom user-created presets (persisted to custom_presets.json) ────────────
import os as _os, json as _json

_CUSTOM_PRESETS_PATH = _os.path.join(_os.path.dirname(__file__), "custom_presets.json")


def _load_custom_presets() -> dict:
    """Load user-created presets from custom_presets.json."""
    if not _os.path.exists(_CUSTOM_PRESETS_PATH):
        return {}
    try:
        with open(_CUSTOM_PRESETS_PATH, "r", encoding="utf-8") as _f:
            return _json.load(_f)
    except Exception as _e:
        print(f"  [image_gen] Warning: could not load custom_presets.json: {_e}")
        return {}


def _save_custom_presets(presets: dict) -> None:
    """Persist custom presets to disk."""
    try:
        with open(_CUSTOM_PRESETS_PATH, "w", encoding="utf-8") as _f:
            _json.dump(presets, _f, indent=2, ensure_ascii=False)
    except Exception as _e:
        print(f"  [image_gen] Warning: could not save custom_presets.json: {_e}")


def get_all_presets() -> dict:
    """Return built-in + custom presets merged.  Custom entries win on key collision."""
    merged = dict(_LORA_PRESETS)
    merged.update(_load_custom_presets())
    return merged


def upsert_custom_preset(key: str, preset: dict) -> None:
    """Add or update a custom preset by key and flush to disk."""
    customs = _load_custom_presets()
    customs[key] = preset
    _save_custom_presets(customs)


def delete_custom_preset(key: str) -> bool:
    """Remove a custom preset.  Returns True if it existed."""
    customs = _load_custom_presets()
    if key not in customs:
        return False
    del customs[key]
    _save_custom_presets(customs)
    return True


def _theme_darkness_score(text: str) -> float:
    """
    Score how dark/grim a theme is on a 0.0–1.0 scale.

    Returns:
        1.0 — neutral (no keywords found) or clearly dark
        ~0.2 — strongly light/whimsical (e.g. "cats fantasy rainbow")

    Used to scale down ``dark_only`` LoRA strengths so vivid or
    playful themes aren't crushed into murky fantasy darkness.
    """
    t = text.lower()
    DARK_WORDS = {
        "dark", "shadow", "grim", "gothic", "horror", "void", "abyss", "undead",
        "death", "necro", "demon", "evil", "sinister", "bleak", "dread", "doom",
        "corrupted", "cursed", "infernal", "hellish", "forsaken", "eldritch",
        "bone", "decay", "wither", "blight", "pestilence", "rot", "ruin",
        "macabre", "plague", "nightmare", "shade", "specter", "wraith",
    }
    LIGHT_WORDS = {
        "rainbow", "pastel", "bright", "whimsical", "cute", "cheerful", "colorful",
        "vibrant", "sunny", "cozy", "fluffy", "gentle", "playful", "bubbly",
        "happy", "joyful", "fairy", "soft", "warm", "light", "sparkle", "glitter",
        "cats", "kittens", "puppies", "flowers", "garden", "spring", "summer",
        "celestial", "radiant", "golden", "crystal", "prismatic", "candy",
        "magical girl", "kawaii", "sweet", "dreamy", "merry", "serene", "lush",
    }
    dark_count  = sum(1 for w in DARK_WORDS  if w in t)
    light_count = sum(1 for w in LIGHT_WORDS if w in t)

    if light_count == 0 and dark_count == 0:
        return 1.0   # neutral theme — dark LoRAs run at full strength

    # ratio in [-1 (all light), +1 (all dark)]
    ratio = (dark_count - light_count) / (dark_count + light_count)
    # Map to [0.20, 1.0] so dark LoRAs are never fully zeroed out
    return round(0.20 + 0.80 * (ratio + 1) / 2, 3)


def _insert_loras(
    workflow: dict,
    checkpoint_node_id: str,
    loras: list[dict],
) -> dict:
    """
    Chain LoRA loader nodes into a ComfyUI workflow.

    Each LoRA wraps the previous model + clip output, then:
    - KSampler / ApplyPulidFlux nodes are rewired to the final model
    - CLIPTextEncode nodes are rewired to the final clip

    Works for both standard FLUX and PuLID FLUX workflows because we target
    class_type strings rather than hardcoded node IDs.
    """
    if not loras:
        return workflow
    wf = dict(workflow)
    max_id = max(int(k) for k in wf.keys() if k.isdigit())

    prev_model = [checkpoint_node_id, 0]
    prev_clip  = [checkpoint_node_id, 1]

    for entry in loras:
        max_id += 1
        nid = str(max_id)
        wf[nid] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model":          prev_model,
                "clip":           prev_clip,
                "lora_name":      entry["filename"],
                "strength_model": entry["model_strength"],
                "strength_clip":  entry["clip_strength"],
            },
        }
        prev_model = [nid, 0]
        prev_clip  = [nid, 1]

    # Rewire downstream nodes
    for node in wf.values():
        ct = node.get("class_type", "")
        inp = node.get("inputs", {})
        if ct in ("KSampler", "KSamplerAdvanced"):
            # Only rewire if model was coming from the checkpoint
            if inp.get("model", [None])[0] == checkpoint_node_id:
                inp["model"] = prev_model
        if ct == "CLIPTextEncode":
            inp["clip"] = prev_clip
        if ct == "ApplyPulidFlux":
            # PuLID wraps the model — update its model input too
            if inp.get("model", [None])[0] == checkpoint_node_id:
                inp["model"] = prev_model

    return wf


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def _is_flux(name: str) -> bool:
    return "flux" in name.lower()

def _is_sd35(name: str) -> bool:
    """SD 3.5 (Large or Medium) — recognised by `sd3.5`, `sd35`, or `stable-diffusion-3` in the filename."""
    n = name.lower()
    return ("sd3.5" in n) or ("sd35" in n) or ("stable-diffusion-3" in n) or ("sd3_" in n)

def _is_ltx(name: str) -> bool:
    return "ltx" in name.lower()


def _summarize_comfy_error(resp) -> str:
    """
    ComfyUI 400 responses include detailed validation errors.  Pull out the
    human-readable bits so we don't leave the user staring at '400 Client Error'.

    Format examples observed:
      { "error": { "message": "...", "details": "...", "type": "..." },
        "node_errors": { "5": { "errors": [{"message": "...", "details": "..."}], ... } } }
    """
    try:
        body = resp.json()
    except Exception:
        snippet = (resp.text or "")[:200].strip()
        return snippet or "<no body>"

    parts: list[str] = []
    err = body.get("error") or {}
    if isinstance(err, dict):
        msg = err.get("message") or ""
        det = err.get("details") or ""
        if msg:
            parts.append(msg.strip())
        if det and det.strip() != msg.strip():
            parts.append(det.strip())

    node_errs = body.get("node_errors") or {}
    if isinstance(node_errs, dict):
        for node_id, ne in list(node_errs.items())[:3]:   # cap to 3 nodes
            if not isinstance(ne, dict):
                continue
            for e in (ne.get("errors") or [])[:2]:        # cap to 2 errors/node
                em = (e.get("message") or "").strip()
                ed = (e.get("details") or "").strip()
                if em or ed:
                    parts.append(f"node {node_id}: {em}{' — ' + ed if ed else ''}")

    return " | ".join(parts) if parts else (resp.text or "")[:200].strip()


# ── Standard workflow builders ────────────────────────────────────────────────

def _build_sdxl_workflow(checkpoint: str, positive: str, seed: int) -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage",        "inputs": {"width": CARD_WIDTH, "height": CARD_HEIGHT, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode",          "inputs": {"text": positive,        "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode",          "inputs": {"text": NEGATIVE_PROMPT, "clip": ["4", 1]}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                # 30 steps + cfg 7.5 gives noticeably cleaner anatomy than 25/7.0
                "seed": seed, "steps": 30, "cfg": 7.5,
                "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mtg_card", "images": ["8", 0]}},
    }


def _build_flux_workflow(checkpoint: str, positive: str, seed: int,
                          negative: str = "") -> dict:
    neg = negative or _FLUX_NEGATIVE
    is_schnell = "schnell" in checkpoint.lower()
    # Schnell: 8 steps / CFG 1.5 / euler + simple   (fast draft quality)
    # Dev fp8: 35 steps / CFG 7.0 / dpm++_2m + sgm_uniform
    #   35 steps adds fine texture and edge crispness.
    #   CFG 7.0 (up from 5.5) forces sharper edges, crisper linework, and
    #   better prompt adherence without over-saturating at 1152x768.
    #   dpm++_2m + sgm_uniform remains the sharpest combo for illustration detail.
    steps    = 8            if is_schnell else 35
    cfg      = 1.5          if is_schnell else 7.0
    sampler  = "euler"      if is_schnell else "dpmpp_2m"
    scheduler= "simple"     if is_schnell else "sgm_uniform"
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "EmptyLatentImage",       "inputs": {"width": CARD_WIDTH, "height": CARD_HEIGHT, "batch_size": 1}},
        "3": {"class_type": "CLIPTextEncode",         "inputs": {"text": positive, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",         "inputs": {"text": neg,      "clip": ["1", 1]}},
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg,
                "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0,
                "model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["2", 0],
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mtg_card", "images": ["6", 0]}},
    }


def _build_sd35_workflow(checkpoint: str, positive: str, seed: int,
                          negative: str = "") -> dict:
    """
    SD 3.5 Large (all-in-one fp8 checkpoint with text encoders baked in).
    Community-tested settings (Nov 2024 SAI release):
      28-35 steps, CFG 4.0-4.5, sampler dpmpp_2m + sgm_uniform.
    SD3.5 responds to negative prompts (unlike FLUX at low CFG), so we use the
    full SDXL-style negative.  Uses ModelSamplingSD3 to set the timestep shift.
    """
    neg = negative or NEGATIVE_PROMPT
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "EmptyLatentImage",       "inputs": {"width": CARD_WIDTH, "height": CARD_HEIGHT, "batch_size": 1}},
        "3": {"class_type": "CLIPTextEncode",         "inputs": {"text": positive, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",         "inputs": {"text": neg,      "clip": ["1", 1]}},
        # ModelSamplingSD3 sets the timestep shift for SD3-family models (3.0 is the SAI default for Large)
        "8": {"class_type": "ModelSamplingSD3",       "inputs": {"shift": 3.0, "model": ["1", 0]}},
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": 30, "cfg": 4.5,
                "sampler_name": "dpmpp_2m", "scheduler": "sgm_uniform", "denoise": 1.0,
                "model": ["8", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["2", 0],
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mtg_card", "images": ["6", 0]}},
    }


def _build_workflow(checkpoint: str, positive: str, seed: int,
                     negative: str = "") -> dict:
    if _is_sd35(checkpoint):
        return _build_sd35_workflow(checkpoint, positive, seed, negative=negative)
    if _is_flux(checkpoint):
        return _build_flux_workflow(checkpoint, positive, seed, negative=negative)
    return _build_sdxl_workflow(checkpoint, positive, seed)


# ── Face-conditioning workflow builders ───────────────────────────────────────

def _build_pulid_flux_workflow(
    checkpoint: str, positive: str, seed: int,
    face_comfy_name: str,
    pulid_model: str,
    eva_clip_model: str,
    negative: str = "",
) -> dict:
    neg = negative or _FLUX_NEGATIVE
    """
    FLUX + PuLID face-conditioning workflow.
    ApplyPulidFlux wraps the base model so the KSampler generates
    an image whose subject resembles the reference face.
    """
    is_schnell = "schnell" in checkpoint.lower()
    steps    = 8            if is_schnell else 35
    cfg      = 1.5          if is_schnell else 7.0
    sampler  = "euler"      if is_schnell else "dpmpp_2m"
    scheduler= "simple"     if is_schnell else "sgm_uniform"
    return {
        "1":  {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2":  {"class_type": "EmptyLatentImage",       "inputs": {"width": CARD_WIDTH, "height": CARD_HEIGHT, "batch_size": 1}},
        "3":  {"class_type": "CLIPTextEncode",         "inputs": {"text": positive, "clip": ["1", 1]}},
        "4":  {"class_type": "CLIPTextEncode",         "inputs": {"text": neg,      "clip": ["1", 1]}},
        # PuLID face nodes
        "10": {"class_type": "PulidModelLoader", "inputs": {"pulid_file": pulid_model}},
        "11": {"class_type": "EVACLIPLoader",    "inputs": {"model_name": eva_clip_model, "device": "cuda"}},
        "12": {"class_type": "LoadImage",        "inputs": {"image": face_comfy_name}},
        "13": {
            "class_type": "ApplyPulidFlux",
            "inputs": {
                "model":        ["1",  0],
                "pulid":        ["10", 0],
                "eva_clip":     ["11", 0],
                "face_image":   ["12", 0],
                "weight":       0.85,
                "start_at":     0.0,
                "end_at":       1.0,
                "fusion":       "mean",
                "fusion_weight": 1.0,
            },
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": steps, "cfg": cfg,
                "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0,
                "model":        ["13", 0],   # conditioned model
                "positive":     ["3",  0],
                "negative":     ["4",  0],
                "latent_image": ["2",  0],
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mtg_card", "images": ["6", 0]}},
    }


def _build_faceid_sdxl_workflow(
    checkpoint: str, positive: str, seed: int,
    face_comfy_name: str,
    ipadapter_model: str,
    clip_vision_model: str,
) -> dict:
    """
    SDXL + IP-Adapter FaceID workflow.
    IPAdapterFaceID modifies the model so generated portraits resemble
    the reference face.
    """
    return {
        "1": {"class_type": "CheckpointLoaderSimple",  "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "EmptyLatentImage",         "inputs": {"width": CARD_WIDTH, "height": CARD_HEIGHT, "batch_size": 1}},
        "3": {"class_type": "CLIPTextEncode",           "inputs": {"text": positive,        "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",           "inputs": {"text": NEGATIVE_PROMPT, "clip": ["1", 1]}},
        # IP-Adapter FaceID nodes
        "10": {"class_type": "IPAdapterUnifiedLoader",  "inputs": {
            "model":          ["1", 0],
            "preset":         "FACEID PLUS V2",
            "lora_strength":  0.6,
            "provider":       "CUDA",
        }},
        "11": {"class_type": "LoadImage",               "inputs": {"image": face_comfy_name}},
        "12": {
            "class_type": "IPAdapterFaceID",
            "inputs": {
                "model":     ["10", 0],
                "ipadapter": ["10", 1],
                "image":     ["11", 0],
                "weight":    0.8,
                "weight_faceidv2": 1.0,
                "weight_type": "linear",
                "combine_embeds": "concat",
                "start_at":  0.0,
                "end_at":    1.0,
                "embeds_scaling": "V only",
            },
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": 25, "cfg": 6.5,
                "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
                "model":        ["12", 0],
                "positive":     ["3",  0],
                "negative":     ["4",  0],
                "latent_image": ["2",  0],
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mtg_card", "images": ["6", 0]}},
    }


def _append_reactor(
    workflow: dict,
    face_comfy_name: str,
    swap_model:    str = "inswapper_128.onnx",
    restore_model: str = "codeformer-v0.1.0.pth",
) -> dict:
    """
    Append a ReActorFaceSwap node after the VAEDecode in any workflow.
    source_image is wired to the uploaded face reference (optional input).
    SaveImage is rewired to the reactor output.

    Required ReActor inputs (from nodes.py inspection):
      enabled, input_image, swap_model, facedetection,
      face_restore_model, face_restore_visibility, codeformer_weight,
      detect_gender_input, detect_gender_source,
      input_faces_index, source_faces_index, console_log_level
    Optional: source_image, face_model, face_boost
    """
    vae_node_id  = None
    save_node_id = None
    for nid, node in workflow.items():
        if node["class_type"] == "VAEDecode":
            vae_node_id = nid
        if node["class_type"] == "SaveImage":
            save_node_id = nid

    if vae_node_id is None or save_node_id is None:
        return workflow

    wf = dict(workflow)
    max_id = max(int(k) for k in wf.keys() if k.isdigit())
    load_id    = str(max_id + 1)
    reactor_id = str(max_id + 2)

    wf[load_id] = {"class_type": "LoadImage", "inputs": {"image": face_comfy_name}}
    wf[reactor_id] = {
        "class_type": "ReActorFaceSwap",
        "inputs": {
            # Required
            "enabled":                 True,
            "input_image":             [vae_node_id, 0],   # IMAGE from VAEDecode
            "swap_model":              swap_model,          # e.g. "inswapper_128.onnx"
            "facedetection":           "retinaface_resnet50",
            "face_restore_model":      restore_model,       # e.g. "codeformer-v0.1.0.pth"
            "face_restore_visibility": 1.0,
            "codeformer_weight":       0.3,   # lower = more identity, less correction
            "detect_gender_input":     "no",
            "detect_gender_source":    "no",
            "input_faces_index":       "0",
            "source_faces_index":      "0",
            "console_log_level":       1,
            # Optional — source_image is the reference face
            "source_image":            [load_id, 0],
        },
    }
    wf[save_node_id] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "mtg_card", "images": [reactor_id, 0]},
    }
    return wf


# ── ImageGen ──────────────────────────────────────────────────────────────────

class ImageGen:
    def __init__(self, comfy_base: str = "", checkpoint: Optional[str] = None,
                 model_speed: str = "quality", art_style: str = "mtg_fantasy"):
        """
        model_speed: "quality" → prefer flux-dev (slower, sharper)
                     "fast"    → prefer flux-schnell (4-8× faster, lower detail)
        art_style:   preset key from _LORA_PRESETS (e.g. "mtg_fantasy", "cyberpunk")
        """
        # Re-probe the port every time an ImageGen is created — handles the case
        # where ComfyUI was restarted between builds (port may change).
        if not comfy_base:
            comfy_base = _detect_comfy_base()
            print(f"  [image_gen] ComfyUI detected at: {comfy_base}")
        self.comfy_base  = comfy_base.rstrip("/")
        self.model_speed = model_speed
        self.art_style   = art_style if art_style in _LORA_PRESETS else "mtg_fantasy"
        self.checkpoint  = checkpoint or self._detect_checkpoint()
        self.available   = bool(self.checkpoint and self._check_server())

        # Face conditioning support
        self.face_method: str = "none"         # pulid_flux | ipadapter_faceid | reactor | none
        self.face_info:   dict = {}            # method-specific model names

        # LoRA art style support
        self.active_loras: list[dict] = []     # populated by _setup_loras()
        self.lora_trigger_prefix: str = ""     # trigger words prepended to every prompt
        self.theme_darkness: float = 1.0       # 0.0=light/whimsical → 1.0=dark/neutral
        self.active_flux_prefix: str = _FLUX_PREFIX   # overridden by _setup_loras()
        self.active_negative:    str = _FLUX_NEGATIVE # overridden by _setup_loras()

        if self.available:
            self._setup_face_method()
            self._setup_loras()

    # ── Checkpoint detection ──────────────────────────────────────────────────

    def _detect_checkpoint(self) -> Optional[str]:
        try:
            r = requests.get(f"{self.comfy_base}/object_info/CheckpointLoaderSimple", timeout=5)
            if r.status_code == 200:
                ckpts = (
                    r.json()
                    .get("CheckpointLoaderSimple", {})
                    .get("input", {}).get("required", {})
                    .get("ckpt_name", [[]])[0]
                )
                usable = [c for c in ckpts
                          if not _is_ltx(c) and not c.startswith("Unconfirmed")]
                if not usable:
                    return None

                flux    = [c for c in usable if _is_flux(c)]
                sd35    = [c for c in usable if _is_sd35(c)]
                schnell = [c for c in flux if "schnell" in c.lower()]
                dev     = [c for c in flux if "schnell" not in c.lower()]

                # model_speed routes to model family:
                #   "sd35"    → SD 3.5 Large (slower, different aesthetic)
                #   "fast"    → FLUX Schnell (4–8× faster than dev)
                #   "quality" → FLUX dev (default, highest detail)
                if self.model_speed == "sd35" and sd35:
                    return sd35[0]
                if self.model_speed == "fast":
                    return (schnell or dev or sd35 or usable)[0]
                # quality (default): prefer FLUX dev → schnell → SD3.5 → anything
                if flux:
                    return (dev or schnell)[0]
                return (sd35 or usable)[0]
        except requests.RequestException as e:
            print(f"  [image_gen] Checkpoint detection failed: {e}")
        return None

    @staticmethod
    def list_checkpoints(comfy_base: str = "") -> dict:
        """Return available checkpoints, split by variant. Used by the UI."""
        if not comfy_base:
            comfy_base = _detect_comfy_base()
        try:
            r = requests.get(f"{comfy_base.rstrip('/')}/object_info/CheckpointLoaderSimple", timeout=5)
            if r.status_code == 200:
                ckpts = (
                    r.json()
                    .get("CheckpointLoaderSimple", {})
                    .get("input", {}).get("required", {})
                    .get("ckpt_name", [[]])[0]
                )
                usable = [c for c in ckpts
                          if not _is_ltx(c) and not c.startswith("Unconfirmed")]
                flux    = [c for c in usable if _is_flux(c)]
                schnell = [c for c in flux if "schnell" in c.lower()]
                dev     = [c for c in flux if "schnell" not in c.lower()]
                sd35    = [c for c in usable if _is_sd35(c)]
                return {"dev": dev, "schnell": schnell, "sd35": sd35, "all": flux + sd35}
        except Exception:
            pass
        return {"dev": [], "schnell": [], "sd35": [], "all": []}

    def _check_server(self) -> bool:
        try:
            r = requests.get(f"{self.comfy_base}/system_stats", timeout=4)
            if r.status_code != 200:
                print(f"  [image_gen] ComfyUI returned {r.status_code}")
                return False
        except requests.RequestException as e:
            print(f"  [image_gen] ComfyUI not reachable: {e}")
            return False
        if not self.checkpoint:
            print(f"  [image_gen] No checkpoint detected")
            return False
        if _is_flux(self.checkpoint):
            kind = "FLUX"
        elif _is_sd35(self.checkpoint):
            kind = "SD3.5"
        else:
            kind = "SDXL"
        print(f"  [image_gen] ComfyUI ready — {kind} checkpoint: {self.checkpoint}")
        return True

    # ── Health check (used by server pre-flight before art gen) ────────────────

    @staticmethod
    def health_check(comfy_base: str = "") -> dict:
        """
        Quick standalone check of ComfyUI readiness — does NOT instantiate ImageGen
        or trigger any side effects.

        Returns a dict with:
          ok:         bool  — true if ComfyUI is up AND has a usable checkpoint
          reachable:  bool  — true if the HTTP endpoint responded at all
          has_ckpt:   bool  — true if at least one usable (non-LTX) checkpoint exists
          message:    str   — single-sentence human-readable status
          hint:       str   — actionable suggestion when ok=False ("" otherwise)
          base_url:   str   — the URL we probed
        """
        if not comfy_base:
            comfy_base = _detect_comfy_base()
        base = comfy_base.rstrip("/")
        out = {
            "ok": False, "reachable": False, "has_ckpt": False,
            "message": "", "hint": "", "base_url": base,
        }
        # 1. Reachability
        try:
            r = requests.get(f"{base}/system_stats", timeout=4)
        except requests.ConnectionError:
            out["message"] = f"ComfyUI is not running at {base}."
            out["hint"]    = "Start ComfyUI (e.g. run_nvidia_gpu.bat) and rebuild."
            return out
        except requests.Timeout:
            out["message"] = f"ComfyUI at {base} timed out responding to /system_stats."
            out["hint"]    = "ComfyUI may be stuck loading a model — wait or restart it."
            return out
        except requests.RequestException as e:
            out["message"] = f"ComfyUI connection error: {e}"
            out["hint"]    = "Check that ComfyUI is bound to 127.0.0.1:8188."
            return out

        if r.status_code != 200:
            out["message"] = f"ComfyUI returned HTTP {r.status_code} on /system_stats."
            out["hint"]    = "Restart ComfyUI — its API server may be in a bad state."
            return out
        out["reachable"] = True

        # 2. Checkpoint presence
        try:
            r2 = requests.get(f"{base}/object_info/CheckpointLoaderSimple", timeout=5)
            ckpts = (r2.json()
                     .get("CheckpointLoaderSimple", {})
                     .get("input", {}).get("required", {})
                     .get("ckpt_name", [[]])[0])
            usable = [c for c in ckpts
                      if not _is_ltx(c) and not c.startswith("Unconfirmed")]
        except Exception as e:
            out["message"] = f"ComfyUI is up but checkpoint listing failed: {e}"
            out["hint"]    = "Check ComfyUI's models/checkpoints folder."
            return out

        if not usable:
            out["message"] = "ComfyUI is up but no usable checkpoints are installed."
            out["hint"]    = "Place a FLUX checkpoint (e.g. flux1-dev-fp8.safetensors) in models/checkpoints/."
            return out
        out["has_ckpt"] = True

        out["ok"]      = True
        out["message"] = f"ComfyUI ready — {len(usable)} checkpoint(s) available."
        return out

    # ── Face-method detection ─────────────────────────────────────────────────

    def _get_available_nodes(self) -> set[str]:
        """Return set of all registered ComfyUI node class types."""
        try:
            r = requests.get(f"{self.comfy_base}/object_info", timeout=15)
            if r.status_code == 200:
                return set(r.json().keys())
        except Exception as e:
            print(f"  [image_gen] object_info query failed: {e}")
        return set()

    def _query_model_list(self, node_type: str, input_key: str) -> list[str]:
        """Ask ComfyUI for available models for a given node + input key."""
        try:
            r = requests.get(f"{self.comfy_base}/object_info/{node_type}", timeout=5)
            if r.status_code == 200:
                result = (
                    r.json()
                    .get(node_type, {})
                    .get("input", {}).get("required", {})
                    .get(input_key, [[]])[0]
                )
                if result:
                    return result
        except Exception:
            pass

        # Fallback: if ComfyUI returns empty, query file system directly
        # (happens when ComfyUI hasn't been restarted since LoRAs were added)
        if node_type == "LoraLoader" and input_key == "lora_name":
            return self._query_loras_from_disk()

        return []

    def _query_loras_from_disk(self) -> list[str]:
        """Fallback: scan the file system for LoRA files when ComfyUI's list is empty."""
        try:
            from pathlib import Path
            # Try common ComfyUI locations
            possible_paths = [
                Path(self.comfy_base or "").parent / "models" / "loras",
                Path.home() / "ComfyUI" / "models" / "loras",
                Path.cwd() / "ComfyUI" / "models" / "loras",
            ]
            for lora_dir in possible_paths:
                if lora_dir.exists():
                    loras = sorted([f.stem for f in lora_dir.glob("*.safetensors")])
                    if loras:
                        print(f"  [image_gen] LoRAs loaded from disk (ComfyUI list was empty): {loras}")
                        return loras
        except Exception as e:
            print(f"  [image_gen] Disk LoRA scan failed: {e}")
        return []

    def _setup_face_method(self) -> None:
        """Detect best available face-conditioning method and cache model names."""
        available_nodes = self._get_available_nodes()

        for method, required_nodes in _FACE_METHODS.items():
            if not all(n in available_nodes for n in required_nodes):
                continue

            # Method nodes are present — check models exist
            if method == "pulid_flux" and _is_flux(self.checkpoint):
                pulid_models = self._query_model_list("PulidModelLoader", "pulid_file")
                eva_models   = self._query_model_list("EVACLIPLoader",    "model_name")
                if pulid_models and eva_models:
                    # Pick EVA-CLIP: prefer one with "EVA02" in the name
                    eva = next((m for m in eva_models if "eva" in m.lower()), eva_models[0])
                    self.face_method = "pulid_flux"
                    self.face_info   = {"pulid": pulid_models[0], "eva_clip": eva}
                    print(f"  [image_gen] Face method: PuLID FLUX  "
                          f"({pulid_models[0]} + {eva})")
                    return

            elif method == "ipadapter_faceid" and not _is_flux(self.checkpoint) and not _is_sd35(self.checkpoint):
                # IPAdapter FaceID is SDXL-only — SD3.5 needs different models
                ipadapter_models = self._query_model_list("IPAdapterUnifiedLoader", "preset")
                if ipadapter_models or True:  # loader takes a preset string, not a model file
                    self.face_method = "ipadapter_faceid"
                    self.face_info   = {}
                    print("  [image_gen] Face method: IP-Adapter FaceID (SDXL)")
                    return

            elif method == "reactor":
                # Query available swap models and face restore models
                swap_models    = self._query_model_list("ReActorFaceSwap", "swap_model")
                restore_models = self._query_model_list("ReActorFaceSwap", "face_restore_model")

                # Prefer inswapper_128, fall back to first available
                swap = next(
                    (m for m in swap_models if "inswapper_128" in m.lower()),
                    swap_models[0] if swap_models else "inswapper_128.onnx",
                )
                # Prefer codeformer, then GFPGAN, then first available
                restore = next(
                    (m for m in restore_models if "codeformer" in m.lower()),
                    next(
                        (m for m in restore_models if "gfpgan" in m.lower()),
                        restore_models[0] if restore_models else "none",
                    ),
                )
                self.face_method = "reactor"
                self.face_info   = {"swap_model": swap, "restore_model": restore}
                print(f"  [image_gen] Face method: ReActor  "
                      f"(swap={swap}, restore={restore})")
                return

        print("  [image_gen] Face method: none (install PuLID/ReActor for face features)")

    # ── LoRA setup ────────────────────────────────────────────────────────────

    def _setup_loras(self) -> None:
        """
        Query ComfyUI for installed LoRAs and match them against the active
        preset's LoRA list.  Builds self.active_loras, self.lora_trigger_prefix,
        and self.active_flux_prefix.  FLUX only — SDXL skipped entirely.
        """
        _all = get_all_presets()
        preset = _all.get(self.art_style, _all.get("mtg_fantasy", next(iter(_all.values()))))

        # Set prompt prefix from preset (None → keep module default _FLUX_PREFIX)
        custom_prefix = preset.get("flux_prefix")
        if custom_prefix is not None:
            self.active_flux_prefix = custom_prefix

        # Per-preset negative prompt (None / "" → use module default _FLUX_NEGATIVE).
        # Anime, photorealism etc. need different negatives to keep FLUX's
        # photoreal prior from overpowering style-specific LoRAs.
        self.active_negative = preset.get("negative_prompt") or _FLUX_NEGATIVE

        style_label = preset["label"]
        print(f"  [image_gen] Art style: {style_label}")

        if not _is_flux(self.checkpoint or ""):
            return

        installed = self._query_model_list("LoraLoader", "lora_name")
        if not installed:
            return

        found: list[dict] = []
        missing_labels: list[str] = []
        for entry in preset["loras"]:
            frags = entry.get("fragments", [entry.get("fragment", "")])
            match = next(
                (f for f in installed
                 if any(frag.lower() in f.lower() for frag in frags)),
                None,
            )
            if match:
                found.append({**entry, "filename": match})
            else:
                missing_labels.append(entry["label"])

        if found:
            self.active_loras = found
            triggers = [e["trigger"] for e in found if e.get("trigger")]
            self.lora_trigger_prefix = ", ".join(triggers) + ". " if triggers else ""
            labels = [e["label"] for e in found]
            print(f"  [image_gen] LoRAs active ({len(found)}/{len(preset['loras'])}): "
                  f"{'; '.join(labels)}")
        if missing_labels:
            print(f"  [image_gen] LoRAs missing for '{style_label}': "
                  f"{missing_labels} — preset runs prompt-only for those.")

    # ── ComfyUI helpers ───────────────────────────────────────────────────────

    def upload_face_to_comfy(self, image_path: Path) -> Optional[str]:
        """
        Upload a local face image to ComfyUI's input directory.
        Returns the filename ComfyUI assigned (used in LoadImage nodes).
        """
        try:
            with image_path.open("rb") as f:
                r = requests.post(
                    f"{self.comfy_base}/upload/image",
                    files={"image": (image_path.name, f, "image/jpeg")},
                    data={"subfolder": "", "type": "input", "overwrite": "true"},
                    timeout=15,
                )
            if r.status_code == 200:
                name = r.json().get("name")
                print(f"  [image_gen] Uploaded face → ComfyUI input/{name}")
                return name
            else:
                print(f"  [image_gen] Face upload returned {r.status_code}")
        except Exception as e:
            print(f"  [image_gen] Face upload failed: {e}")
        return None

    def _queue_prompt(self, workflow: dict) -> str:
        try:
            r = requests.post(
                f"{self.comfy_base}/prompt",
                json={"prompt": workflow, "client_id": "mtg_deck_builder"},
                timeout=10,
            )
            # On 400 Bad Request ComfyUI returns a JSON body describing the actual
            # validation failure — surface it so we can diagnose missing LoRAs,
            # bad node inputs, etc. instead of just "400 Client Error".
            if r.status_code == 400:
                detail = _summarize_comfy_error(r)
                raise RuntimeError(f"ComfyUI rejected workflow (400): {detail}")
            r.raise_for_status()
            resp_json = r.json()
            prompt_id = resp_json.get("prompt_id")
            if not prompt_id:
                raise ValueError(f"No prompt_id in response: {resp_json}")
            return prompt_id
        except requests.ConnectionError as e:
            raise ConnectionError(
                f"Cannot reach ComfyUI at {self.comfy_base} — is it running?"
            ) from e
        except requests.Timeout as e:
            raise TimeoutError(
                f"ComfyUI at {self.comfy_base} timed out — it may be stuck or overloaded."
            ) from e
        except Exception as e:
            print(f"  [image_gen] _queue_prompt failed: {e}")
            raise

    def _wait_for_image(self, prompt_id: str, cancel_event=None) -> Optional[dict]:
        deadline   = time.monotonic() + OUTPUT_TIMEOUT
        start_time = time.monotonic()
        poll_count = 0
        last_status_str = None

        while time.monotonic() < deadline:
            # Check cancel event before sleeping
            if cancel_event is not None and cancel_event.is_set():
                print(f"  [image_gen] Cancel requested — interrupting ComfyUI prompt {prompt_id}")
                try:
                    # Send interrupt to ComfyUI to stop the current generation
                    requests.post(f"{self.comfy_base}/interrupt", timeout=5)
                except Exception as e:
                    print(f"  [image_gen] Interrupt request failed: {e}")
                return None

            time.sleep(POLL_INTERVAL)
            poll_count += 1
            try:
                r = requests.get(f"{self.comfy_base}/history/{prompt_id}", timeout=5)
            except requests.RequestException as e:
                print(f"  [image_gen] Poll {poll_count} network error: {e}")
                continue
            if r.status_code != 200:
                print(f"  [image_gen] Poll {poll_count}: history returned {r.status_code}")
                continue

            history = r.json()
            if prompt_id not in history:
                # Job still queued/running — log queue depth every ~60s
                if poll_count % 30 == 0:
                    elapsed = time.monotonic() - start_time
                    try:
                        q = requests.get(f"{self.comfy_base}/queue", timeout=5).json()
                        running = len(q.get("queue_running", []))
                        pending = len(q.get("queue_pending", []))
                        print(f"  [image_gen] [{elapsed:.0f}s] still queued — "
                              f"ComfyUI queue: {running} running, {pending} pending")
                    except Exception:
                        print(f"  [image_gen] [{elapsed:.0f}s] still queued (queue check failed)")
                continue

            entry      = history[prompt_id]
            status     = entry.get("status", {})
            status_str = status.get("status_str", "unknown")
            completed  = status.get("completed", False)
            elapsed    = time.monotonic() - start_time

            # Log status transitions so we know what ComfyUI is doing
            if status_str != last_status_str:
                print(f"  [image_gen] [{elapsed:.1f}s] ComfyUI status → {status_str!r}")
                last_status_str = status_str

            # ── Detect ComfyUI execution errors ──────────────────────────────
            # When a node fails (OOM, missing LoRA, bad input…) ComfyUI marks
            # status_str = "error" and embeds the reason in status["messages"].
            # NOTE: completed may be False on some errors (e.g. comfy_aimdo
            # VRAMBuffer crash) — check status_str alone, not completed+status_str.
            if status_str in ("error", "failed"):
                messages = status.get("messages", [])
                for msg in messages:
                    if not (isinstance(msg, (list, tuple)) and len(msg) >= 2):
                        continue
                    kind, data = msg[0], msg[1]
                    if kind == "execution_error" and isinstance(data, dict):
                        node_id   = data.get("node_id",   "?")
                        node_type = data.get("node_type", "?")
                        exc_type  = data.get("exception_type",    "")
                        exc_msg   = data.get("exception_message", "unknown error")
                        traceback_lines = data.get("traceback", [])
                        tb_tail = "".join(traceback_lines[-5:]) if traceback_lines else ""
                        print(
                            f"  [image_gen] EXECUTION ERROR in node {node_id} "
                            f"({node_type}): [{exc_type}] {exc_msg}"
                        )
                        if tb_tail:
                            print(f"  [image_gen] traceback tail:\n{tb_tail}")
                if not any(
                    isinstance(m, (list, tuple)) and len(m) >= 2 and m[0] == "execution_error"
                    for m in messages
                ):
                    print(f"  [image_gen] ComfyUI reports {status_str!r} — "
                          f"messages: {messages[:5]}")
                return None   # failed — don't wait out the full timeout

            # ── Check for output images ───────────────────────────────────────
            outputs = entry.get("outputs", {})
            for node_out in outputs.values():
                if node_out.get("images"):
                    print(f"  [image_gen] Image ready after {elapsed:.1f}s "
                          f"({poll_count} polls)")
                    return node_out["images"][0]

            # Job is in history but no outputs yet — still executing
            if completed and not outputs:
                # Completed with no output and no error — unusual, log it
                print(f"  [image_gen] [{elapsed:.1f}s] completed but no outputs? "
                      f"status={status_str!r}  outputs_keys={list(entry.get('outputs',{}).keys())}")

        elapsed = time.monotonic() - start_time
        print(f"  [image_gen] Timeout after {elapsed:.1f}s waiting for {prompt_id}")
        return None

    def _download_image(self, image_info: dict, save_path: Path) -> bool:
        try:
            r = requests.get(
                f"{self.comfy_base}/view",
                params={
                    "filename":  image_info["filename"],
                    "subfolder": image_info.get("subfolder", ""),
                    "type":      image_info.get("type", "output"),
                },
                timeout=30,
            )
            if r.status_code == 200:
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(r.content)
                return True
            print(f"    [_download_image] GET /view returned {r.status_code}")
        except Exception as e:
            print(f"    [_download_image] Exception: {e}")
        return False

    # ── Public generation interface ───────────────────────────────────────────

    def generate(
        self,
        art_prompt:    str,
        filename_stem: str,
        face_comfy_name: Optional[str] = None,   # already-uploaded ComfyUI filename
        face_gender:   str = "either",            # "male", "female", or "either"
        cancel_event=None,                        # threading.Event — set to stop generation mid-run
    ) -> Optional[Path]:
        if not self.available:
            return None

        save_path = Path(f"{filename_stem}.png")
        if save_path.exists():
            return save_path

        seed   = random.randint(0, 2**32 - 1)
        prefix = self.active_flux_prefix if _is_flux(self.checkpoint) else _SDXL_PREFIX

        # LoRA trigger words prepended first so CLIP weights them most heavily.
        # self.lora_trigger_prefix is "" when no MTG art LoRAs are installed.
        lora_prefix = self.lora_trigger_prefix

        # Face-conditioned cards must show a clear human face for ReActor/PuLID
        # to work with. We prepend a strong humanoid portrait directive so the
        # model always generates a human character regardless of what the themer
        # described (commanders can be dragons, krakens, etc. — we override that
        # for the generated portrait so the face swap has something to land on).
        #
        # The medium word ("Painted", "Photorealistic", "Anime illustration") is
        # pulled from the active preset via face_prefix_medium.  Using the wrong
        # medium here (e.g. "Painted portrait" for a Photorealism preset) creates
        # a direct contradiction that causes FLUX to produce spiral/swirl artifacts.
        face_prefix = ""
        if face_comfy_name:
            _all_presets  = get_all_presets()
            _active_preset = _all_presets.get(self.art_style, {})
            _fp_medium  = _active_preset.get("face_prefix_medium",  "Painted portrait")
            _fp_quality = _active_preset.get("face_prefix_quality", "painterly skin tones")

            if face_gender == "male":
                _fp_subject = "of a man"
            elif face_gender == "female":
                _fp_subject = "of a woman"
            else:
                _fp_subject = "of a person"

            face_prefix = (
                f"{_fp_medium} {_fp_subject}, face clearly visible and well-lit, "
                f"detailed expressive eyes, {_fp_quality}. "
            )

        full_prompt = lora_prefix + prefix + face_prefix + art_prompt

        # ReActor needs a detectable face in the generated image to swap onto.
        # Append a frontal-face nudge so the subject is facing forward enough
        # for retinaface_resnet50 to pick up on.
        if face_comfy_name and self.face_method == "reactor":
            full_prompt += ", face and upper body visible, three-quarter view toward camera, subject looking forward"

        # Log the final prompt and settings so we can diagnose blurriness/LoRA issues
        print(f"  [image_gen] Prompt ({len(full_prompt)} chars): {full_prompt[:120]}{'...' if len(full_prompt) > 120 else ''}")
        print(f"  [image_gen] Negative ({len(self.active_negative)} chars): {self.active_negative[:100]}...")
        print(f"  [image_gen] Theme darkness: {self.theme_darkness:.2f}, LoRAs: {len(self.active_loras) if self.active_loras else 0}")

        # Build workflow — face-conditioned if we have a reference.
        # Pass the preset-specific negative so anime / photorealism etc. can
        # actively push against FLUX's default photoreal prior.
        if face_comfy_name and self.face_method != "none":
            workflow = self._build_face_workflow(full_prompt, seed, face_comfy_name)
        else:
            workflow = _build_workflow(self.checkpoint, full_prompt, seed,
                                       negative=self.active_negative)

        # Insert LoRA nodes into workflow (chains model + clip through each LoRA).
        # Dark-only LoRAs have their strength scaled by self.theme_darkness so
        # light/whimsical themes aren't dragged into grim dark-fantasy territory.
        if self.active_loras and _is_flux(self.checkpoint):
            scaled: list[dict] = []
            for entry in self.active_loras:
                if entry.get("dark_only") and self.theme_darkness < 1.0:
                    scaled.append({
                        **entry,
                        "model_strength": round(entry["model_strength"] * self.theme_darkness, 3),
                        "clip_strength":  round(entry["clip_strength"]  * self.theme_darkness, 3),
                    })
                else:
                    scaled.append(entry)
            # Checkpoint node is always "1" in FLUX workflows (standard and PuLID)
            workflow = _insert_loras(workflow, "1", scaled)

        try:
            # Log LoRA chain so we can spot missing/wrong filenames immediately
            lora_nodes = {nid: n for nid, n in workflow.items()
                          if n.get("class_type") == "LoraLoader"}
            if lora_nodes:
                for nid, n in lora_nodes.items():
                    inp = n.get("inputs", {})
                    print(f"  [image_gen] LoRA node {nid}: {inp.get('lora_name')}  "
                          f"model={inp.get('strength_model')} clip={inp.get('strength_clip')}")

            prompt_id  = self._queue_prompt(workflow)
            print(f"  [image_gen] Queued {prompt_id} (face={'yes' if face_comfy_name else 'no'}), waiting...")
            image_info = self._wait_for_image(prompt_id, cancel_event=cancel_event)
            if not image_info:
                return None
            if self._download_image(image_info, save_path):
                return save_path
        except requests.RequestException as e:
            print(f"  [image_gen] RequestException '{filename_stem}': {e}")
        except Exception as e:
            print(f"  [image_gen] Unexpected error '{filename_stem}': {e}")
        return None

    def _build_face_workflow(self, positive: str, seed: int, face_comfy_name: str) -> dict:
        """Select and build the best available face-conditioned workflow."""
        neg = self.active_negative
        if self.face_method == "pulid_flux":
            return _build_pulid_flux_workflow(
                self.checkpoint, positive, seed, face_comfy_name,
                self.face_info["pulid"], self.face_info["eva_clip"],
                negative=neg,
            )
        if self.face_method == "ipadapter_faceid":
            return _build_faceid_sdxl_workflow(
                self.checkpoint, positive, seed, face_comfy_name,
                "", "",  # preset-based, no explicit model file paths needed
            )
        if self.face_method == "reactor":
            base = _build_workflow(self.checkpoint, positive, seed, negative=neg)
            return _append_reactor(
                base, face_comfy_name,
                swap_model=self.face_info.get("swap_model", "inswapper_128.onnx"),
                restore_model=self.face_info.get("restore_model", "codeformer-v0.1.0.pth"),
            )
        # Should not reach here
        return _build_workflow(self.checkpoint, positive, seed, negative=neg)

    def generate_deck(
        self,
        themed_commander,
        themed_deck: list,
        deck_name: str,
        face_paths: Optional[list[Path]] = None,   # commander face photos (1 person)
        crew_paths: Optional[list[Path]] = None,   # crew photos (multiple people for creature cards)
        face_gender: str = "either",               # gender hint for commander face
        crew_gender: str = "either",               # gender hint for crew faces
        progress_callback=None,                    # callable(i, total, name, has_face, elapsed, success)
        theme_str: str = "",                       # human-readable theme for LoRA darkness scaling
        card_done_callback=None,                   # callable(tc, art_path) — called after each card renders
        cancel_event=None,                         # threading.Event — set to stop mid-run
    ) -> dict[str, Optional[Path]]:
        if not self.available:
            return {}

        # Compute theme darkness once for the whole deck.
        hint = (theme_str or
                (themed_deck[0].art_prompt if themed_deck else "") or
                deck_name)
        self.theme_darkness = _theme_darkness_score(hint)
        if self.theme_darkness < 0.85:
            dark_entries = [e["label"] for e in self.active_loras if e.get("dark_only")]
            if dark_entries:
                print(f"  [image_gen] Light theme detected (darkness={self.theme_darkness:.2f}) — "
                      f"scaling dark LoRAs: {dark_entries}")

        # ── Upload commander face reference (used ONLY for the commander card) ─
        face_comfy_name: Optional[str] = None
        if face_paths and self.face_method != "none":
            face_comfy_name = self.upload_face_to_comfy(face_paths[0])
            if not face_comfy_name:
                print("  [image_gen] Commander face upload failed — generating without face conditioning")
            else:
                print(f"  [image_gen] Commander face uploaded: {face_comfy_name}")

        # ── Upload ALL crew photos (distributed round-robin across creature cards) ─
        # Each photo in crew_paths represents a different person.
        # Humanoid creature cards cycle through the crew photos in order.
        crew_comfy_names: list[str] = []
        if crew_paths and self.face_method != "none":
            for cp in crew_paths:
                n = self.upload_face_to_comfy(cp)
                if n:
                    crew_comfy_names.append(n)
            if crew_comfy_names:
                print(f"  [image_gen] Crew faces uploaded: {len(crew_comfy_names)}/{len(crew_paths)} photos")
            else:
                print("  [image_gen] All crew photo uploads failed — generating creatures without crew faces")

        # Deduplicate cards.
        # Commander is always included even if art_prompt is empty — we give it
        # a name-based fallback so is_cmd is always bound to the right card in
        # the queue and face conditioning is never accidentally applied to the
        # wrong card.
        all_cards = [themed_commander] + themed_deck
        seen: set[str] = set()
        queue = []
        for tc in all_cards:
            if tc.original_name in seen:
                continue
            seen.add(tc.original_name)
            is_cmd_card = (tc.original_name == themed_commander.original_name)
            if tc.art_prompt:
                queue.append(tc)
            elif is_cmd_card:
                # Commander has no prompt — use card name as minimal fallback
                # rather than skipping it (which would misassign face conditioning)
                from themer import ThemedCard as _TC
                queue.append(_TC(
                    original_name=tc.original_name,
                    themed_name=tc.themed_name,
                    art_prompt=tc.original_name,
                    flavor_text=tc.flavor_text,
                    card=tc.card,
                ))
            # non-commander cards with no prompt are silently skipped (unchanged)

        total = len(queue)
        if _is_flux(self.checkpoint):
            kind = "FLUX"
        elif _is_sd35(self.checkpoint):
            kind = "SD3.5"
        else:
            kind = "SDXL"
        tags     = []
        if face_comfy_name:   tags.append(f"cmd-face:{self.face_method}")
        if crew_comfy_names:  tags.append(f"crew:{len(crew_comfy_names)} photos")
        face_tag = (" + " + ", ".join(tags)) if tags else ""
        # Per-card timing estimate: schnell ~6s, SD3.5 ~30s, FLUX dev ~35s
        if "schnell" in self.checkpoint.lower():
            secs_each = 6
        elif _is_sd35(self.checkpoint):
            secs_each = 30
        else:
            secs_each = 35
        print(f"\n  Generating art for {total} cards via {kind}{face_tag} "
              f"(~{total * secs_each // 60}–{total * secs_each * 2 // 60} min)...")

        from face_ref import is_human_card

        results: dict[str, Optional[Path]] = {}
        art_dir = Path("generated_art") / deck_name
        crew_card_idx = 0   # round-robin index into crew_comfy_names

        for i, tc in enumerate(queue, 1):
            if cancel_event is not None and cancel_event.is_set():
                print(f"  [image_gen] Cancelled after {i - 1}/{total} cards.")
                break

            safe = "".join(c if c.isalnum() or c == "_" else "_" for c in tc.original_name)[:48]
            out  = art_dir / safe

            is_cmd = (tc.original_name == themed_commander.original_name)

            # ── Assign face reference for this card ───────────────────────────
            # Commander → always uses commander face (if provided)
            # Humanoid creatures → round-robin through crew photos (if provided)
            # Everything else → no face conditioning
            card_face_name:   Optional[str] = None
            card_face_gender: str           = "either"

            if is_cmd and face_comfy_name:
                card_face_name   = face_comfy_name
                card_face_gender = face_gender
                face_tag_card    = "[👑]"
            elif not is_cmd and crew_comfy_names and is_human_card(tc.card.get("type_line", "")):
                card_face_name   = crew_comfy_names[crew_card_idx % len(crew_comfy_names)]
                card_face_gender = crew_gender
                crew_card_idx   += 1
                face_tag_card    = f"[👥{(crew_card_idx - 1) % len(crew_comfy_names) + 1}]"
            else:
                face_tag_card = "    "

            print(f"  [{i:>3}/{total}] {face_tag_card} {tc.themed_name:<33}", end=" ", flush=True)

            t0   = time.monotonic()
            path = self.generate(
                tc.art_prompt, str(out),
                face_comfy_name=card_face_name,
                face_gender=card_face_gender,
                cancel_event=cancel_event,
            )
            elapsed = time.monotonic() - t0
            results[tc.original_name] = path
            print(f"{'OK' if path else 'FAIL'}  {elapsed:.0f}s")
            if card_done_callback and path:
                try:
                    card_done_callback(tc, path)
                except Exception as _cdc_err:
                    print(f"  [image_gen] card_done_callback error: {_cdc_err}")
            if progress_callback:
                try:
                    progress_callback(i, total, tc.themed_name,
                                      card_face_name is not None, elapsed, path is not None)
                except Exception:
                    pass

        done = sum(1 for v in results.values() if v)
        print(f"\n  Art: {done}/{total} images saved to {art_dir}/")
        return results

    @property
    def face_method_label(self) -> str:
        return {
            "pulid_flux":       "PuLID FLUX (high quality)",
            "ipadapter_faceid": "IP-Adapter FaceID (SDXL)",
            "reactor":          "ReActor face swap",
            "none":             "not available",
        }.get(self.face_method, "unknown")
