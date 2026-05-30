"""
Custom themed mana pips.

Each pip is a **two-layer** symbol exactly as requested:
  1. a solid disc in the mana colour it represents (the "main colour"), and
  2. a single bold **black silhouette** of the deck's theme icon on top.

One shared silhouette is used across all five colours (and colourless) so the
deck reads as a cohesive set — only the disc colour changes per pip. The
silhouette subject comes from the deck's emblem prompt (falling back to the art
theme), so it is driven by user input.

Silhouette source, in priority order:
  1. ComfyUI / FLUX  — a flat black-on-white silhouette, thresholded to pure
     black and trimmed. Highest quality, most flexible subjects.
  2. Procedural      — one of the hand-drawn vector shapes from ``set_symbol``
     rendered in solid black, chosen by keyword. Always available, so pips
     never fail even when ComfyUI is offline.

The result feeds ``card_renderer`` which composites the pips onto the frame in
place of the stock W/U/B/R/G/C SVG symbols.
"""
from __future__ import annotations

import io
import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

# Colours the silhouette gets composited onto. Pure mana hues for W/U/R/G; B and
# C are deliberately *lightened* (a black silhouette on a black disc is
# invisible — real MTG solves this the same way, a pale disc under a black skull).
MANA_DISC: dict[str, tuple[int, int, int]] = {
    "W": (245, 236, 200),   # ivory
    "U": (59, 130, 246),    # blue
    "B": (120, 110, 135),   # muted violet-grey (lightened so silhouette reads)
    "R": (231, 70, 56),     # red
    "G": (34, 170, 94),     # green
    "C": (176, 172, 168),   # neutral grey (colourless)
}

# Base render resolution; card_renderer downsamples per use (pips render ~45px).
PIP_BASE = 256

COMFY_URL = "http://127.0.0.1:8188"


# ── ComfyUI silhouette generation ──────────────────────────────────────────────

def _comfy_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        COMFY_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _comfy_get(path: str) -> dict:
    return json.loads(urllib.request.urlopen(COMFY_URL + path, timeout=10).read())


def _comfy_view(filename: str, subfolder: str, ftype: str) -> Image.Image:
    qs = urllib.parse.urlencode(
        {"filename": filename, "subfolder": subfolder, "type": ftype}
    )
    data = urllib.request.urlopen(f"{COMFY_URL}/view?{qs}", timeout=20).read()
    return Image.open(io.BytesIO(data)).convert("L")


def _flux_silhouette(subject: str, timeout_s: int = 180) -> Optional[Image.Image]:
    """
    Ask FLUX for a flat black silhouette of ``subject`` on white. Returns a
    greyscale PIL image, or ``None`` if ComfyUI is unreachable / times out.
    """
    try:
        import image_gen  # local; pulls in the shared FLUX workflow builder
    except Exception:
        return None

    prompt = (
        f"a flat solid pure black silhouette of {subject}, centered, "
        "on a plain pure white background, simple bold minimal logo icon, "
        "single shape, no outline, no shading, no detail, no text, "
        "high contrast, vector style"
    )
    try:
        wf = image_gen._build_flux_workflow(
            "flux1-dev-fp8.safetensors", prompt, 7,
            negative="", gen=image_gen.GenSettings(steps=20),
        )
        pid = _comfy_post(
            "/prompt", {"prompt": wf, "client_id": str(uuid.uuid4())}
        )["prompt_id"]
    except Exception as e:
        print(f"  [mana_pips] ComfyUI unavailable, using procedural fallback ({e})")
        return None

    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            entry = _comfy_get(f"/history/{pid}").get(pid)
        except Exception:
            entry = None
        if entry and entry.get("status", {}).get("completed"):
            for node in entry.get("outputs", {}).values():
                for im in node.get("images", []):
                    try:
                        return _comfy_view(
                            im["filename"], im.get("subfolder", ""),
                            im.get("type", "output"),
                        )
                    except Exception:
                        return None
            return None
        time.sleep(2)
    print("  [mana_pips] silhouette generation timed out, using fallback")
    return None


# ── Silhouette extraction ──────────────────────────────────────────────────────

def _extract_silhouette(gray: Image.Image) -> Optional[Image.Image]:
    """
    Threshold a black-on-white render to a clean pure-black RGBA silhouette,
    dropping stray specks and trimming to the subject. Returns RGBA or None.
    """
    # Median filter knocks out compression specks before thresholding.
    g = gray.filter(ImageFilter.MedianFilter(3))
    # alpha = where the image is dark (the silhouette)
    alpha = g.point(lambda p: 255 if p < 128 else 0, "L")

    # Keep only the largest connected blob if scipy is available; otherwise the
    # median filter + bbox is already clean for FLUX-on-white renders.
    try:
        import numpy as np
        from scipy import ndimage
        arr = np.asarray(alpha) > 0
        labels, n = ndimage.label(arr)
        if n > 1:
            sizes = ndimage.sum(arr, labels, range(1, n + 1))
            keep = int(np.argmax(sizes)) + 1
            arr = labels == keep
            alpha = Image.fromarray((arr * 255).astype("uint8"), "L")
    except Exception:
        pass

    bbox = alpha.getbbox()
    if not bbox:
        return None
    alpha = alpha.crop(bbox)
    sil = Image.new("RGBA", alpha.size, (0, 0, 0, 255))
    sil.putalpha(alpha)
    return sil


# ── Procedural fallback silhouette ─────────────────────────────────────────────

def _procedural_silhouette(subject: str, theme: str) -> Image.Image:
    """A solid-black vector shape from set_symbol, chosen by keyword. Always works."""
    import hashlib
    from set_symbol import _SHAPE_FUNCS, _SHAPE_KEYWORDS

    t = (subject + " " + theme).lower()
    idx = int(hashlib.sha256(t.encode()).hexdigest(), 16) % len(_SHAPE_FUNCS)
    for kw, shape_idx in _SHAPE_KEYWORDS:
        if kw in t:
            idx = shape_idx
            break

    size = PIP_BASE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    black = (0, 0, 0)
    # fg=bg=accent all black → a solid silhouette with no inner cut-outs.
    _SHAPE_FUNCS[idx](draw, size / 2, size / 2, size * 0.42, black, black, black)
    # The shape is black on a transparent canvas, so the alpha channel IS the
    # silhouette mask — use it directly (do NOT route through _extract_silhouette,
    # which expects a white-background greyscale render and would treat the whole
    # canvas as solid). Trim to the drawn shape.
    alpha = img.split()[3]
    bbox = alpha.getbbox()
    if bbox:
        alpha = alpha.crop(bbox)
    sil = Image.new("RGBA", alpha.size, (0, 0, 0, 255))
    sil.putalpha(alpha)
    return sil


# ── Composition ────────────────────────────────────────────────────────────────

def _compose_pip(disc_rgb: tuple[int, int, int], silhouette: Image.Image,
                 size: int = PIP_BASE) -> Image.Image:
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.ellipse(
        [1, 1, size - 2, size - 2],
        fill=disc_rgb + (255,),
        outline=(22, 20, 18, 255),
        width=max(1, size // 40),
    )
    s = silhouette.copy()
    fit = int(size * 0.62)
    s.thumbnail((fit, fit), Image.LANCZOS)
    base.alpha_composite(s, ((size - s.width) // 2, (size - s.height) // 2))
    return base


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_mana_pips(theme: str, subject: str = "") -> dict[str, Image.Image]:
    """
    Build the W/U/B/R/G/C pip images for a deck. ``subject`` is the silhouette
    icon (e.g. the emblem prompt); falls back to the theme when empty.
    Returns a dict of mana-code → RGBA PIL image at ``PIP_BASE`` resolution.
    """
    subject = (subject or theme or "arcane sigil").strip()
    gray = _flux_silhouette(subject)
    sil = _extract_silhouette(gray) if gray is not None else None
    if sil is None:
        sil = _procedural_silhouette(subject, theme)
        print(f"  [mana_pips] procedural silhouette for {subject!r}")
    else:
        print(f"  [mana_pips] FLUX silhouette for {subject!r}")
    return {code: _compose_pip(rgb, sil) for code, rgb in MANA_DISC.items()}


def save_mana_pips(theme: str, out_dir: Path, subject: str = "") -> dict[str, Path]:
    """Generate pips and save them as PNGs under ``out_dir``. Returns code → path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pips = generate_mana_pips(theme, subject)
    paths: dict[str, Path] = {}
    for code, img in pips.items():
        p = out_dir / f"pip_{code}.png"
        img.save(p, "PNG")
        paths[code] = p
    return paths


def load_mana_pips(out_dir: Path) -> dict[str, Image.Image]:
    """Load previously-saved pip PNGs from ``out_dir`` (code → image)."""
    pips: dict[str, Image.Image] = {}
    for code in MANA_DISC:
        p = out_dir / f"pip_{code}.png"
        if p.exists():
            pips[code] = Image.open(p).convert("RGBA")
    return pips
