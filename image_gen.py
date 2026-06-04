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

    3. shakker_dark_fantasy.safetensors   (~38 MB,  strength 0.65, no trigger needed)
       ALREADY DOWNLOADED — Shakker-Labs dark fantasy atmospheric lighting.

  Combined model strength sum ≈ 2.00 — within safe range for FLUX multi-LoRA stacking.

Sampler notes (community-tested FLUX dev, 2025):
  euler + beta   — NOT recommended together (beta only shines paired with deis).
  dpm++_2m + sgm_uniform — sharpest detail, best for illustration/concept art.
  deis + beta    — high contrast cinematic look, also excellent for MTG scenes.
  Dev default:     dpm++_2m + sgm_uniform, 28 steps, CFG 3.5, 1152x768.
  Schnell default: euler + simple,          8 steps, CFG 1.0, 1152x768 (no LoRAs — dev-trained).
"""
from __future__ import annotations

import io
import json
import random
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import requests

# On Windows the default console encoding is cp1252 which can't represent many
# Unicode characters that appear in art prompts and log messages (—, …, ⚠, etc.).
# Wrap stdout/stderr with UTF-8 so print() never raises UnicodeEncodeError.
# Always rewrap if errors != "replace" so we get lossless fallback even if uvicorn
# has already set encoding=utf-8 but without the errors= safety net.
def _ensure_utf8_stdout() -> None:
    for _attr in ("stdout", "stderr"):
        _stream = getattr(sys, _attr, None)
        if _stream is None:
            continue
        _enc = getattr(_stream, "encoding", "") or ""
        _err = getattr(_stream, "errors",   "") or ""
        if hasattr(_stream, "buffer") and (
            _enc.lower().replace("-", "") != "utf8" or _err != "replace"
        ):
            setattr(sys, _attr,
                    io.TextIOWrapper(_stream.buffer, encoding="utf-8", errors="replace"))

_ensure_utf8_stdout()

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


# ── User-configurable generation settings ─────────────────────────────────────
# Single source of truth for the knobs the frontend "Advanced" panels expose.
# Defaults here MUST match frontend/src/config/genSettings.js.  Threaded through
# ImageGen → workflow builders; absent/None fields fall back to model defaults so
# existing behavior is unchanged when the UI sends nothing.
@dataclass
class GenSettings:
    # FLUX sampler controls (dev only; schnell ignores guidance)
    guidance:   float          = 3.5     # FluxGuidance value (1.5–5)
    steps:      Optional[int]  = None     # None → 28 dev / 8 schnell
    sampler:    Optional[str]  = None     # None → dpmpp_2m dev / euler schnell
    scheduler:  Optional[str]  = None     # None → sgm_uniform dev / simple schnell
    # Seed
    seed_mode:  str            = "random"  # "random" | "fixed"
    seed:       Optional[int]  = None      # used when seed_mode == "fixed"
    # LoRA selection/strength overrides (list of {filename, model_strength, clip_strength?})
    # None → use the art-style preset's default LoRA stack.
    lora_overrides: Optional[list] = None
    # Face conditioning
    face_method: Optional[str] = None      # None=auto | "reactor" | "pulid_flux" | "none"
    face_weight: Optional[float] = None    # PuLID identity weight (0.5–1.0)
    # Stability
    safe_mode:  bool           = False     # lower steps + resolution to reduce crash load

    # Resolved generation resolution (set by ImageGen based on safe_mode)
    width:      int            = CARD_WIDTH
    height:     int            = CARD_HEIGHT

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "GenSettings":
        """Build from an arbitrary dict, ignoring unknown keys and bad types."""
        gs = cls()
        if not d:
            return gs
        for k, v in d.items():
            if k in cls.__dataclass_fields__ and v is not None:
                setattr(gs, k, v)
        return gs

    def resolved(self) -> dict:
        """A flat dict for logging."""
        return asdict(self)

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
    # First-person / POV prevention
    "first person view, first-person perspective, pov shot, first person pov, "
    "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
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
    "watermark, text, border, card frame, out of frame, cropped, nsfw, "
    # Face-swap artifact guards (prevents 2 torches + black background syndrome)
    "floating head, headless, no body, face only, torso only, incomplete character, "
    "looking away, facing away, back turned, no face visible, face hidden, "
    "empty black background, void, featureless background, blank background, "
    # First-person / POV prevention — FLUX tends toward POV hands when prompts mention wielding/casting
    "first person view, first-person perspective, pov shot, first person pov, "
    "hands in foreground, foreground hands, player pov, viewer pov, point of view shot"
)

# ── Positive prompt prefixes ───────────────────────────────────────────────────
# SDXL responds well to comma-separated quality tags at high CFG
_SDXL_PREFIX = (
    "masterpiece, best quality, highly detailed, sharp focus, "
    "professional fantasy illustration, artstation trending, concept art, "
    "cinematic lighting, dramatic shadows, rich color palette, "
    "third-person view, character viewed from outside, landscape composition, wide shot, subject fully in frame, no cropping, "
    "anatomically correct hands, five fingers on each hand, "
)

# FLUX needs strong explicit style anchors to avoid defaulting to photorealism.
# Lead with the medium ("digital painting") before any subject description so
# the style token is weighted highest by CLIP attention.
_FLUX_PREFIX = (
    "Digital painting, fantasy illustration, concept art. "
    "Painterly brushwork, rich textured surface, highly detailed. "
    "Vivid saturated colors, cinematic lighting, dramatic shadows. "
    "Third-person view, character viewed from outside. Landscape composition. "
    "Any visible hands have exactly five fingers each. "
)

# ── Style/trigger de-duplication ──────────────────────────────────────────────
# When the user's theme already names the style (e.g. theme "neon cyberpunk rave"
# with the cyberpunk preset), the injected LoRA trigger prefix + style flux_prefix
# repeat words like "cyberpunk" two or three times. CLIP then over-weights the
# style and the LoRA "takes over", drowning out the per-card mana-colour palette.
# These helpers strip style words from the INJECTED prefixes when those words are
# already present in the user's prompt — the user's wording (and colours) win,
# the style is stated once. LoRA *trigger tokens* (e.g. "kcyberpunk") are unique
# and not affected, so the LoRA still activates.

_DEDUP_STOPWORDS = {
    "digital", "painting", "concept art", "style", "illustration", "highly",
    "detailed", "scene", "image", "card", "with", "and", "the", "view",
    "composition", "lighting", "colors", "color", "background",
}


def _prompt_word_set(text: str) -> set:
    """Significant lowercased words in `text` (len ≥ 5, not a stopword)."""
    return {
        w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]+", text)
        if len(w) >= 5 and w.lower() not in _DEDUP_STOPWORDS
    }


def _tidy_prompt(text: str) -> str:
    """Clean up punctuation/whitespace left after removing words."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;])", r"\1", text)     # space before punct
    text = re.sub(r"([,.;])(\s*[,.;])+", r"\1", text)  # collapsed runs of punct
    text = re.sub(r"(^|[.;])\s*,", r"\1", text)   # stray leading comma
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" ,;")


def _strip_trigger_prefix(lora_prefix: str, prompt_words: set) -> str:
    """Drop whole LoRA trigger tokens that already appear as words in the prompt.

    The prefix looks like ``"trigA, trig B. "``. A trigger is dropped only when
    *all* of its words are already in the prompt (so unique codes like
    "kcyberpunk" — which never appear in user prompts — are always kept)."""
    if not lora_prefix.strip():
        return lora_prefix
    body = lora_prefix.rstrip()
    trailing = "." if body.endswith(".") else ""
    body = body.rstrip(".")
    kept = []
    for trig in [t.strip() for t in body.split(",") if t.strip()]:
        words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z\-]+", trig)]
        if words and all(w in prompt_words for w in words):
            continue   # fully redundant with the user's prompt
        kept.append(trig)
    if not kept:
        return ""
    return ", ".join(kept) + (trailing or ".") + " "


def _dedup_style_words(flux_prefix: str, prompt_words: set) -> str:
    """Remove significant style words from the flux_prefix that the prompt already
    states, so the style concept isn't double-weighted."""
    if not flux_prefix.strip():
        return flux_prefix

    def repl(m):
        return "" if m.group(0).lower() in prompt_words else m.group(0)

    return _tidy_prompt(re.sub(r"[A-Za-z][A-Za-z\-]+", repl, flux_prefix)) + " "


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
                "clip_strength":  0.55,
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
                "fragments":      ["shakker"],
                "trigger":        "",
                "model_strength": 0.65,
                "clip_strength":  0.5,
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
        "themer_medium":     '"cinematic photograph," or "professional photograph," or "detailed photorealistic scene,"',
        "themer_quality":    '"sharp focus, photorealistic detail, realistic materials" or "film-quality, vivid colors, natural lighting" or "detailed textures, lifelike appearance"',
        # flux_prefix: lead with BRIGHT natural light sources so FLUX doesn't
        # default to underexposed dark output.  "cinematic photography" alone at
        # low CFG can produce near-black frames — anchor on warm volumetric light
        # first, then the style and quality terms.
        "flux_prefix": (
            "Professional photographic quality. Sharp focus, vivid colors, realistic details. "
            "Well-lit with natural lighting, no dark underexposed areas. Realistic textures and materials. "
            "Third-person view, character viewed from outside. "
        ),
        # face_prefix_medium: overrides the "Painted portrait" default used in
        # generate() for face-conditioned cards.  Must NOT specify "Painted" here —
        # that word directly contradicts the photorealistic style and causes FLUX
        # to produce spiral/contradiction artifacts.
        "face_prefix_medium": "Photorealistic photograph, close-up portrait, detailed skin texture, professional studio lighting",
        "face_prefix_quality": "sharp photorealistic skin detail, natural lighting on face",
        # Custom negative for photorealism: the default _FLUX_NEGATIVE explicitly
        # lists "photograph, photo, photorealistic, hyperrealistic, camera, DSLR"
        # as negatives — which directly contradicts this preset's entire purpose.
        # This override removes those terms and instead pushes against underexposure
        # and flat/washed output that FLUX can produce without a realism LoRA.
        "negative_prompt": (
            "bad hands, extra fingers, wrong number of fingers, malformed hands, "
            "bad anatomy, deformed, twisted, distorted, "
            "first person view, first-person perspective, pov shot, first person pov, "
            "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
            "blurry, out of focus, soft focus, hazy, foggy, low resolution, noise, grain, "
            "underexposed, too dark, pitch black, barely visible, muddy dark colors, "
            "flat lighting, harsh shadows, overexposed, washed out, blown highlights, "
            "cartoon, anime, illustration, painting, sketch, drawing, digital art, 3d render, cgi, "
            "filter effects, artistic style, stylized, unrealistic, fantasy, magical effects, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
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
        # Quality tag is COLOR-NEUTRAL on purpose: it must not inject "neon /
        # electric / vivid" hues, or every card's palette collapses to generic
        # neon and the per-card mana / theme colors (col 5) are ignored. Keep
        # luminosity + detail words only; the actual hue comes from col 5.
        "themer_quality":    '"glowing illumination, high detail" or "luminous light, sharp focus" or "painterly, cinematic lighting"',
        # flux_prefix: lead with BRIGHT glowing neon light sources so FLUX doesn't
        # default to near-black.  "vivid neon palette against deep shadows" was the
        # old wording — FLUX over-weighted "deep shadows" and generated near-black
        # frames.  Now we anchor on luminosity first, then add dark atmosphere second.
        # NOTE: palette and exact framing are intentionally NOT specified here.
        # Color is driven per-card by the themer from each card's mana identity
        # (_color_palette_hint), and composition variety comes from the themer's
        # per-card scene descriptions.  This prefix only anchors MEDIUM + LUMINOSITY
        # (to keep FLUX well-exposed — see the cfg/FluxGuidance fix) + card-suitable
        # orientation.  Baking "electric magenta, cyan, deep blue" and "subject fully
        # centered" here was overriding the per-card palette and flattening every
        # card into the same look.
        "flux_prefix": (
            "Digital painting, cyberpunk concept art. "
            "Bright neon-lit illumination, luminous glowing light sources, well-lit scene. "
            "Chrome and glass architecture, holographic overlays, retrofuturistic technology. "
            "High detail, sharp focus. "
            "Third-person view, character viewed from outside, landscape composition. "
            "Any visible hands have exactly five fingers each. "
        ),
        # Cyberpunk-specific negative: push FLUX away from near-black underexposure.
        # Without this the model happily makes the whole scene black and dots a
        # few neon pixels in, which reads as 'deep shadows' but looks like a failure.
        "negative_prompt": (
            "bad hands, extra fingers, four fingers, three fingers, wrong number of fingers, "
            "bad anatomy, deformed, ugly, "
            "first person view, first-person perspective, pov shot, first person pov, "
            "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
            "underexposed, too dark, pitch black, barely visible, muddy dark, dark muddy colors, "
            "dark background, all black, completely black, near black, "
            "overexposed, washed out, blown out, pure white, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        # LoRA notes: both are dim=2 / alpha=16 FLUX LoRAs (alpha/rank ≈ 8 → potent
        # even at modest strength), trained with text_encoder_lr=0, so they are
        # UNET-only and clip_strength patches nothing (left at 0).
        #
        # "Neon Noir" (mad-neon-noir) is a SUBJECT/SCENE LoRA, not a pure style one:
        # it was trained on 1940s-noir people (tags: street, alley, bar, man, woman,
        # trenchcoat) and at any meaningful strength it overrides the card's actual
        # character — turning every commander into a fedora-and-trenchcoat detective
        # regardless of the prompt (confirmed by A/B testing: it still imposed the
        # trenchcoat even at strength 0.25).  So it is intentionally NOT in the
        # active stack.  "Cyberpunk Detailer" carries the neon-cyberpunk aesthetic
        # (cyber-armor, augments, neon detail) while respecting the described subject,
        # so it leads at 0.55.  To re-introduce a noir mood, add Neon Noir back at a
        # LOW strength (≤0.2) and expect some loss of subject fidelity.
        "loras": [
            # PRIMARY style LoRA: Cyberpunk CG (kcyberpunk).  Genuine flux-1-dev,
            # dim16/alpha16 (scale 1.0 — well-behaved), trained as a STYLE on
            # cyberpunk CG scenes & characters.  Unlike Neon Noir it does NOT hijack
            # the subject (verified: a gold/crimson armored knight stayed an armored
            # knight, fully neon-styled).  Recommended weight 0.6–0.8.
            {
                "fragments":      ["kcyberpunk", "cyberpunk_cg", "cyberpunkcg"],
                "trigger":        "kcyberpunk",
                "model_strength": 0.7,
                "clip_strength":  0.0,
                "dark_only":      False,
                "label":          "Cyberpunk CG",
                "download_url":   "https://civitai.com/models/1248843",
                "download_note":  "kcyberpunk-02.safetensors (FLUX.1 D)",
            },
            # SECONDARY detail layer: adds cyber-augment / neon detail without
            # dictating the subject.  Kept moderate so it complements, not competes.
            {
                "fragments":      ["cyberpunk_detailer", "cbrpnk", "Neon_Cyberpunk_Detailer"],
                "trigger":        "mad-cbrpnk-dtlr",
                "model_strength": 0.4,
                "clip_strength":  0.0,
                "dark_only":      False,
                "label":          "Cyberpunk Detailer",
                "download_url":   "https://civitai.com/models/730615",
                "download_note":  "Neon_Cyberpunk_Detailer_FLUX_multi_trigger.safetensors",
            },
        ],
        # Per-card rotation: each card randomly uses one of these two style stacks
        # for stylistic variety across a deck (CG-realism vs vaporwave neon mood).
        # Both are clean flux-1-dev STYLE LoRAs that respect the subject.
        "lora_rotation": [
            {
                "label": "Cyberpunk CG",
                "loras": [
                    {"fragments": ["kcyberpunk", "cyberpunk_cg"], "trigger": "kcyberpunk",
                     "model_strength": 0.7, "clip_strength": 0.0, "dark_only": False, "label": "Cyberpunk CG"},
                    {"fragments": ["cyberpunk_detailer", "cbrpnk", "Neon_Cyberpunk_Detailer"], "trigger": "mad-cbrpnk-dtlr",
                     "model_strength": 0.4, "clip_strength": 0.0, "dark_only": False, "label": "Cyberpunk Detailer"},
                ],
            },
            {
                "label": "Neon Abyss",
                "loras": [
                    # bo-neon trained its text encoder (has lora_te keys), so clip_strength
                    # patches the COLOR conditioning. At 0.85 it overrode the prompt's
                    # palette and forced magenta/cyan neon onto every card regardless of
                    # the mana/theme colors. Lowered clip to 0.45 (and model to 0.75) so
                    # the neon STYLE survives but the per-card green/black palette shows.
                    {"fragments": ["boFLUX_Abyss_Neon", "abyss_neon", "bo-neon", "boflux"], "trigger": "bo-neon",
                     "model_strength": 0.75, "clip_strength": 0.45, "dark_only": False, "label": "Neon Abyss"},
                    {"fragments": ["cyberpunk_detailer", "cbrpnk", "Neon_Cyberpunk_Detailer"], "trigger": "mad-cbrpnk-dtlr",
                     "model_strength": 0.35, "clip_strength": 0.0, "dark_only": False, "label": "Cyberpunk Detailer"},
                ],
            },
        ],
    },

    # ── Post-apocalyptic desert wasteland ─────────────────────────────────────
    "desert_punk": {
        "label":       "Desert Punk",
        "description": "Post-apocalyptic wasteland — Mad Max / Fallout, salvaged tech, harsh sun, dust and rust.",
        "icon":        "🏜️",
        "style_guide_hint":  "post-apocalyptic gritty retrofuture concept art, weathered salvaged-tech textures, dramatic directional lighting",
        "themer_medium":     '"digital painting," or "post-apocalyptic concept art," or "gritty illustration,"',
        # Quality tag is appended to EVERY art_prompt — keep it to lighting/detail
        # words ONLY. A fixed palette here ("ochre and rust", "dust-hazed") forced
        # the same look on every card; per-card colour comes from mana identity.
        "themer_quality":    '"dramatic directional lighting, rich gritty detail" or "weathered texture, atmospheric depth" or "painterly, high detail"',
        # NOTE: avoid "bleached sky" / "harsh overhead sunlight" — at FLUX CFG 5.0
        # those resolve to pure white overexposure.
        #
        # IMPORTANT (variety): the flux_prefix LEADS every prompt, so it must carry
        # STYLE/medium only — NOT a fixed scene or wardrobe. The old prefix baked
        # "Sun-scorched desert wasteland, cracked red earth, amber dust haze" +
        # "salvaged rust-stained armor" into all 100 cards, so every card rendered
        # as the same desert with the same armor (the zero-variety bug). Each card's
        # unique scene now comes from its own art_prompt; the prefix only sets the
        # gritty post-apoc retrofuture LOOK.
        "flux_prefix": (
            "Digital painting, post-apocalyptic retrofuture concept art, gritty Mad-Max / Fallout aesthetic. "
            "Weathered salvaged-tech textures, rust and grime, dramatic directional lighting, deep shadows. "
            "Third-person view, character viewed from outside. High detail, landscape composition. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["retrofuture", "dystopia"],
                "trigger":        "RetroFutureDystopia",
                "model_strength": 0.55,
                # clip 0.65 over-weighted the LoRA's trained look (samey output);
                # keep style-LoRA clip moderate so each card's prompt shows through.
                "clip_strength":  0.45,
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
            "Third-person view, character viewed from outside. "
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
            "first person view, first-person perspective, pov shot, first person pov, "
            "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
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

    # ── Semi-realistic anime illustration ────────────────────────────────────────
    # Bridges anime aesthetics with photorealistic rendering for high-detail
    # card art — expressive anime eyes, realistic skin textures, dynamic lighting.
    # Unlike the flat-colour anime preset, this produces rich shading and depth.
    # LoRA: Flux Semi-Realistic Anime Art Style (civitai.com/models/754435)
    #   18 MB · no trigger word required · Very Positive (266 reviews)
    #   Save as: semi_realistic_anime_flux.safetensors
    "anime_illustrated": {
        "label":       "Anime Illustrated",
        "description": "Semi-realistic anime — expressive characters with detailed shading, depth, and dynamic lighting. High detail, not flat.",
        "icon":        "✨",
        "style_guide_hint":  "semi-realistic anime illustration, detailed shading, expressive eyes, dynamic lighting, rich backgrounds, high detail",
        "themer_medium":     '"anime illustration," or "semi-realistic anime art," or "detailed anime concept art,"',
        "themer_quality":    '"detailed shading, expressive anime style" or "semi-realistic anime, dynamic lighting" or "high detail anime illustration, rich color depth"',
        "flux_prefix": (
            "Semi-realistic anime illustration, highly detailed anime art style. "
            "Expressive anime eyes, rich volumetric lighting, detailed character rendering. "
            "Dynamic composition, vivid saturated colors, intricate background detail. "
            "High quality digital anime illustration, not flat, not cel-shaded. "
            "Third-person view, character viewed from outside. "
        ),
        "face_prefix_medium": "Semi-realistic anime portrait illustration",
        "face_prefix_quality": "detailed anime face, expressive eyes, realistic skin shading, dynamic lighting",
        "negative_prompt": (
            "photograph, photo, photorealistic, hyperrealistic, "
            "3d render, cgi, octane render, unreal engine, "
            "flat colour, cel-shaded, flat shading, no shading, "
            "bad hands, extra fingers, bad anatomy, deformed, "
            "first person view, first-person perspective, pov shot, first person pov, "
            "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        "loras": [
            {
                # dim2/alpha16 (≈8× internal scale), trained on only ~15 images, so at
                # high strength it imposes its default training subject (a ponytail
                # anime girl) on any card whose prompt doesn't specify a distinct
                # character. 0.6 keeps the semi-realistic anime *style* (verified the
                # look survives down to 0.5) while giving the prompt enough authority
                # to vary the subject. text encoder is untrained → clip_strength is a
                # no-op, left at 0.
                "fragments":      ["semi_realistic_anime", "semirealistic_anime", "semi-realistic_anime"],
                "trigger":        "",   # trigger already embedded in flux_prefix
                "model_strength": 0.6,
                "clip_strength":  0.0,
                "dark_only":      False,
                "label":          "Semi-Realistic Anime (Flux)",
                "download_url":   "https://civitai.com/models/754435",
                "download_note":  "Save as semi_realistic_anime_flux.safetensors",
            },
        ],
    },

    # ── Soft anime artbook style ──────────────────────────────────────────────────
    # Polished anime illustration — soft lighting, clean painterly rendering,
    # closer to key-animation artbook quality than flat TV anime.
    # LoRA: SoftServe Anime by Araminta (HuggingFace, free, no login required)
    #   Download: huggingface.co/alvdansen/softserve_anime
    #   Save as: softserve_anime_flux.safetensors
    "anime_soft": {
        "label":       "Anime Artbook",
        "description": "Soft artbook-quality anime — clean polished illustration, gentle lighting, painterly character rendering.",
        "icon":        "🌸",
        "style_guide_hint":  "anime artbook illustration style, soft painterly rendering, clean polished anime art, gentle volumetric lighting",
        "themer_medium":     '"anime illustration," or "anime artbook art," or "anime key visual,"',
        "themer_quality":    '"soft painterly anime, polished illustration" or "clean anime artbook style, gentle lighting" or "anime key visual quality, rich color"',
        "flux_prefix": (
            "sftsrv style illustration, anime artbook illustration. "
            "Soft painterly anime rendering, polished clean linework with gentle volumetric lighting. "
            "Rich backgrounds, anime key-visual quality. "
            "Warm saturated colors, smooth detailed shading. "
            "Third-person view, character viewed from outside. "
        ),
        "face_prefix_medium": "Anime artbook portrait, sftsrv style illustration",
        "face_prefix_quality": "clean detailed anime face, soft lighting, expressive eyes, polished illustration",
        "negative_prompt": (
            "photograph, photo, photorealistic, hyperrealistic, "
            "3d render, cgi, octane render, unreal engine, "
            "flat colour, cel-shaded, harsh flat shading, "
            "bad hands, extra fingers, bad anatomy, deformed, "
            "first person view, first-person perspective, pov shot, first person pov, "
            "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        "loras": [
            {
                "fragments":      ["softserve_anime", "softserve", "soft_serve_anime"],
                "trigger":        "",   # trigger already embedded in flux_prefix
                "model_strength": 0.90,
                "clip_strength":  0.7,
                "dark_only":      False,
                "label":          "SoftServe Anime (Araminta)",
                "download_url":   "https://huggingface.co/alvdansen/softserve_anime",
                "download_note":  "Download flux_dev_softstyle_araminta_k.safetensors → rename to softserve_anime_flux.safetensors",
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
            "Third-person view, character viewed from outside. High detail, intricate composition, subject fully in frame. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["mucha"],
                "trigger":        "Alphonse Mucha Style",
                "model_strength": 0.70,
                "clip_strength":  0.55,
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
        "style_guide_hint":  "dark gothic horror illustration, moonlit eerie atmosphere, dramatic chiaroscuro, crumbling architecture",
        "themer_medium":     '"dark gothic illustration," or "horror concept art," or "gothic painting,"',
        # Quality tag appended to EVERY prompt — lighting/detail/mood only, no palette lock.
        "themer_quality":    '"atmospheric shadow and gloom, fine detail" or "gothic horror mood, dramatic chiaroscuro" or "eerie cinematic lighting, rich detail"',
        # STYLE only — no fixed scene. The old prefix baked "haunted stone
        # architecture, gargoyles, iron gates, graveyards" into every card; the
        # per-card scene now comes from its art_prompt (zero-variety fix).
        "flux_prefix": (
            "Digital painting, dark gothic horror illustration, Innistrad-style. "
            "Moody atmospheric horror, deep shadow and pale moonlight, dramatic chiaroscuro, eerie unsettling mood. "
            "Third-person view, character viewed from outside. Landscape composition. "
            "Any visible hands have exactly five fingers each. "
        ),
        "negative_prompt": (
            "bad hands, extra fingers, four fingers, three fingers, wrong number of fingers, "
            "bad anatomy, deformed, ugly, "
            "first person view, first-person perspective, pov shot, first person pov, "
            "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
            "overexposed, washed out, blown out, pure white, "
            "colorful, bright, cheerful, sunny, pastel, vibrant rainbow, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        "loras": [
            {
                "fragments":      ["Dark_Haunted_Fantasy", "dark_haunted_fantasy", "halloweenstyle"],
                "trigger":        "halloweenstyle",
                "model_strength": 0.70,
                "clip_strength":  0.55,
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
            "Third-person view, character viewed from outside. Landscape composition. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["WATERCOLOR-lora", "watercolor_lora", "WATERCOLORlora"],
                "trigger":        "watercolor, wet on wet, paintstreaks, watercolor painting",
                "model_strength": 0.85,
                "clip_strength":  0.65,
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
        "style_guide_hint":  "steampunk illustration, Victorian brass-and-copper machine aesthetic, intricate clockwork detail, gas-lamp lighting",
        "themer_medium":     '"steampunk illustration," or "clockpunk concept art," or "Victorian mechanical painting,"',
        # Quality tag appended to EVERY prompt — texture/detail/lighting only, no palette lock.
        "themer_quality":    '"intricate mechanical detail, fine texture" or "brass-and-copper texture, painterly precision" or "warm gas-lamp lighting, rich detail"',
        # STYLE only — no fixed scene. The old prefix baked "clockwork cogs, gears,
        # pipes, Victorian-industrial architecture, dirigibles" into every card; the
        # per-card scene now comes from its art_prompt (zero-variety fix).
        "flux_prefix": (
            "Digital painting, steampunk illustration, Kaladesh-style Victorian brass-and-copper aesthetic. "
            "Intricate clockwork detail and patinated metal textures, warm gas-lamp lighting, painterly. "
            "Third-person view, character viewed from outside. Landscape composition. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["SteampunkIllustration", "steampunk_illustration", "steampunk_illus"],
                "trigger":        "steampunk illustration, mechanical, cogs and gears, copper pipes, ornate",
                "model_strength": 0.80,
                "clip_strength":  0.6,
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
            "Third-person view, character viewed from outside. Landscape composition. "
            "Any visible hands have exactly five fingers each. "
        ),
        "loras": [
            {
                "fragments":      ["oil_painting_flux", "oil_painting_flux-h"],
                "trigger":        "oil painting",
                "model_strength": 0.75,
                "clip_strength":  0.6,
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
            "Third-person view, character viewed from outside. Wide composition, subject fully in frame. "
        ),
        "negative_prompt": (
            "bad hands, extra fingers, bad anatomy, deformed, ugly, "
            "photograph, photo, photorealistic, hyperrealistic, "
            "first person view, first-person perspective, pov shot, first person pov, "
            "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
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
        "style_guide_hint":  "eldritch cosmic horror illustration, Lovecraftian surreal atmosphere, ominous alien dread, dramatic scale",
        "themer_medium":     '"eldritch illustration," or "cosmic horror concept art," or "Lovecraftian painting,"',
        # Quality tag appended to EVERY prompt — mood/detail only, no fixed subject/palette.
        "themer_quality":    '"surreal warped detail, ominous atmosphere" or "cosmic horror mood, eerie depth" or "alien detail, dramatic dread"',
        # STYLE only — no fixed scene. The old prefix baked "non-Euclidean geometry,
        # writhing tentacles, star-filled void, eyes, alien architecture" into every
        # card; the per-card scene now comes from its art_prompt (zero-variety fix).
        "flux_prefix": (
            "Digital illustration, eldritch cosmic horror comic art style, Lovecraftian. "
            "Oppressive cosmic dread, otherworldly alien atmosphere, surreal warped detail, ominous sense of scale. "
            "Third-person view, character viewed from outside. Landscape composition. "
            "Any visible hands have exactly five fingers each. "
        ),
        "negative_prompt": (
            "bad hands, extra fingers, four fingers, three fingers, wrong number of fingers, "
            "bad anatomy, deformed, ugly, "
            "first person view, first-person perspective, pov shot, first person pov, "
            "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
            "overexposed, washed out, blown out, pure white, "
            "bright cheerful colors, pastel, rainbow, "
            "watermark, text, border, card frame, out of frame, cropped, nsfw"
        ),
        "loras": [
            {
                "fragments":      ["Eldritch_Comics", "eldritch_comics", "Eldritch_Comics_for_Flux"],
                "trigger":        "illustration",
                "model_strength": 0.75,
                "clip_strength":  0.6,
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
            "Third-person view, character viewed from outside. Landscape composition. "
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

    # ── Ragnarok Online illustrated card/loading screen style ───────────────────
    # Trained on Illustrious XL (SDXL). ro_lora_v2 — 1374 images, rank 64, alpha 32.
    # WD14-retagged captions: trigger words lock to front via keep_tokens=2.
    # IMPORTANT: Requires Illustrious XL loaded in ComfyUI — will not work on FLUX.
    "ragnarok_online": {
        "label":       "Ragnarok Online",
        "description": "RO illustrated card art style — anime fantasy, jewel-tone palettes, painterly character portraits. Understands RO card names, job classes, elements, and races. REQUIRES Illustrious XL (SDXL).",
        "icon":        "⚔️",
        "required_checkpoint_type": "sdxl",
        "style_guide_hint":  "ragnarok online card art style, anime fantasy illustration, vibrant jewel-tone colors, painterly character portraits, detailed fantasy adventure scenes",
        "themer_medium":     '"anime illustration," or "fantasy card art," or "painted anime portrait,"',
        "themer_quality":    '"detailed anime illustration, jewel-tone palette" or "painterly fantasy card art, vivid saturated colors" or "high-detail illustrated character, vibrant anime style"',
        # themer_vocabulary: injected into the batch prompt so Ollama uses the exact
        # token vocabulary the LoRA was trained on (elements, races, job-class tags).
        # Format mirrors the training caption schema:
        #   ragnarok online style, ro card art, [element] element, [race] race, [job tags], ..., [suffix]
        "themer_vocabulary": (
            "RAGNAROK ONLINE LoRA VOCABULARY — use these EXACT tokens, they activate trained visual concepts.\n"
            "\n"
            "PROMPT STRUCTURE: [medium], [element token], [race token], [job class tag(s)], [scene description], [suffix]\n"
            "Insert element + race + class tags RIGHT AFTER the medium, BEFORE the scene.\n"
            "\n"
            "ELEMENT TOKENS — pick from card's MTG color identity (col 5):\n"
            "  W (white)     -> holy element\n"
            "  U (blue)      -> water element   (ethereal/ghost: ghost element)\n"
            "  B (black)     -> shadow element  (undead creature: undead)\n"
            "  R (red)       -> fire element\n"
            "  G (green)     -> earth element   (wind/flying: wind element)\n"
            "  Colorless     -> neutral element\n"
            "  Multi-color   -> use dominant color or combine: 'holy fire element', 'water shadow element'\n"
            "\n"
            "RACE TOKENS — pick from creature subtype/flavor:\n"
            "  Angel, Cleric, Divine       -> angel race\n"
            "  Dragon, Wyvern              -> dragon race\n"
            "  Beast, Wolf, Bear, Cat      -> brute race\n"
            "  Zombie, Skeleton, Specter   -> undead race\n"
            "  Merfolk, Serpent, Fish      -> fish race\n"
            "  Goblin, Orc, Demon          -> demon race\n"
            "  Human, Soldier, Knight      -> demihuman race\n"
            "  Spider, Insect, Bug         -> insect race\n"
            "  Plant, Saproling, Treefolk  -> plant race\n"
            "  Elemental, Golem, Construct -> formless race\n"
            "\n"
            "JOB CLASS TAGS — match creature archetype (add 1-2 most fitting):\n"
            "  Armored swordsman          -> knight | lord knight | rune knight\n"
            "  Holy paladin/defender      -> crusader | paladin | royal guard\n"
            "  Fire/ice/lightning mage    -> wizard | high wizard | warlock\n"
            "  Healer, support caster     -> priest | archbishop | acolyte\n"
            "  Shadow assassin, rogue     -> assassin | guillotine cross | shadow chaser\n"
            "  Archer, marksman           -> hunter | sniper | ranger\n"
            "  Martial monk, fist fighter -> monk | champion | sura\n"
            "  Engineer, inventor         -> mechanic | blacksmith | genetic\n"
            "  Ninja, shadow warrior      -> ninja | kagerou | oboro\n"
            "  Gunner, gunslinger         -> gunslinger | rebellion\n"
            "  Bard, musician             -> bard | clown | minstrel\n"
            "  Dancer, performer          -> dancer | gypsy | wanderer\n"
            "  Non-creature (spell/land)  -> omit class tag\n"
            "\n"
            "COMPOSITION SUFFIX — always end with one of these:\n"
            "  'full body portrait, painterly background, saturated colors'\n"
            "  'full body action pose, vibrant background, jewel-tone palette'\n"
            "  'card illustration, detailed background, vivid colors'\n"
            "\n"
            "EXAMPLE (W/U creature — angel, holy paladin):\n"
            "  fantasy card art, holy water element, angel race, archbishop, [white-winged healer in a misty shrine, golden light streaming down], full body portrait, painterly background, saturated colors\n"
            "EXAMPLE (B/R instant — shadow fire, no creature class):\n"
            "  fantasy card art, shadow fire element, [eruption of dark flame consuming a battlefield ruin at dusk], card illustration, detailed background, vivid colors"
        ),
        # flux_prefix: not used for SDXL (Illustrious XL uses _SDXL_PREFIX instead).
        # Triggers are prepended via lora_trigger_prefix, which takes effect before _SDXL_PREFIX.
        "flux_prefix": None,
        # Custom negative: removes "anime, cartoon" suppression terms that are in the
        # global NEGATIVE_PROMPT — Illustrious XL IS an anime model, those terms hurt it.
        "negative_prompt": (
            "bad hands, extra fingers, missing fingers, fused fingers, too many fingers, "
            "mutated hands, poorly drawn hands, deformed hands, malformed hands, "
            "bad anatomy, extra limbs, missing limbs, missing arms, missing legs, "
            "extra arms, extra legs, disconnected limbs, malformed limbs, gross proportions, "
            "long neck, elongated neck, twisted body, "
            "bad face, ugly face, deformed face, poorly drawn face, asymmetrical face, "
            "first person view, first-person perspective, pov shot, first person pov, "
            "hands in foreground, foreground hands, player pov, viewer pov, point of view shot, "
            "ugly, worst quality, low quality, "
            "blurry, out of focus, soft focus, "
            "jpeg artifacts, compression artifacts, pixelated, noisy, grainy, "
            "overexposed, underexposed, washed out, flat lighting, "
            "low resolution, draft, unfinished, "
            "watermark, signature, text, username, artist name, logo, stamp, "
            "border, frame, card template, card border, card frame, "
            "duplicate, clone, multiple copies, tiling, collage, "
            "3d render, cgi, plastic, doll, mannequin, toy, figurine, "
            "photograph, photo, photorealistic, hyperrealistic, "
            "nsfw, nude, explicit"
        ),
        # face_prefix: for character cards with face conditioning
        "face_prefix_medium": "Anime illustration portrait, ragnarok online style",
        "face_prefix_quality": "detailed anime face, expressive eyes, painterly skin tones, vibrant colors",
        # loras: default/fallback list (used when lora_variants is absent or for
        # lora_count in STYLE_PRESETS). Points to the illustrated style entries.
        "loras": [
            {
                "fragments":      ["ro_lora_v5", "ro_lora_v4", "ro_lora_v3", "ro_lora_v2", "ro_lora"],
                "trigger":        "ragnarok online style, ro card art",
                "model_strength": 0.85,
                "clip_strength":  0.7,
                "dark_only":      False,
                "label":          "Ragnarok Online Style v5",
                "download_url":   None,
                "download_note":  "ro_lora_v5.safetensors — Illustrious XL, 1687 official art + 7881 Danbooru job classes, semantic card names",
            },
        ],
        # lora_variants: randomly selects between illustrated style (2/3) and
        # pixel art sprite style (1/3) on each card generation.
        "lora_variants": [
            {
                "weight": 2,
                "label":  "Illustrated Style",
                "loras": [
                    {
                        # v5/v4/v3/v2 cascade: illustrated RO card art + job classes.
                        # Captions include card names, element, race, job tags.
                        # v5 adds 313 unique GRF card illustrations + more Danbooru data.
                        "fragments":      ["ro_lora_v5", "ro_lora_v4", "ro_lora_v3", "ro_lora_v2", "ro_lora"],
                        "trigger":        "ragnarok online style, ro card art",
                        "model_strength": 0.85,
                        "clip_strength":  0.7,
                        "dark_only":      False,
                        "label":          "Ragnarok Online Style",
                        "download_url":   None,
                        "download_note":  "ro_lora_v5.safetensors — train via train_v5.bat",
                    },
                ],
            },
            {
                "weight": 1,
                "label":  "Pixel Art Sprite Style",
                "loras": [
                    {
                        # RO Sprite Pixel Art LoRA by Konan (civitai.com/models/1242746)
                        # Trained on Illustrious/NoobAI XL — generates classic RO sprite-style
                        # pixel art characters. Trigger: "pixel, full body, simple background".
                        "fragments":      ["ro_pixel_sprite", "RagnarokSpriteNoob", "ragnarok_sprite"],
                        "trigger":        "pixel art, ragnarok online style, full body, simple background, white background",
                        "model_strength": 0.9,
                        "clip_strength":  0.75,
                        "dark_only":      False,
                        "label":          "RO Pixel Sprite LoRA",
                        "download_url":   "https://civitai.com/models/1242746",
                        "download_note":  "RagnarokSpriteNoob_byKonan — CivitAI requires a LOGGED-IN download "
                                          "(the API URL returns 'Unauthorized'). Download via the web UI while "
                                          "signed in, save as ro_pixel_sprite_lora.safetensors in ComfyUI/models/loras/. "
                                          "Until then this variant is auto-skipped and RO builds use the v5 illustrated style.",
                    },
                ],
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
        "style_guide_hint":   p.get("style_guide_hint", ""),
        "themer_medium":      p.get("themer_medium", '"digital painting," or "fantasy illustration," or "concept art,"'),
        "themer_quality":     p.get("themer_quality", '"painterly brushwork, vivid colors" or "dramatic lighting, intricate detail" or "painterly, rich texture"'),
        # themer_vocabulary: style-specific token vocabulary injected into the LLM
        # batch prompt (currently only set for ragnarok_online — trains the LLM to use
        # LoRA-trained concept tokens like "holy element", "angel race", "archbishop").
        "themer_vocabulary":  p.get("themer_vocabulary", ""),
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


# ── Turbo render mode ─────────────────────────────────────────────────────────
# flux-dev + a distillation ("turbo") LoRA runs at ~8 steps near full dev quality
# (~3-4x faster than 28-step dev, far sharper than schnell). The LoRA file is
# user-supplied — drop it in ComfyUI/models/loras/ like any other; it's matched by
# these filename fragments. Recommended: alimama-creative FLUX.1-Turbo-Alpha
# (8 steps, model strength 1.0, guidance 3.5). If none is installed, turbo falls
# back to standard 28-step dev so output never degrades to noise.
_TURBO_LORA_FRAGMENTS = [
    "FLUX.1-Turbo-Alpha", "flux.1-turbo", "flux-turbo", "fluxturbo",
    "Hyper-FLUX.1-dev-8steps", "Hyper-FLUX", "Hyper-SD-FLUX", "Hyper-SD3",
]
_TURBO_STEPS         = 8
_TURBO_LORA_STRENGTH = 1.0    # Turbo-Alpha / Hyper-8step both want ~1.0 on the UNET
_TURBO_FALLBACK_STEPS = 28    # used when turbo requested but no turbo LoRA present


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

def _is_sdxl(name: str) -> bool:
    """SDXL models (including Illustrious, Juggernaut, etc.)
    Detected by presence of 'sdxl' or common SDXL model names."""
    n = name.lower()
    return ("sdxl" in n) or ("illustrious" in n) or ("juggernaut" in n) or \
           ("realistic" in n and "sd" in n) or ("dreamshaper" in n)


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

def _build_sdxl_workflow(checkpoint: str, positive: str, seed: int,
                          negative: str = "") -> dict:
    neg = negative or NEGATIVE_PROMPT
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage",        "inputs": {"width": CARD_WIDTH, "height": CARD_HEIGHT, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode",          "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode",          "inputs": {"text": neg,      "clip": ["4", 1]}},
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
                          negative: str = "", gen: Optional[GenSettings] = None) -> dict:
    gen = gen or GenSettings()
    neg = negative or _FLUX_NEGATIVE
    is_schnell = "schnell" in checkpoint.lower()
    # FLUX is GUIDANCE-DISTILLED: it expects its guidance value through a
    # FluxGuidance conditioning node, NOT classifier-free guidance.  Driving it
    # with KSampler cfg>1 plus a negative prompt over-guides the latent and
    # pushes it to a blown-out near-white frame.  This was the cause of the
    # cyberpunk "overexposed/blank" failures: measured mean brightness ~250
    # (detector rejects >242) at cfg 3.5, vs ~109 with the fix below — and
    # lowering LoRA strength alone did NOT fix it, only the sampler change did.
    #   Correct usage (ComfyUI canonical FLUX): KSampler cfg=1.0 + a FluxGuidance
    #   node at ~3.5 (community sweet spot 3.0–4.0).  At cfg=1.0 the negative
    #   prompt is inert (FLUX ignores it) — that is expected and correct; FLUX
    #   steers from the positive prompt, not negatives.
    #   Schnell is distilled to ignore guidance entirely, so it runs cfg=1.0
    #   with no FluxGuidance node at all.
    #   dpm++_2m + sgm_uniform remains the sharpest combo for illustration detail.
    # User-configurable knobs (fall back to model-appropriate defaults).
    # flux-dev fp8 is ~indistinguishable at 28 vs 35 steps for card art but ~20%
    # faster (~38s -> ~30s/card on a 3090); override via gen.steps for max fidelity.
    steps    = gen.steps     if gen.steps     else (8       if is_schnell else 28)
    sampler  = gen.sampler   or              ("euler"  if is_schnell else "dpmpp_2m")
    scheduler= gen.scheduler or              ("simple" if is_schnell else "sgm_uniform")
    flux_guidance = gen.guidance     # distilled guidance for dev (ignored by schnell)
    width, height = gen.width, gen.height
    wf = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "EmptyLatentImage",       "inputs": {"width": width, "height": height, "batch_size": 1}},
        "3": {"class_type": "CLIPTextEncode",         "inputs": {"text": positive, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",         "inputs": {"text": neg,      "clip": ["1", 1]}},
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": steps, "cfg": 1.0,
                "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0,
                "model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["2", 0],
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mtg_card", "images": ["6", 0]}},
    }
    if not is_schnell:
        # Insert FluxGuidance between the positive encode and the sampler.
        # (_insert_loras only rewires CLIPTextEncode.clip and KSampler.model, so
        # this node and the KSampler.positive link below survive LoRA chaining.)
        wf["8"] = {"class_type": "FluxGuidance",
                   "inputs": {"conditioning": ["3", 0], "guidance": flux_guidance}}
        wf["5"]["inputs"]["positive"] = ["8", 0]
    return wf


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
                     negative: str = "", gen: Optional[GenSettings] = None) -> dict:
    if _is_sd35(checkpoint):
        return _build_sd35_workflow(checkpoint, positive, seed, negative=negative)
    if _is_flux(checkpoint):
        return _build_flux_workflow(checkpoint, positive, seed, negative=negative, gen=gen)
    return _build_sdxl_workflow(checkpoint, positive, seed, negative=negative)


# ── Face-conditioning workflow builders ───────────────────────────────────────

def _build_pulid_flux_workflow(
    checkpoint: str, positive: str, seed: int,
    face_comfy_name: str,
    pulid_model: str,
    eva_clip_model: str,
    negative: str = "",
    gen: Optional[GenSettings] = None,
) -> dict:
    """
    FLUX + PuLID face-conditioning workflow.
    ApplyPulidFlux wraps the base model so the KSampler generates
    an image whose subject resembles the reference face.
    """
    gen = gen or GenSettings()
    neg = negative or _FLUX_NEGATIVE
    is_schnell = "schnell" in checkpoint.lower()
    # See _build_flux_workflow: FLUX uses cfg=1.0 + a FluxGuidance node, never
    # KSampler cfg>1 (which over-guides to a blown-out white frame).
    # flux-dev fp8 is ~indistinguishable at 28 vs 35 steps for card art but ~20%
    # faster (~38s -> ~30s/card on a 3090); override via gen.steps for max fidelity.
    steps    = gen.steps     if gen.steps     else (8       if is_schnell else 28)
    sampler  = gen.sampler   or              ("euler"  if is_schnell else "dpmpp_2m")
    scheduler= gen.scheduler or              ("simple" if is_schnell else "sgm_uniform")
    flux_guidance = gen.guidance     # distilled guidance for dev (ignored by schnell)
    face_weight = gen.face_weight if gen.face_weight is not None else 0.75
    width, height = gen.width, gen.height
    wf = {
        "1":  {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2":  {"class_type": "EmptyLatentImage",       "inputs": {"width": width, "height": height, "batch_size": 1}},
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
                # weight 0.75 default: enough identity preservation without over-
                # constraining composition for non-portrait action scenes.  0.85
                # caused cramped layouts on creature cards mid-action.  User-tunable
                # via gen.face_weight.
                "weight":       face_weight,
                # start_at 0.1: lets FLUX establish rough composition (layout, sky, ground)
                # in the first 3-4 steps before face identity is injected.  Starting at
                # 0.0 locks everything to the face embedding from step 0, which competes
                # with the scene composition and produces face-blob artifacts.
                "start_at":     0.1,
                "end_at":       1.0,
                "fusion":       "mean",
                "fusion_weight": 1.0,
            },
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": steps, "cfg": 1.0,
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
    if not is_schnell:
        # FluxGuidance node id 14 (PuLID nodes occupy 10–13). Survives LoRA chaining.
        wf["14"] = {"class_type": "FluxGuidance",
                    "inputs": {"conditioning": ["3", 0], "guidance": flux_guidance}}
        wf["5"]["inputs"]["positive"] = ["14", 0]
    return wf


def _build_faceid_sdxl_workflow(
    checkpoint: str, positive: str, seed: int,
    face_comfy_name: str,
    ipadapter_model: str,
    clip_vision_model: str,
    negative: str = "",
) -> dict:
    """
    SDXL + IP-Adapter FaceID workflow.
    IPAdapterFaceID modifies the model so generated portraits resemble
    the reference face.
    """
    neg = negative or NEGATIVE_PROMPT
    return {
        "1": {"class_type": "CheckpointLoaderSimple",  "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "EmptyLatentImage",         "inputs": {"width": CARD_WIDTH, "height": CARD_HEIGHT, "batch_size": 1}},
        "3": {"class_type": "CLIPTextEncode",           "inputs": {"text": positive, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",           "inputs": {"text": neg,      "clip": ["1", 1]}},
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

class _ReactorCudaError(Exception):
    """
    Raised by _wait_for_image when ReActor face-swap fails due to a CUDA 12.x
    driver mismatch.  Signals generate() to retry the card without face
    conditioning rather than silently falling back to Scryfall art.
    """


class ImageGen:
    def __init__(self, comfy_base: str = "", checkpoint: Optional[str] = None,
                 model_speed: str = "quality", art_style: str = "mtg_fantasy",
                 gen_settings: Optional[GenSettings] = None):
        """
        model_speed: "quality" → prefer flux-dev (slower, sharper)
                     "turbo"   → flux-dev + turbo LoRA at 8 steps (~3-4× faster,
                                 near-dev quality); needs a turbo LoRA installed
                     "fast"    → prefer flux-schnell (4-8× faster, lower detail)
        art_style:   preset key from _LORA_PRESETS (e.g. "mtg_fantasy", "cyberpunk")
        gen_settings: user-configurable knobs (guidance/steps/seed/loras/safe_mode…).
                      None → defaults (existing behavior).
        """
        # User-configurable generation settings (guidance, steps, seed, loras, …)
        self.gen = gen_settings or GenSettings()
        # Turbo mode runs flux-dev at a low step count via a distillation LoRA
        # (resolved in _setup_loras). Default the step count here so the workflow
        # builders pick it up; a user gen.steps override still wins.
        self._turbo = (model_speed == "turbo")
        self._turbo_lora: Optional[dict] = None
        if self._turbo and self.gen.steps is None:
            self.gen.steps = _TURBO_STEPS
        # Safe mode: shrink the workload that can trip an unstable machine under
        # combined GPU+CPU load — fewer steps and a smaller canvas.
        if self.gen.safe_mode:
            if self.gen.steps is None:
                self.gen.steps = 28
            self.gen.width  = 896
            self.gen.height = 600
            print("  [image_gen] SAFE MODE on — steps capped, resolution reduced "
                  f"({self.gen.width}x{self.gen.height})")
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
        # Per-card LoRA rotation pool (populated by _setup_loras from a preset's
        # "lora_rotation"): list of {label, loras:[resolved], trigger_prefix}.
        # When non-empty, generate() picks one stack per card for stylistic variety.
        self._lora_rotation: list[dict] = []
        self.theme_darkness: float = 1.0       # 0.0=light/whimsical → 1.0=dark/neutral
        self.active_flux_prefix: str = _FLUX_PREFIX   # overridden by _setup_loras()
        self.active_negative:    str = _FLUX_NEGATIVE # overridden by _setup_loras()

        if self.available:
            self._setup_face_method()
            self._setup_loras()
            # Turbo requested but no turbo LoRA installed → 8 steps alone would be
            # noisy. Fall back to standard dev steps so quality never degrades.
            if self._turbo and self._turbo_lora is None and self.gen.steps == _TURBO_STEPS:
                self.gen.steps = _TURBO_FALLBACK_STEPS
                print(f"  [image_gen] ⚠ Turbo requested but no turbo LoRA installed "
                      f"(expected one of {_TURBO_LORA_FRAGMENTS}); using "
                      f"{_TURBO_FALLBACK_STEPS}-step dev instead.")
            # Log resolved generation settings once per build for easy troubleshooting.
            try:
                print(f"  [gen_settings] {json.dumps(self.gen.resolved())}")
            except Exception:
                pass

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
                #   "sd35"            → SD 3.5 Large (slower, different aesthetic)
                #   "fast"            → FLUX Schnell (4–8× faster than dev)
                #   "quality"/"turbo" → FLUX dev (turbo adds a distillation LoRA +
                #                       low steps for ~3-4× speed at near-dev quality)
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
                sdxl    = [c for c in usable if _is_sdxl(c) and c not in sd35]  # SDXL but not SD3.5
                return {"dev": dev, "schnell": schnell, "sd35": sd35, "sdxl": sdxl, "all": flux + sdxl + sd35}
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
        elif _is_sdxl(self.checkpoint):
            kind = "SDXL"
        else:
            kind = "Unknown"
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
                    loras = sorted([f.name for f in lora_dir.glob("*.safetensors")])
                    if loras:
                        print(f"  [image_gen] LoRAs loaded from disk (ComfyUI list was empty): {loras}")
                        return loras
        except Exception as e:
            print(f"  [image_gen] Disk LoRA scan failed: {e}")
        return []

    def _setup_face_method(self) -> None:
        """Detect best available face-conditioning method and cache model names."""
        # User override: explicitly disable face conditioning.
        if self.gen.face_method == "none":
            self.face_method = "none"
            print("  [image_gen] Face method: none (disabled by user setting)")
            return

        available_nodes = self._get_available_nodes()

        # User override: try a specific method first (falls through to auto-detect
        # if the requested method's nodes/models aren't available).
        forced = self.gen.face_method
        methods = list(_FACE_METHODS.items())
        if forced and forced in _FACE_METHODS:
            methods.sort(key=lambda kv: kv[0] != forced)

        for method, required_nodes in methods:
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

                # Only use ReActor if we have actual models
                if swap_models:
                    # Prefer inswapper_128, fall back to first available
                    swap = next(
                        (m for m in swap_models if "inswapper_128" in m.lower()),
                        swap_models[0],
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
                # else: ReActorFaceSwap node exists but no models — fall through to try other methods

        print("  [image_gen] Face method: none (install PuLID/ReActor for face features)")

    # ── LoRA setup ────────────────────────────────────────────────────────────

    def _setup_loras(self) -> None:
        """
        Query ComfyUI for installed LoRAs and match them against the active
        preset's LoRA list.  Builds self.active_loras, self.lora_trigger_prefix,
        and self.active_flux_prefix.  Supports FLUX and SDXL models.
        """
        _all = get_all_presets()
        preset = _all.get(self.art_style, _all.get("mtg_fantasy", next(iter(_all.values()))))

        # Detect checkpoint family up front — the negative-prompt fallback below
        # and the LoRA-compatibility gates further down both depend on these.
        is_flux = _is_flux(self.checkpoint or "")
        is_sd35 = _is_sd35(self.checkpoint or "")
        is_sdxl = _is_sdxl(self.checkpoint or "")

        # Set prompt prefix from preset (None → keep module default _FLUX_PREFIX)
        custom_prefix = preset.get("flux_prefix")
        if custom_prefix is not None:
            self.active_flux_prefix = custom_prefix

        # Per-preset negative prompt (None / "" → use model-appropriate default).
        # Anime, photorealism etc. need different negatives to keep FLUX's
        # photoreal prior from overpowering style-specific LoRAs.
        # SDXL/SD3.5 respond to negatives at high CFG — fall back to the full
        # NEGATIVE_PROMPT (anatomy + quality terms) rather than _FLUX_NEGATIVE
        # (which is tuned for FLUX's low-CFG regime and lacks those terms).
        _preset_neg = preset.get("negative_prompt")
        if _preset_neg:
            self.active_negative = _preset_neg
        elif is_flux:
            self.active_negative = _FLUX_NEGATIVE
        else:
            self.active_negative = NEGATIVE_PROMPT

        style_label = preset["label"]
        print(f"  [image_gen] Art style: {style_label}")

        # Checkpoint type mismatch warning
        required_type = preset.get("required_checkpoint_type", "").lower()
        if required_type:
            if is_flux:
                checkpoint_type = "flux"
            elif is_sd35:
                checkpoint_type = "sd3.5"
            elif is_sdxl:
                checkpoint_type = "sdxl"
            else:
                checkpoint_type = "unknown"
            if required_type != checkpoint_type:
                print(f"  [image_gen] ⚠️  WARNING: '{style_label}' preset requires {required_type.upper()}, "
                      f"but {checkpoint_type.upper()} is loaded ({self.checkpoint}). "
                      f"Load {required_type.upper()} checkpoint for best results.")

        # Skip LoRAs for unsupported model types (neither FLUX nor SDXL)
        if not is_flux and not is_sdxl:
            return

        # Schnell is a different distilled architecture — dev-trained LoRAs are
        # incompatible and produce incoherent output.  Skip LoRA setup entirely;
        # schnell runs prompt-only.  (Future schnell-native LoRAs can be added
        # to the catalog with a schnell_ok=True flag to opt back in.)
        if is_flux and "schnell" in (self.checkpoint or "").lower():
            print(f"  [image_gen] FLUX schnell detected — skipping LoRA setup "
                  f"(dev-trained LoRAs are incompatible with schnell)")
            return

        installed = self._query_model_list("LoraLoader", "lora_name")
        if not installed:
            return

        # ── Variant selection ─────────────────────────────────────────────────
        # If the preset defines lora_variants (list of {"weight": N, "label": str,
        # "loras": [...]}) randomly pick one variant proportional to weights.
        # This lets a single preset produce different visual styles per-card,
        # e.g. illustrated art 2/3 of the time, pixel art 1/3 of the time.
        lora_list = preset["loras"]
        variant_label = ""
        variants = preset.get("lora_variants")
        if variants:
            # Only consider variants whose LoRAs are actually installed — a variant
            # whose file is missing (e.g. a login-gated CivitAI sprite LoRA) would
            # otherwise be picked and render prompt-only/inconsistent. If none are
            # installed, fall back to the full list (legacy prompt-only behaviour).
            def _variant_installed(v):
                for entry in v.get("loras", []):
                    frags = entry.get("fragments", [entry.get("fragment", "")])
                    if any(any(fr.lower() in f.lower() for fr in frags) for f in installed):
                        return True
                return False
            usable = [v for v in variants if _variant_installed(v)] or variants
            if len(usable) < len(variants):
                _dropped = [v.get("label", "variant") for v in variants if v not in usable]
                print(f"  [image_gen] LoRA variants skipped (no installed LoRA): {_dropped}")
            weights = [v.get("weight", 1) for v in usable]
            chosen = random.choices(usable, weights=weights, k=1)[0]
            lora_list = chosen["loras"]
            variant_label = f" [{chosen.get('label', 'variant')}]"
            print(f"  [image_gen] LoRA variant selected:{variant_label} "
                  f"(weights={weights})")

        found: list[dict] = []
        missing_labels: list[str] = []
        for entry in lora_list:
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
            model_type = "SDXL" if is_sdxl else "FLUX"
            print(f"  [image_gen] LoRAs active ({len(found)}/{len(lora_list)}){variant_label} [{model_type}]: "
                  f"{'; '.join(labels)}")
        if missing_labels:
            print(f"  [image_gen] LoRAs missing for '{style_label}': "
                  f"{missing_labels} — preset runs prompt-only for those.")

        # ── Turbo mode: resolve a distillation LoRA (flux-dev only) ─────────────
        # Applied on TOP of the style stack in generate(); lets dev run at 8 steps.
        if self._turbo and is_flux and "schnell" not in (self.checkpoint or "").lower():
            tmatch = next(
                (f for f in installed
                 if any(frag.lower() in f.lower() for frag in _TURBO_LORA_FRAGMENTS)),
                None,
            )
            if tmatch:
                self._turbo_lora = {
                    "label": "Turbo (distill)", "filename": tmatch, "trigger": "",
                    "model_strength": _TURBO_LORA_STRENGTH, "clip_strength": 0.0,
                }
                print(f"  [image_gen] Turbo mode ON: {tmatch} @ "
                      f"{self.gen.steps or _TURBO_STEPS} steps")

        # ── User LoRA overrides (from the Advanced "LoRA picker") ───────────────
        # gen.lora_overrides is a list of {filename, model_strength, clip_strength?,
        # trigger?}.  When present it REPLACES the preset's default stack so the user
        # has full control over which installed LoRAs run and at what strength.
        overrides = self.gen.lora_overrides
        if overrides:
            resolved: list[dict] = []
            for ov in overrides:
                fn = ov.get("filename")
                if not fn:
                    continue
                # accept exact filename or a fragment match against installed list
                match = fn if fn in installed else next(
                    (f for f in installed if fn.lower() in f.lower()), None)
                if not match:
                    print(f"  [image_gen] LoRA override not installed, skipping: {fn}")
                    continue
                resolved.append({
                    "filename":       match,
                    "trigger":        ov.get("trigger", ""),
                    "model_strength": float(ov.get("model_strength", 0.7)),
                    "clip_strength":  float(ov.get("clip_strength", 0.0)),
                    "dark_only":      False,
                    "label":          ov.get("label", match),
                })
            self.active_loras = resolved
            triggers = [e["trigger"] for e in resolved if e.get("trigger")]
            self.lora_trigger_prefix = ", ".join(triggers) + ". " if triggers else ""
            print(f"  [image_gen] LoRA overrides applied ({len(resolved)}): "
                  f"{[e['label'] for e in resolved]}")

        # ── Per-card LoRA rotation pool ─────────────────────────────────────────
        # A preset may define "lora_rotation": a list of style stacks. We resolve
        # each stack's filenames once here; generate() then picks one stack PER CARD
        # for stylistic variety across a deck.  Skipped when the user supplied
        # explicit LoRA overrides (their choice wins).
        rotation_spec = preset.get("lora_rotation")
        if rotation_spec and not overrides:
            pool: list[dict] = []
            for stack in rotation_spec:
                resolved_stack: list[dict] = []
                for entry in stack.get("loras", []):
                    frags = entry.get("fragments", [entry.get("fragment", "")])
                    match = next((f for f in installed
                                  if any(fr.lower() in f.lower() for fr in frags)), None)
                    if match:
                        resolved_stack.append({**entry, "filename": match})
                if resolved_stack:
                    trg = [e["trigger"] for e in resolved_stack if e.get("trigger")]
                    pool.append({
                        "label":         stack.get("label", "stack"),
                        "loras":         resolved_stack,
                        "trigger_prefix": (", ".join(trg) + ". ") if trg else "",
                    })
            if pool:
                self._lora_rotation = pool
                # default to the first stack (generate() re-picks per card)
                self.active_loras       = pool[0]["loras"]
                self.lora_trigger_prefix = pool[0]["trigger_prefix"]
                print(f"  [image_gen] LoRA rotation enabled ({len(pool)} stacks): "
                      f"{[p['label'] for p in pool]}")

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
                print(f"  [image_gen] Uploaded face -> ComfyUI input/{name}")
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
            # Check cancel event before sleeping.
            # Use cancel_event.wait() instead of time.sleep() so the sleep is
            # immediately interrupted the moment cancel is set — no need to wait
            # up to POLL_INTERVAL seconds before detecting it.
            if cancel_event is not None:
                cancel_event.wait(timeout=POLL_INTERVAL)
                if cancel_event.is_set():
                    print(f"  [image_gen] Cancel requested — interrupting ComfyUI prompt {prompt_id}")
                    try:
                        # Stop the running generation
                        requests.post(f"{self.comfy_base}/interrupt", timeout=5)
                    except Exception as e:
                        print(f"  [image_gen] Interrupt request failed: {e}")
                    try:
                        # Clear the ComfyUI queue so no pending jobs start next
                        requests.post(f"{self.comfy_base}/queue",
                                      json={"clear": True}, timeout=5)
                    except Exception:
                        pass
                    return None
            else:
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
                print(f"  [image_gen] [{elapsed:.1f}s] ComfyUI status -> {status_str!r}")
                last_status_str = status_str

            # ── Detect ComfyUI execution errors ──────────────────────────────
            # When a node fails (OOM, missing LoRA, bad input…) ComfyUI marks
            # status_str = "error" and embeds the reason in status["messages"].
            # NOTE: completed may be False on some errors (e.g. comfy_aimdo
            # VRAMBuffer crash) — check status_str alone, not completed+status_str.
            if status_str in ("error", "failed"):
                messages = status.get("messages", [])
                cuda_error_detected = False

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

                        # ── ReActor Error Handling ───────────────────────────────
                        # If ReActor fails due to any onnxruntime/CUDA issue, log
                        # gracefully and retry without face conditioning.
                        # Note: reactor_swapper.py is patched to CPUExecutionProvider
                        # to avoid CUDA 12.x vs 13.x DLL mismatch (WinError 1114).
                        is_cuda_error = (
                            "cublasLt64_12" in str(exc_msg) or
                            "WinError 1114" in str(exc_msg) or
                            "CUDA" in str(exc_type) or
                            ("onnxruntime" in str(exc_msg) and
                             ("cuda" in str(exc_msg).lower() or "provider" in str(exc_msg).lower()))
                        )
                        is_reactor_error = node_type and "ReActor" in node_type

                        if is_cuda_error and is_reactor_error:
                            cuda_error_detected = True
                            print(f"  [image_gen] ReActor error detected — retrying without face conditioning")
                            print(f"  [image_gen] Error: [{exc_type}] {str(exc_msg)[:120]}")
                            continue

                        # For non-ReActor/non-CUDA errors, print full error details
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

                # ReActor error: raise so generate() can retry without face conditioning
                if cuda_error_detected:
                    raise _ReactorCudaError(
                        "ReActor face-swap failed — retrying without face conditioning"
                    )

                # Return None to stop waiting (generation failed)
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

    @staticmethod
    def _is_bad_image(path: Path) -> bool:
        """
        Detect overexposed (near-white), blank, or NaN-artifact images produced
        by ComfyUI.  FLUX dev at high CFG can occasionally output a near-white
        or monochromatic blob when the latent contains NaN/Inf values.

        Thresholds:
          mean brightness > 242  — nearly all-white (overexposure)
          mean stddev < 8        — near-uniform colour (blank or solid-colour blob)
        """
        try:
            from PIL import Image as _PILI, ImageStat as _IStatMod
            img  = _PILI.open(path).convert("RGB")
            stat = _IStatMod.Stat(img)
            mean_br = sum(stat.mean)   / 3
            mean_sd = sum(stat.stddev) / 3
            return mean_br > 242 or mean_sd < 8
        except Exception:
            return False

    # ── Public generation interface ───────────────────────────────────────────

    def generate(
        self,
        art_prompt:    str,
        filename_stem: str,
        face_comfy_name: Optional[str] = None,   # already-uploaded ComfyUI filename
        face_gender:   str = "either",            # "male", "female", or "either"
        cancel_event=None,                        # threading.Event — set to stop generation mid-run
        card_type:     str = "",                  # type_line — used to keep people out of Land art
    ) -> Optional[Path]:
        if not self.available:
            return None

        save_path = Path(f"{filename_stem}.png")
        if save_path.exists():
            if not self._is_bad_image(save_path):
                return save_path
            # Cached file is a known-bad artifact — delete and regenerate
            save_path.unlink()
            print(f"  [image_gen] Stale overexposed/blank image deleted, regenerating: {save_path.name}")

        # Per-card LoRA rotation: pick one style stack for THIS card so a deck
        # doesn't render every card in an identical LoRA look.
        if self._lora_rotation:
            stack = random.choice(self._lora_rotation)
            self.active_loras        = stack["loras"]
            self.lora_trigger_prefix = stack["trigger_prefix"]
            print(f"  [image_gen] LoRA stack for this card: {stack['label']}")

        # Seed: fixed (reproducible) when the user pins one, else random per card.
        if self.gen.seed_mode == "fixed" and self.gen.seed is not None:
            seed = int(self.gen.seed)
        else:
            seed = random.randint(0, 2**32 - 1)
        # For FLUX, always use the preset-specific active_flux_prefix.
        # For SDXL/SD3.5, use active_flux_prefix only if the preset defined a
        # custom one (i.e. active_flux_prefix was overridden from _FLUX_PREFIX);
        # otherwise fall back to _SDXL_PREFIX which is tuned for high-CFG SDXL.
        if _is_flux(self.checkpoint):
            prefix = self.active_flux_prefix
        elif self.active_flux_prefix is not _FLUX_PREFIX:
            # Preset explicitly set a custom prefix for this SDXL/SD3.5 style
            prefix = self.active_flux_prefix
        else:
            prefix = _SDXL_PREFIX

        # ── Land cards: the location IS the subject, no people ──────────────────
        # Every style prefix says "character viewed from outside", which on a Land
        # makes FLUX insert a person into what should be a pure landscape. For lands
        # we flip that clause and append a strong no-people directive (with a city /
        # settlement exception, where structures are the subject — still no figures).
        is_land = "land" in (card_type or "").lower()
        land_suffix = ""
        if is_land:
            prefix = prefix.replace("character viewed from outside", "no people, no characters")
            land_suffix = (
                ". This is a LAND card: the terrain, structures and location ARE the sole subject. "
                "An unpopulated landscape — no people, no characters, no figures, no creatures in frame. "
                "If the location is a city or ruins, show the architecture itself from afar, still with no visible people."
            )

        # LoRA trigger words prepended first so CLIP weights them most heavily.
        # self.lora_trigger_prefix is "" when no MTG art LoRAs are installed.
        lora_prefix = self.lora_trigger_prefix

        # De-duplicate style words already present in the user's prompt. Without
        # this, a theme like "neon cyberpunk rave" + the cyberpunk preset repeats
        # "cyberpunk" across the trigger prefix AND the style flux_prefix, so the
        # LoRA over-dominates and the per-card mana-colour palette is ignored.
        # Unique LoRA trigger CODES (e.g. "kcyberpunk") are preserved so the LoRA
        # still fires; only redundant plain-English style words are stripped.
        _pw = _prompt_word_set(art_prompt)
        if _pw:
            _before = (lora_prefix, prefix)
            lora_prefix = _strip_trigger_prefix(lora_prefix, _pw)
            prefix = _dedup_style_words(prefix, _pw)
            if (lora_prefix, prefix) != _before:
                print(f"  [image_gen] de-duped style words already in prompt "
                      f"(trigger={_before[0]!r}->{lora_prefix!r})")

        # CRITICAL FIX: Face constraint must cooperate WITH themer's description, not override it.
        # The old code prepended a contradictory "Painted portrait of a person" that overrode
        # the mechanical soul (e.g., "destroying enemies"), causing FLUX artifacts (2 torches, black background).
        # Now: append face requirements AFTER the main description so the soul is established first.
        face_suffix = ""
        if face_comfy_name:
            _all_presets  = get_all_presets()
            _active_preset = _all_presets.get(self.art_style, {})
            _fp_quality = _active_preset.get("face_prefix_quality", "painterly skin tones")

            if face_gender == "male":
                _fp_subject = "a man"
            elif face_gender == "female":
                _fp_subject = "a woman"
            else:
                _fp_subject = "a person"

            # Append AFTER art_prompt so the mechanical soul is established first,
            # then add face requirements as additional constraints.
            #
            # IMPORTANT — keep the character ACTIVE. The face still needs to be a clear,
            # frontal-ish focal point (so PuLID/ReActor can find it), but phrasing it as
            # "upper body in frame, facing forward toward camera" produced stiff portraits
            # of a person standing and staring into nothing, overriding the card's action.
            # So: demand a prominent, well-lit face AND an engaged, mid-action moment.
            face_suffix = (
                f". The subject is {_fp_subject}; their face is a clear, well-lit focal point with "
                f"detailed expressive eyes and {_fp_quality}, turned toward the viewer at a three-quarter angle. "
                f"They are actively engaged in the scene — a dynamic, in-motion moment with intent and emotion, "
                f"NOT a stiff posed portrait and NOT standing blankly staring into the distance."
            )
            # ReActor needs a clearly detectable face to swap onto — keep it unobscured
            # and large enough, without collapsing the whole image into a head-and-shoulders shot.
            if self.face_method == "reactor":
                face_suffix += " Keep the face unobscured and prominent enough to read clearly."

        full_prompt = lora_prefix + prefix + art_prompt + face_suffix + land_suffix

        # Log the final prompt and settings so we can diagnose blurriness/LoRA issues
        print(f"  [image_gen] Prompt ({len(full_prompt)} chars): {full_prompt[:120]}{'...' if len(full_prompt) > 120 else ''}")
        print(f"  [image_gen] Negative ({len(self.active_negative)} chars): {self.active_negative[:100]}...")
        print(f"  [image_gen] Theme darkness: {self.theme_darkness:.2f}, LoRAs: {len(self.active_loras) if self.active_loras else 0}")

        def _build_and_run(attempt_seed: int) -> Optional[Path]:
            # Build workflow — face-conditioned if we have a reference.
            # Pass the preset-specific negative so anime / photorealism etc. can
            # actively push against FLUX's default photoreal prior.
            if face_comfy_name and self.face_method != "none":
                wf = self._build_face_workflow(full_prompt, attempt_seed, face_comfy_name)
            else:
                wf = _build_workflow(self.checkpoint, full_prompt, attempt_seed,
                                     negative=self.active_negative, gen=self.gen)

            # Insert LoRA nodes into workflow (chains model + clip through each LoRA).
            # Dark-only LoRAs have their strength scaled by self.theme_darkness so
            # light/whimsical themes aren't dragged into grim dark-fantasy territory.
            # LoRAs are skipped for schnell — all current LoRAs are dev-trained and
            # incompatible with schnell's distillation; applying them produces
            # incoherent output. schnell runs prompt-only.
            _is_schnell_ckpt = "schnell" in (self.checkpoint or "").lower()
            _is_flux_model = _is_flux(self.checkpoint)
            _is_sdxl_model = not _is_flux_model and not _is_sd35(self.checkpoint or "")

            # Turbo distillation LoRA rides on top of the style stack (flux-dev only).
            effective_loras = list(self.active_loras or [])
            if self._turbo_lora and _is_flux_model and not _is_schnell_ckpt:
                effective_loras = [self._turbo_lora] + effective_loras

            if effective_loras and (_is_flux_model or _is_sdxl_model) and not _is_schnell_ckpt:
                scaled: list[dict] = []
                for entry in effective_loras:
                    if entry.get("dark_only") and self.theme_darkness < 1.0:
                        scaled.append({
                            **entry,
                            "model_strength": round(entry["model_strength"] * self.theme_darkness, 3),
                            "clip_strength":  round(entry["clip_strength"]  * self.theme_darkness, 3),
                        })
                    else:
                        scaled.append(entry)
                # Checkpoint node ID varies by model:
                #   FLUX workflows: node "1"
                #   SDXL workflows: node "4"
                checkpoint_node = "1" if _is_flux_model else "4"
                wf = _insert_loras(wf, checkpoint_node, scaled)

            # Log LoRA chain so we can spot missing/wrong filenames immediately
            lora_nodes = {nid: n for nid, n in wf.items()
                          if n.get("class_type") == "LoraLoader"}
            if lora_nodes:
                for nid, n in lora_nodes.items():
                    inp = n.get("inputs", {})
                    print(f"  [image_gen] LoRA node {nid}: {inp.get('lora_name')}  "
                          f"model={inp.get('strength_model')} clip={inp.get('strength_clip')}")

            pid = self._queue_prompt(wf)
            print(f"  [image_gen] Queued {pid} (face={'yes' if face_comfy_name else 'no'}), waiting...")
            img_info = self._wait_for_image(pid, cancel_event=cancel_event)
            if not img_info:
                return None
            if self._download_image(img_info, save_path):
                return save_path
            return None

        try:
            result = _build_and_run(seed)
            if result and self._is_bad_image(result):
                # First attempt produced overexposed/blank output — retry once with a new seed
                result.unlink()
                print(f"  [image_gen] Overexposed/blank on attempt 1, retrying with new seed…")
                seed2  = random.randint(0, 2**32 - 1)
                result = _build_and_run(seed2)
                if result and self._is_bad_image(result):
                    result.unlink()
                    print(f"  [image_gen] Both attempts produced bad output — "
                          f"Scryfall art will be used as fallback for '{filename_stem}'")
                    return None
            return result
        except _ReactorCudaError as e:
            # ReActor face-swap failed due to CUDA mismatch — retry this card
            # without face conditioning so we at least get a styled base image
            # rather than losing it to Scryfall art entirely.
            print(f"  [image_gen] {e}")
            if face_comfy_name:
                print(f"  [image_gen] Retrying '{filename_stem}' without face conditioning…")
                return self.generate(
                    art_prompt, filename_stem,
                    face_comfy_name=None,
                    face_gender=face_gender,
                    card_type=card_type,
                    cancel_event=cancel_event,
                )
            return None
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
                negative=neg, gen=self.gen,
            )
        if self.face_method == "ipadapter_faceid":
            return _build_faceid_sdxl_workflow(
                self.checkpoint, positive, seed, face_comfy_name,
                "", "",  # preset-based, no explicit model file paths needed
                negative=neg,
            )
        if self.face_method == "reactor":
            base = _build_workflow(self.checkpoint, positive, seed, negative=neg, gen=self.gen)
            return _append_reactor(
                base, face_comfy_name,
                swap_model=self.face_info.get("swap_model", "inswapper_128.onnx"),
                restore_model=self.face_info.get("restore_model", "codeformer-v0.1.0.pth"),
            )
        # Should not reach here
        return _build_workflow(self.checkpoint, positive, seed, negative=neg, gen=self.gen)

    def generate_deck(
        self,
        themed_commander,
        themed_deck: list,
        deck_name: str,
        face_paths: Optional[list[Path]] = None,   # commander face photos (1 person)
        crew_paths: Optional[list[Path]] = None,   # crew photos (multiple people for creature cards)
        face_gender: str = "either",               # gender hint for commander face
        crew_gender: str = "either",               # gender hint for crew faces
        crew_prompt: str = "",                     # shared appearance notes for crew-faced creatures
        progress_callback=None,                    # callable(i, total, name, has_face, elapsed, success)
        theme_str: str = "",                       # human-readable theme for LoRA darkness scaling
        card_done_callback=None,                   # callable(tc, art_path) — called after each card renders
        cancel_event=None,                         # threading.Event — set to stop mid-run
    ) -> dict[str, Optional[Path]]:
        if not self.available:
            return {}

        # Compute theme darkness once for the whole deck.
        # Prefer the explicit theme_str (most representative); when absent, sample
        # the deck name + up to 5 card prompts so a single neutral first-card prompt
        # doesn't misrepresent a dark or whimsical deck.
        if theme_str:
            hint = theme_str
        else:
            _sample_prompts = [tc.art_prompt for tc in themed_deck[:5] if tc.art_prompt]
            hint = " ".join(filter(None, [deck_name] + _sample_prompts))
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
        elif _is_sdxl(self.checkpoint):
            kind = "SDXL"
        else:
            kind = "Unknown"
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

            card_uses_crew = False
            if is_cmd and face_comfy_name:
                card_face_name   = face_comfy_name
                card_face_gender = face_gender
                face_tag_card    = "[👑]"
            elif not is_cmd and crew_comfy_names and is_human_card(tc.card.get("type_line", "")):
                card_face_name   = crew_comfy_names[crew_card_idx % len(crew_comfy_names)]
                card_face_gender = crew_gender
                crew_card_idx   += 1
                card_uses_crew   = True
                face_tag_card    = f"[👥{(crew_card_idx - 1) % len(crew_comfy_names) + 1}]"
            else:
                face_tag_card = "    "

            # Crew appearance: inject the shared crew notes (tattoos, outfit, etc.)
            # into crew-faced creature cards — mirrors how commander_prompt carries
            # the commander's look (face-swap only carries the face, not body art).
            card_art_prompt = tc.art_prompt
            if card_uses_crew and crew_prompt.strip():
                card_art_prompt = (f"{crew_prompt.strip()}, {tc.art_prompt}"
                                   if tc.art_prompt else crew_prompt.strip())

            print(f"  [{i:>3}/{total}] {face_tag_card} {tc.themed_name:<33}", end=" ", flush=True)

            t0   = time.monotonic()
            path = self.generate(
                card_art_prompt, str(out),
                face_comfy_name=card_face_name,
                face_gender=card_face_gender,
                cancel_event=cancel_event,
                card_type=tc.card.get("type_line", ""),
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
