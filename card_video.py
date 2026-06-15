"""
card_video.py — OPTIONAL "animate card" enrichment via a local ComfyUI
image-to-video (I2V) model.

╔══════════════════════════════════════════════════════════════════════════════╗
║  WHAT THIS DOES                                                                ║
║                                                                                ║
║  Given a card's still ART crop, run a ComfyUI I2V model to produce a short     ║
║  sequence of frames (subtle "cinemagraph" motion). The caller then composites  ║
║  each frame back through card_renderer.render_card_frames() so the frame /     ║
║  text / mana symbols stay crisp and only the art moves, and finally encodes a  ║
║  seamless looping MP4 (see encode_loop_mp4).                                   ║
║                                                                                ║
║  ZERO-LIABILITY / SUPPLY-YOUR-OWN-MODEL DESIGN                                 ║
║  Ships NO video weights. Like Hunyuan3D / LoRAs, the user installs an I2V      ║
║  model + nodes into their own ComfyUI. We AUTO-DETECT which is present         ║
║  (LTX-Video or Wan 2.x, both ship as ComfyUI-core nodes) and gate on it via    ║
║  health_check(). If nothing usable is installed, the feature stays disabled.   ║
║                                                                                ║
║  The default workflow graphs below are best-effort for stock ComfyUI core.     ║
║  Node inputs drift between ComfyUI versions, so a user can override the whole  ║
║  graph with their own API-format JSON (placeholders documented in             ║
║  _PLACEHOLDERS) via MYTHFORGE_VIDEO_WORKFLOW_<METHOD> or a file in             ║
║  card_assets/video_workflows/.                                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import requests
from PIL import Image

# Reuse ComfyUI connection conventions from the 3D module (same install).
from model3d import _comfy_base, _comfy_models_dir, _COMFY_OUTPUT_DIR

# ── Poll / timeout ────────────────────────────────────────────────────────────
_POLL_INTERVAL = 2.0
_OUTPUT_TIMEOUT = float(os.environ.get("MYTHFORGE_VIDEO_TIMEOUT", "600"))  # 10 min

# Where optional user-supplied workflow templates live (override the defaults).
_WORKFLOW_DIR = Path("card_assets") / "video_workflows"

# Placeholder tokens substituted into a workflow template (default or override).
_PLACEHOLDERS = {
    "image":    "__IMAGE__",     # ComfyUI input filename of the source art
    "positive": "__POSITIVE__",  # motion prompt
    "negative": "__NEGATIVE__",
    "width":    "__WIDTH__",
    "height":   "__HEIGHT__",
    "length":   "__LENGTH__",    # frame count
    "fps":      "__FPS__",        # PLAYBACK frame rate (encode timing / smoothness)
    "cond_fps": "__COND_FPS__",   # LTXV CONDITIONING frame rate — the motion lever
                                  # (lower = more motion); decoupled from playback fps
    "seed":     "__SEED__",
    "model":    "__MODEL__",     # resolved checkpoint/unet filename
    "clip":     "__CLIP__",      # Wan: umt5 text encoder
    "vae":      "__VAE__",       # Wan: vae
    "clipvis":  "__CLIPVIS__",   # Wan: clip-vision
    "prefix":   "__PREFIX__",    # SaveImage filename_prefix
}


# ── Motion presets (combined with each card's own art_prompt) ─────────────────
# Each value is the MOTION clause fed to the I2V model.  Keep them ambient or
# camera-driven and ALWAYS pin the subject ("subject stays still"): LTXV/Wan warp
# the figure on large/structural motion, so action verbs (swings, runs, casts)
# belong in neither the presets nor a sane custom prompt.  Grouped subtle→stronger.
_MOTION_PRESETS: dict[str, str] = {
    # ── Ambient ──
    "subtle":  "subtle cinemagraph, gentle ambient motion, the subject stays still, "
               "only soft background drift and faint light flicker",
    "elements": "drifting embers and smoke, flowing water, swaying cloth and hair, "
                "shimmering magical energy, subject mostly still",
    "shimmer": "shimmering light, glints and sparkles drifting across the scene, "
               "subtle glow pulsing, subject still",
    "breathing": "living portrait, the subject breathes slowly and blinks, the faintest "
                 "idle sway, everything else still, no pose change",
    # ── Atmosphere / weather ──
    "rain":   "steady rain falling, wet reflective sheen and dripping water, "
              "subtle mist, subject stays still",
    "snow":   "soft snow or ash gently falling and drifting, cold still air, "
              "subject stays still",
    "fog":    "low fog and mist slowly rolling through the scene, volumetric haze "
              "drifting, subject stays still",
    "fire":   "flickering firelight and glowing embers, warm light dancing across "
              "the scene, subject stays still",
    # ── Camera moves (I2V's most reliable) ──
    "push_in": "very slow cinematic camera push-in with parallax depth, "
               "subject stays still, gentle atmospheric motion",
    "pull_back": "very slow cinematic camera pull-back reveal with parallax depth, "
                 "subject stays still, gentle atmospheric motion",
    "pan":    "slow cinematic camera pan drifting across the scene with parallax, "
              "subject stays still",
    "orbit":  "gentle cinematic parallax, foreground and background layers separate "
              "as the view sways slightly, subject stays still",
    # ── Energy / FX (spells, artifacts) ──
    "arcane": "pulsing magical glow, runes and energy flickering and breathing with "
              "light, subject stays still",
    "energy": "crackling energy and drifting sparks arcing across the scene, "
              "electric glow flickering, subject stays still",
}
_DEFAULT_PRESET = "subtle"

# Appended to a CUSTOM motion prompt to keep the subject from morphing — the same
# guarantee every built-in preset carries.
_CUSTOM_MOTION_GUARD = "the subject stays still with no pose change, only the described motion"

_NEG_PROMPT = ("morphing, warping, distortion, deformed, flickering identity, "
               "jitter, text, watermark, fast motion, scene cut, duplicate subject")


def motion_presets() -> list[dict]:
    """Preset list for the UI (key + human label), grouped for the dropdown."""
    labels = {
        "subtle": "Subtle cinemagraph", "elements": "Drifting elements",
        "shimmer": "Shimmer & glints", "breathing": "Living portrait (breathe & blink)",
        "rain": "Rain & wet sheen", "snow": "Falling snow / ash",
        "fog": "Rolling fog & mist", "fire": "Flickering firelight",
        "push_in": "Camera: slow push-in", "pull_back": "Camera: pull-back reveal",
        "pan": "Camera: slow pan", "orbit": "Camera: parallax sway",
        "arcane": "Arcane pulse & runes", "energy": "Crackling energy",
    }
    return [{"key": k, "label": labels.get(k, k)} for k in _MOTION_PRESETS]


def build_motion_prompt(preset: str, art_prompt: str = "", custom: str = "") -> str:
    """Build the I2V motion prompt.

    A non-empty ``custom`` free-text description wins over ``preset`` (the user
    typed exactly what they want) and is anchored with the subject-stays-still
    guard so it doesn't morph the figure. Either way the card's own ``art_prompt``
    is appended as the Scene so motion fits without re-describing it.
    """
    custom = (custom or "").strip()
    if custom:
        base = f"{custom[:300]}, {_CUSTOM_MOTION_GUARD}"
    else:
        base = _MOTION_PRESETS.get(preset or _DEFAULT_PRESET, _MOTION_PRESETS[_DEFAULT_PRESET])
    art = (art_prompt or "").strip()
    if art:
        # Trim the art prompt so the motion clause stays dominant.
        art = art[:400]
        return f"{base}. Scene: {art}"
    return base


# ── I2V method registry ───────────────────────────────────────────────────────
# Each method: the ComfyUI node class(es) that MUST be present to use it, a
# default frame geometry, and the disk fragments used to find its model file(s).
_VIDEO_METHODS: dict[str, dict] = {
    # LTX-Video — single checkpoint, ComfyUI-core nodes. Light + fast: the
    # recommended starting point on a 24 GB card.
    "ltxv": {
        "label":  "LTX-Video",
        "nodes":  ["LTXVImgToVideo"],
        "dims":   (768, 512),
        "length": 49,            # LTXV likes 8n+1
        "fps":    24,
        # T5 text encoder is loaded SEPARATELY (CLIPLoader type="ltxv"), not
        # bundled in the LTXV checkpoint — so it's a required model slot.
        "models": {"ckpt": ["ltx-video", "ltxv", "ltx"], "clip": ["t5xxl"]},
        "model_dirs": {"ckpt": ["checkpoints", "diffusion_models"],
                       "clip": ["text_encoders", "clip", "t5"]},
    },
    # Wan 2.x I2V — heavier (separate unet/clip/vae/clip-vision), ComfyUI-core
    # nodes. Higher motion quality.
    "wan": {
        "label":  "Wan 2.x",
        "nodes":  ["WanImageToVideo"],
        "dims":   (832, 480),
        "length": 33,
        "fps":    16,
        "models": {
            "unet": ["wan", "i2v"], "clip": ["umt5"],
            "vae": ["wan", "vae"], "clipvis": ["clip_vision", "clip-vision"],
        },
        "model_dirs": {"unet": ["diffusion_models", "unet"], "clip": ["text_encoders", "clip"],
                       "vae": ["vae"], "clipvis": ["clip_vision"]},
    },
}
_METHOD_ORDER = ["ltxv", "wan"]   # preference, NOT a hard default


# ── Clip-length (duration) configuration ──────────────────────────────────────
# Duration is exposed in the UI as "clip length" (seconds) and converted to a
# frame count here.  I2V models like a frame count of the form k*n+1 (LTXV→8n+1,
# Wan→4n+1); off-multiple lengths can drop or duplicate the last frames.  Motion
# is range-limited because I2V temporal coherence degrades and VRAM/time grow with
# length; the procedural foil sweep is cheap so it allows longer loops.
_FRAME_SNAP = {"ltxv": 8, "wan": 4}     # frame count best expressed as k*n + 1
MOTION_MIN_S, MOTION_MAX_S = 1.0, 6.0   # I2V art-motion clip-length bounds (sec)
FOIL_MIN_S,   FOIL_MAX_S   = 1.0, 10.0  # procedural foil loop bounds (sec)
FPS_OPTIONS = [12, 16, 24, 30]          # selectable frame rates (smoothness)
_FOIL_DEFAULT_S = 3.0
_MOTION_DEFAULT_S = 2.0

# Motion strength (art-motion / LTXV only). LTX-Video's *conditioning* frame_rate
# is the motion lever: the model assumes that much time passes between frames, so
# a LOWER conditioning fps packs MORE motion per frame. We map a 0..1 strength to
# a conditioning fps in [_MOTION_COND_FPS_MIN.._MAX] (inverted), DECOUPLED from the
# playback fps (which only controls encode smoothness). Wan has no equivalent knob
# in the default graph, so motion_strength is a no-op there.
MOTION_STRENGTH_DEFAULT = 0.5
# Wide range: LTXV motion scales hard only at low conditioning fps, so a narrow
# band (e.g. 17–27) is barely perceptible. 8 fps ≈ the clip spans ~6 s of "real
# time" over its frames → lots of motion; 30 fps → ~1.5 s → very subtle.
_MOTION_COND_FPS_MIN = 8    # strength 1.0 → strongest motion
_MOTION_COND_FPS_MAX = 30   # strength 0.0 → most subtle


def _ltxv_cond_fps(strength: float) -> int:
    """Map motion strength 0..1 → LTXV conditioning frame_rate (inverted: lower fps
    = more motion). 0 → 30 (subtle), 0.5 → 22, 1 → 14 (strong)."""
    s = max(0.0, min(1.0, float(strength)))
    return int(round(_MOTION_COND_FPS_MAX - s * (_MOTION_COND_FPS_MAX - _MOTION_COND_FPS_MIN)))


def frames_for_duration(method: Optional[str], seconds: float, fps: int,
                        *, foil: bool = False) -> int:
    """Convert a desired clip length (seconds) to a frame count.

    For I2V motion the result is clamped to the method's safe range and snapped to
    the nearest k*n+1 the model prefers.  For the procedural foil sweep any count
    is fine, so it's just round(seconds*fps) within the foil bounds.
    """
    fps = max(1, int(fps or 24))
    lo, hi = (FOIL_MIN_S, FOIL_MAX_S) if foil else (MOTION_MIN_S, MOTION_MAX_S)
    seconds = max(lo, min(hi, float(seconds)))
    raw = max(2, int(round(seconds * fps)))
    if foil:
        return raw
    k = _FRAME_SNAP.get(method or "", 1)
    if k > 1:
        n = max(1, round((raw - 1) / k))
        return k * n + 1
    return raw


def video_caps() -> dict:
    """Duration / frame-rate capability ranges surfaced to the UI so the clip-length
    slider and FPS selector show valid bounds per effect."""
    return {
        "motion": {"min_s": MOTION_MIN_S, "max_s": MOTION_MAX_S, "default_s": _MOTION_DEFAULT_S},
        "foil":   {"min_s": FOIL_MIN_S,   "max_s": FOIL_MAX_S,   "default_s": _FOIL_DEFAULT_S},
        "fps_options": list(FPS_OPTIONS),
        "motion_strength_default": MOTION_STRENGTH_DEFAULT,
    }


def _available_nodes(comfy_base: Optional[str] = None) -> set[str]:
    base = comfy_base or _comfy_base()
    try:
        r = requests.get(f"{base}/object_info", timeout=15)
        if r.status_code == 200:
            return set(r.json().keys())
    except Exception:
        pass
    return set()


def _find_model_file(fragments: list[str], subdirs: list[str]) -> Optional[str]:
    """First model file under models/<subdir> whose name contains all-or-any of
    the fragments. Returns the ComfyUI-relative name (what the loader expects)."""
    base = _comfy_models_dir()
    for sub in subdirs:
        d = base / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() not in (".safetensors", ".gguf", ".ckpt", ".pt", ".sft"):
                continue
            name = p.name.lower()
            if any(frag.lower() in name for frag in fragments):
                return str(p.relative_to(d)).replace("\\", "/")
    return None


def _resolve_models(method: str) -> dict:
    """Map each required model slot → installed filename (or None if missing)."""
    spec = _VIDEO_METHODS[method]
    out: dict[str, Optional[str]] = {}
    for slot, frags in spec["models"].items():
        out[slot] = _find_model_file(frags, spec["model_dirs"][slot])
    return out


def detect_method(comfy_base: Optional[str] = None) -> Optional[str]:
    """First registered I2V method whose required nodes AND model files are all
    present. Preference order, but neither is a forced default."""
    nodes = _available_nodes(comfy_base)
    if not nodes:
        return None
    for method in _METHOD_ORDER:
        spec = _VIDEO_METHODS[method]
        if not all(n in nodes for n in spec["nodes"]):
            continue
        models = _resolve_models(method)
        if all(models.values()):
            return method
    return None


def health_check() -> dict:
    """{ok, message, hint, method, methods, models} — mirrors Model3DGen.health_check."""
    base = _comfy_base()
    # 1. ComfyUI reachable
    try:
        r = requests.get(f"{base}/system_stats", timeout=5)
        if r.status_code != 200:
            raise RuntimeError(f"status {r.status_code}")
    except Exception as e:
        return {"ok": False, "method": None, "methods": [],
                "message": "ComfyUI not reachable.",
                "hint": f"Start ComfyUI on {base} (port 8188). ({e})", "models": {}}

    nodes = _available_nodes(base)
    present = [m for m in _METHOD_ORDER
               if all(n in nodes for n in _VIDEO_METHODS[m]["nodes"])]
    if not present:
        return {"ok": False, "method": None, "methods": [],
                "message": "No image-to-video nodes found in ComfyUI.",
                "hint": "Update ComfyUI (LTX-Video and Wan I2V ship as core nodes) "
                        "or install an I2V custom-node pack.", "models": {}}

    # 2/3. A present method must also have its model file(s) on disk
    for method in present:
        models = _resolve_models(method)
        if all(models.values()):
            return {"ok": True, "method": method, "methods": present,
                    "message": f"Ready ({_VIDEO_METHODS[method]['label']}).",
                    "hint": "", "models": models}

    miss = {m: _resolve_models(m) for m in present}
    return {"ok": False, "method": None, "methods": present,
            "message": "I2V nodes present but model weights are missing.",
            "hint": "Download the model files for one of: "
                    + ", ".join(_VIDEO_METHODS[m]["label"] for m in present)
                    + " into ComfyUI/models/.", "models": miss}


# ── Workflow templates (default, override-able) ───────────────────────────────
def _default_ltxv_template() -> dict:
    P = _PLACEHOLDERS
    return {
        "1":  {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": P["model"]}},
        "2":  {"class_type": "CLIPLoader", "inputs": {"clip_name": P["clip"], "type": "ltxv"}},
        "3":  {"class_type": "CLIPTextEncode", "inputs": {"text": P["positive"], "clip": ["2", 0]}},
        "4":  {"class_type": "CLIPTextEncode", "inputs": {"text": P["negative"], "clip": ["2", 0]}},
        "5":  {"class_type": "LoadImage", "inputs": {"image": P["image"]}},
        "6":  {"class_type": "LTXVImgToVideo", "inputs": {
                   "positive": ["3", 0], "negative": ["4", 0], "vae": ["1", 2],
                   "image": ["5", 0], "width": P["width"], "height": P["height"],
                   "length": P["length"], "batch_size": 1, "strength": 1.0}},
        "7":  {"class_type": "LTXVConditioning", "inputs": {
                   "positive": ["6", 0], "negative": ["6", 1], "frame_rate": P["cond_fps"]}},
        "8":  {"class_type": "KSampler", "inputs": {
                   "model": ["1", 0], "positive": ["7", 0], "negative": ["7", 1],
                   "latent_image": ["6", 2], "seed": P["seed"], "steps": 30,
                   "cfg": 3.0, "sampler_name": "euler", "scheduler": "normal",
                   "denoise": 1.0}},
        "9":  {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["1", 2]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0],
                                                     "filename_prefix": P["prefix"]}},
    }


def _default_wan_template() -> dict:
    P = _PLACEHOLDERS
    return {
        "1":  {"class_type": "UNETLoader", "inputs": {"unet_name": P["model"],
                                                      "weight_dtype": "default"}},
        "2":  {"class_type": "CLIPLoader", "inputs": {"clip_name": P["clip"], "type": "wan"}},
        "3":  {"class_type": "VAELoader", "inputs": {"vae_name": P["vae"]}},
        "4":  {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": P["clipvis"]}},
        "5":  {"class_type": "LoadImage", "inputs": {"image": P["image"]}},
        "6":  {"class_type": "CLIPVisionEncode", "inputs": {
                   "clip_vision": ["4", 0], "image": ["5", 0], "crop": "none"}},
        "7":  {"class_type": "CLIPTextEncode", "inputs": {"text": P["positive"], "clip": ["2", 0]}},
        "8":  {"class_type": "CLIPTextEncode", "inputs": {"text": P["negative"], "clip": ["2", 0]}},
        "9":  {"class_type": "WanImageToVideo", "inputs": {
                   "positive": ["7", 0], "negative": ["8", 0], "vae": ["3", 0],
                   "clip_vision_output": ["6", 0], "start_image": ["5", 0],
                   "width": P["width"], "height": P["height"], "length": P["length"],
                   "batch_size": 1}},
        "10": {"class_type": "KSampler", "inputs": {
                   "model": ["1", 0], "positive": ["9", 0], "negative": ["9", 1],
                   "latent_image": ["9", 2], "seed": P["seed"], "steps": 20,
                   "cfg": 6.0, "sampler_name": "uni_pc", "scheduler": "simple",
                   "denoise": 1.0}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0],
                                                     "filename_prefix": P["prefix"]}},
    }


_DEFAULT_TEMPLATES = {"ltxv": _default_ltxv_template, "wan": _default_wan_template}


def _load_template(method: str) -> dict:
    """User override (env var, then card_assets/video_workflows/<method>.json),
    else the bundled default graph."""
    env = os.environ.get(f"MYTHFORGE_VIDEO_WORKFLOW_{method.upper()}", "").strip()
    candidates = [Path(env)] if env else []
    candidates.append(_WORKFLOW_DIR / f"{method}.json")
    for p in candidates:
        try:
            if p and p.is_file():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [card_video] bad workflow template {p}: {e}")
    return _DEFAULT_TEMPLATES[method]()


def _fill(template: dict, subs: dict) -> dict:
    """Replace any value that EXACTLY equals a placeholder token with its
    (already correctly-typed) substitution, recursing the workflow structure.
    Structural recursion — not JSON-string replace — so a prompt containing
    quotes or backslashes can't corrupt the workflow JSON, and numeric slots
    keep their int type from `subs`."""
    def rec(o):
        if isinstance(o, dict):
            return {k: rec(v) for k, v in o.items()}
        if isinstance(o, list):
            return [rec(v) for v in o]
        if isinstance(o, str) and o in subs:
            return subs[o]
        return o
    return rec(template)


def build_workflow(method: str, image_comfy_name: str, motion_prompt: str,
                   prefix: str, *, frames: int, fps: int, w: int, h: int,
                   seed: int, models: dict,
                   motion_strength: float = MOTION_STRENGTH_DEFAULT) -> dict:
    # Motion strength → LTXV conditioning frame_rate (decoupled from playback fps).
    # Other methods have no conditioning-fps lever, so fall back to playback fps
    # (a no-op for their graphs, which don't reference __COND_FPS__).
    cond_fps = _ltxv_cond_fps(motion_strength) if method == "ltxv" else fps
    subs = {
        _PLACEHOLDERS["image"]: image_comfy_name,
        _PLACEHOLDERS["positive"]: motion_prompt,
        _PLACEHOLDERS["negative"]: _NEG_PROMPT,
        _PLACEHOLDERS["width"]: w, _PLACEHOLDERS["height"]: h,
        _PLACEHOLDERS["length"]: frames, _PLACEHOLDERS["fps"]: fps,
        _PLACEHOLDERS["cond_fps"]: cond_fps,
        _PLACEHOLDERS["seed"]: seed, _PLACEHOLDERS["prefix"]: prefix,
        _PLACEHOLDERS["model"]: models.get("ckpt") or models.get("unet") or "",
        _PLACEHOLDERS["clip"]: models.get("clip") or "",
        _PLACEHOLDERS["vae"]: models.get("vae") or "",
        _PLACEHOLDERS["clipvis"]: models.get("clipvis") or "",
    }
    return _fill(_load_template(method), subs)


# ── ComfyUI submit / poll / collect ───────────────────────────────────────────
def _upload_image(image_path: Path, comfy_base: str) -> str:
    with image_path.open("rb") as f:
        r = requests.post(f"{comfy_base}/upload/image",
                          files={"image": (image_path.name, f, "image/png")},
                          data={"subfolder": "mtg_anim", "type": "input", "overwrite": "true"},
                          timeout=20)
    r.raise_for_status()
    j = r.json()
    sub = j.get("subfolder", "")
    return f"{sub}/{j['name']}" if sub else j["name"]


def _submit(workflow: dict, comfy_base: str) -> str:
    r = requests.post(f"{comfy_base}/prompt",
                      json={"prompt": workflow, "client_id": str(uuid.uuid4())},
                      timeout=15)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"ComfyUI /prompt rejected: {r.status_code} {r.text[:400]}")
    return r.json()["prompt_id"]


def _wait(prompt_id: str, comfy_base: str,
          progress_cb: Optional[Callable[[str], None]] = None,
          timeout: float = _OUTPUT_TIMEOUT) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{comfy_base}/history/{prompt_id}", timeout=10)
            if r.status_code == 200:
                entry = r.json().get(prompt_id, {})
                if entry:
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        err = next((m[1].get("exception_message", str(m)) for m in msgs
                                    if m[0] == "execution_error"), "unknown error")
                        raise RuntimeError(f"ComfyUI execution error: {err}")
                    if status.get("completed", False):
                        return entry.get("outputs", {})
        except RuntimeError:
            raise
        except Exception as e:
            print(f"  [card_video] poll error: {e}")
        if progress_cb:
            progress_cb("Generating motion…")
        time.sleep(_POLL_INTERVAL)
    raise RuntimeError(f"I2V generation timed out after {timeout}s")


def _collect_frames(outputs: dict) -> list[Image.Image]:
    """Read the SaveImage frame PNGs from ComfyUI's output dir, in order."""
    items: list[tuple[str, str]] = []
    for node_out in outputs.values():
        for it in node_out.get("images", []):
            if isinstance(it, dict) and it.get("type") == "output":
                items.append((it.get("subfolder", ""), it.get("filename", "")))
    items.sort(key=lambda t: t[1])      # SaveImage suffixes _00001_, _00002_, …
    frames = []
    for sub, fn in items:
        p = _COMFY_OUTPUT_DIR / sub / fn
        if p.exists():
            img = Image.open(p)
            img.load()
            frames.append(img.convert("RGBA"))
    return frames


def animate(image_path: Path, motion_prompt: str, *, method: Optional[str] = None,
            frames: Optional[int] = None, fps: Optional[int] = None,
            motion_strength: float = MOTION_STRENGTH_DEFAULT,
            seed: int = 0, progress_cb: Optional[Callable[[str], None]] = None,
            ) -> list[Image.Image]:
    """Run I2V on a still image; return the generated art frames (PIL RGBA).
    `motion_strength` (0..1) drives how much the art moves (LTXV only). Raises if
    no usable method is installed."""
    comfy_base = _comfy_base()
    method = method or detect_method(comfy_base)
    if method is None:
        raise RuntimeError("No image-to-video model available in ComfyUI.")
    spec = _VIDEO_METHODS[method]
    w, h = spec["dims"]
    n = frames or spec["length"]
    f = fps or spec["fps"]
    models = _resolve_models(method)

    comfy_name = _upload_image(image_path, comfy_base)
    prefix = f"mtg_anim/{image_path.stem}_{uuid.uuid4().hex[:8]}"
    wf = build_workflow(method, comfy_name, motion_prompt, prefix,
                        frames=n, fps=f, w=w, h=h, seed=seed, models=models,
                        motion_strength=motion_strength)
    pid = _submit(wf, comfy_base)
    outputs = _wait(pid, comfy_base, progress_cb=progress_cb)
    art_frames = _collect_frames(outputs)
    # Frames are loaded into memory (img.load() above), so the ComfyUI output
    # PNGs + the uploaded source are now disposable — clean them so a full-deck
    # animation doesn't leave thousands of stray files in ComfyUI's dirs.
    _cleanup_comfy_files(prefix, comfy_name)
    if not art_frames:
        raise RuntimeError("I2V produced no frames (check the ComfyUI workflow).")
    return art_frames


def _cleanup_comfy_files(prefix: str, comfy_name: str) -> None:
    """Delete this run's SaveImage output frames + the uploaded input image."""
    import glob
    try:
        for fp in glob.glob(str(_COMFY_OUTPUT_DIR / (prefix + "*"))):
            try:
                os.remove(fp)
            except OSError:
                pass
        inp = _COMFY_OUTPUT_DIR.parent / "input" / comfy_name
        if inp.exists():
            inp.unlink()
    except Exception:
        pass   # best-effort cleanup; never fail the animation over leftovers


# ── Looping + MP4 encode ──────────────────────────────────────────────────────
def ping_pong(frames: list, loop: bool = True) -> list:
    """Boomerang a sequence into a seamless loop (forward then reverse, without
    duplicating the two endpoints). Pass loop=False to keep the raw sequence."""
    if not loop or len(frames) < 3:
        return list(frames)
    return list(frames) + list(frames[-2:0:-1])


def encode_loop_mp4(frames: list, out_path: Path, *, fps: int = 24,
                    loop: bool = True) -> Path:
    """Encode card frames (PIL images, 750×1050) to a looping H.264 MP4."""
    import imageio.v2 as imageio

    seq = ping_pong(frames, loop=loop)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        str(out_path), fps=fps, codec="libx264", quality=8,
        macro_block_size=1, pixelformat="yuv420p",
        ffmpeg_params=["-movflags", "+faststart"],
    )
    try:
        for fr in seq:
            writer.append_data(_as_rgb(fr))
    finally:
        writer.close()
    return out_path


def encode_loop_webp(frames: list, out_path: Path, *, fps: int = 24,
                     loop: bool = True) -> Path:
    """Encode card frames to an animated WebP (alpha preserved, infinite loop)."""
    seq = ping_pong(frames, loop=loop)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    imgs = [fr.convert("RGBA") for fr in seq]
    dur = max(1, int(round(1000.0 / max(1, fps))))
    imgs[0].save(str(out_path), format="WEBP", save_all=True,
                 append_images=imgs[1:], duration=dur, loop=0,
                 lossless=False, quality=82, method=4)
    return out_path


def encode_loop_gif(frames: list, out_path: Path, *, fps: int = 24,
                    loop: bool = True) -> Path:
    """Encode card frames to an animated GIF (256-colour, infinite loop). GIF
    has no real alpha, so transparent corners are flattened onto black."""
    seq = ping_pong(frames, loop=loop)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    imgs = [_as_rgb_img(fr) for fr in seq]
    dur = max(20, int(round(1000.0 / max(1, fps))))   # GIF granularity is ~10ms
    imgs[0].save(str(out_path), format="GIF", save_all=True,
                 append_images=imgs[1:], duration=dur, loop=0,
                 optimize=True, disposal=2)
    return out_path


# Animation output formats == file extensions. mp4 is the default; webp keeps
# alpha and is the smallest high-quality option; gif is the most portable.
VIDEO_FORMATS: tuple[str, ...] = ("mp4", "webp", "gif")
_FORMAT_ENCODERS = {
    "mp4":  encode_loop_mp4,
    "webp": encode_loop_webp,
    "gif":  encode_loop_gif,
}


def format_options() -> list[dict]:
    """Format list for the UI (key + human label)."""
    labels = {"mp4": "MP4 (H.264 video)", "webp": "Animated WebP",
              "gif": "Animated GIF"}
    return [{"key": k, "label": labels[k]} for k in VIDEO_FORMATS]


def encode_loop(frames: list, out_path: Path, *, fmt: str = "mp4", fps: int = 24,
                loop: bool = True) -> Path:
    """Encode card frames to ``fmt`` (mp4 / webp / gif). ``out_path`` should
    already carry the matching suffix (callers own the filename)."""
    enc = _FORMAT_ENCODERS.get((fmt or "mp4").lower())
    if enc is None:
        raise ValueError(f"Unsupported animation format: {fmt!r} "
                         f"(expected one of {', '.join(VIDEO_FORMATS)})")
    return enc(frames, out_path, fps=fps, loop=loop)


def _as_rgb(img):
    import numpy as np
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.asarray(img)


def _as_rgb_img(img):
    """RGB copy of a card frame, flattening any alpha onto black (for GIF)."""
    if img.mode == "RGB":
        return img
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


# ── Procedural foil / holo overlay (whole-card, no I2V model needed) ───────────
# Unlike the I2V path (which moves only the ART), the foil effect animates a
# holographic sheen across the WHOLE composited card — frame, text and art alike.
# It is purely procedural (numpy), deterministic, and runs on CPU, so it works
# even when no image-to-video model is installed.

_FOIL_STYLES: dict[str, str] = {
    "holo":   "Rainbow holo",
    "gold":   "Gold foil",
    "silver": "Silver shimmer",
}
_DEFAULT_FOIL = "holo"


def foil_styles() -> list[dict]:
    """Foil-style list for the UI (key + human label)."""
    return [{"key": k, "label": v} for k, v in _FOIL_STYLES.items()]


def _hsv_to_rgb_np(h, s, v):
    """Vectorised HSV→RGB. h is an HxW float array in [0,1); s/v may be scalar
    or array. Returns HxWx3 in [0,1]."""
    import numpy as np
    i = np.floor(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    i = (i.astype(int) % 6)
    vv = np.broadcast_to(np.asarray(v, np.float32), h.shape)
    pp = np.broadcast_to(np.asarray(p, np.float32), h.shape)
    r = np.choose(i, [vv, q, pp, pp, t, vv])
    g = np.choose(i, [t, vv, vv, q, pp, pp])
    b = np.choose(i, [pp, pp, t, vv, vv, q])
    return np.stack([r, g, b], axis=-1)


def _foil_geometry(size):
    """Diagonal sweep coordinate (0..1) for an (w, h) card, phase-independent."""
    import numpy as np
    w, h = size
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    return (xs / float(w) + ys / float(h)) * 0.5


def _foil_overlay(base_arr, diag, lum, phase, *, style, intensity):
    """Screen one holographic frame (phase∈[0,1)) onto a base card array
    (HxWx4 float32, 0..255). Returns a uint8-ready float array, alpha kept."""
    import numpy as np
    if style == "gold":
        hue = np.full_like(diag, 0.11, dtype=np.float32)   # warm gold band
        sat = 0.55
    elif style == "silver":
        hue = np.zeros_like(diag)                           # white specular only
        sat = 0.0
    else:                                                   # holo rainbow
        hue = (diag * 3.0 - phase) % 1.0
        sat = 0.6
    holo = _hsv_to_rgb_np(hue, sat, 1.0)

    # A narrow specular band sweeping diagonally across the card (periodic → loops).
    sweep = 0.5 + 0.5 * np.sin(2.0 * np.pi * (diag - phase))
    glint = sweep ** 8
    recept = 0.30 + 0.70 * lum                  # foil catches the light on lit areas
    strength = (0.18 + 0.82 * glint) * recept * intensity
    add = holo * strength[..., None]

    rgb = base_arr[..., :3] / 255.0
    comp = 1.0 - (1.0 - rgb) * (1.0 - add)      # screen blend
    a = base_arr[..., 3:4] / 255.0
    comp = comp * a + rgb * (1.0 - a)           # leave transparent corners untouched

    out = np.empty_like(base_arr)
    out[..., :3] = np.clip(comp * 255.0, 0, 255)
    out[..., 3] = base_arr[..., 3]
    return out


def foil_frames(base_frames: list, *, count: int, style: str = "holo",
                intensity: float = 0.55) -> list:
    """Overlay an animated foil/holo sheen onto composited card frames.

    ``base_frames`` is one or more 750×1050 card images:
      • a single still card → ``count`` looping foil frames are synthesised from it;
      • an already-animated (looping) sequence → one full holo cycle is laid over
        it, sampled to ``count`` frames (pass ``count == len(base_frames)``).

    The result is inherently periodic (frame[count] == frame[0]), so encode it
    with ``loop=False`` — it already loops seamlessly without a ping-pong.
    """
    import numpy as np
    if not base_frames:
        return []
    style = style if style in _FOIL_STYLES else _DEFAULT_FOIL
    first = base_frames[0].convert("RGBA")
    diag = _foil_geometry(first.size)

    cache: list[tuple] = []
    for bf in base_frames:
        arr = np.asarray(bf.convert("RGBA"), dtype=np.float32)
        lum = (arr[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)) / 255.0
        cache.append((arr, lum))

    n_base = len(cache)
    out = []
    for tdx in range(count):
        phase = tdx / float(count)
        idx = min(int(tdx / count * n_base), n_base - 1) if n_base > 1 else 0
        arr, lum = cache[idx]
        frame = _foil_overlay(arr, diag, lum, phase, style=style, intensity=intensity)
        out.append(Image.fromarray(frame.astype(np.uint8), "RGBA"))
    return out
