"""
cc_frames.py — OPTIONAL "official-style" M15 frame rendering via Card Conjurer assets.

╔══════════════════════════════════════════════════════════════════════════════╗
║  CLEAN-ROOM / ZERO-LIABILITY DESIGN                                            ║
║                                                                                ║
║  This module contains ONLY original code (MIT, same as the rest of Myth Forge) ║
║  plus the *factual* MTG card layout geometry (where the title/art/text boxes   ║
║  sit on a card). It ships and redistributes NO frame artwork whatsoever.       ║
║                                                                                ║
║  To use it you must install Card Conjurer YOURSELF and point MYTHFORGE_CC_DIR  ║
║  at its root (the folder containing `img/frames/...`). The frame PNGs are      ║
║  © Wizards of the Coast / their respective authors — treat them exactly like   ║
║  the LoRAs/checkpoints the app already expects you to supply locally; do NOT   ║
║  commit them to this (or any public) repository.                               ║
║                                                                                ║
║  If MYTHFORGE_CC_DIR is unset or the assets are missing, render_card_cc()      ║
║  returns None and the caller falls back to the built-in renderer.              ║
╚══════════════════════════════════════════════════════════════════════════════╝

Implemented styles (see _SPECS): "m15" (regular modern frame) and "m15_fullart"
(borderless / full-bleed art). The layout is data-driven (one _FrameSpec each),
so adding more packs (8th edition, Showcase, Planeswalker, …) is just another spec.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps

# Reuse Myth Forge's tuned text engine + fonts + canvas scale so this renders at
# the same quality and downscales identically. We only borrow our OWN helpers.
import card_renderer as cr


# ── Layout spec (factual MTG card geometry — fractions of the full card) ───────
@dataclass(frozen=True)
class _Box:
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class _Text:
    x: float
    y: float
    w: float
    h: float
    size: float          # as a fraction of card height
    font: str            # logical font name (mapped in _FONT_FILES)


@dataclass(frozen=True)
class _FrameSpec:
    # Sub-path under <cc_dir>/img/frames where this pack's files live
    subdir: str
    # color-key -> frame PNG filename
    frames: dict
    # color-key -> power/toughness PNG filename
    pt: dict
    art: _Box
    set_symbol: _Box
    pt_box: _Box
    title: _Text
    type: _Text
    rules: _Box          # rules+flavor share this box
    mana_right: float    # right edge x-fraction for the (right-aligned) mana row
    mana_cy: float       # vertical centre y-fraction of the mana row
    mana_size: float     # mana pip size as a fraction of card height


# M15 "regular" — values transcribed from the standard MTG card layout
# (the same functional geometry Card Conjurer's m15Regular version uses).
_M15 = _FrameSpec(
    subdir="m15/regular",
    frames={
        "W": "m15FrameW.png", "U": "m15FrameU.png", "B": "m15FrameB.png",
        "R": "m15FrameR.png", "G": "m15FrameG.png", "M": "m15FrameM.png",
        "A": "m15FrameA.png", "L": "m15FrameL.png",
    },
    pt={
        "W": "m15PTW.png", "U": "m15PTU.png", "B": "m15PTB.png",
        "R": "m15PTR.png", "G": "m15PTG.png", "M": "m15PTM.png",
        "A": "m15PTA.png", "C": "m15PTC.png",
    },
    art=_Box(0.0767, 0.1129, 0.8476, 0.4429),
    set_symbol=_Box(0.9213 - 0.12, 0.5910, 0.12, 0.0410),  # right-anchored band
    pt_box=_Box(0.7573, 0.8848, 0.188, 0.0733),
    title=_Text(0.0854, 0.0522, 0.8292, 0.0543, 0.0381, "belerenb"),
    type=_Text(0.0854, 0.5664, 0.8292, 0.0543, 0.0324, "belerenb"),
    rules=_Box(0.086, 0.6303, 0.828, 0.2875),
    mana_right=0.9292,
    mana_cy=0.0522 + 0.0543 / 2,
    mana_size=0.046,
)

# M15 "borderless" / full-art — art fills the WHOLE card; the frame PNG is a
# translucent overlay (title plate + gradient text box). Text reads white over
# the art, which the legibility picker handles automatically by sampling.
_M15_FULLART = _FrameSpec(
    subdir="m15/borderless",
    frames={
        "W": "m15GenericShowcaseFrameW.png", "U": "m15GenericShowcaseFrameU.png",
        "B": "m15GenericShowcaseFrameB.png", "R": "m15GenericShowcaseFrameR.png",
        "G": "m15GenericShowcaseFrameG.png", "M": "m15GenericShowcaseFrameM.png",
        "A": "m15GenericShowcaseFrameA.png", "L": "m15GenericShowcaseFrameL.png",
        "C": "m15GenericShowcaseFrameC.png",
    },
    pt={
        "W": "pt/w.png", "U": "pt/u.png", "B": "pt/b.png", "R": "pt/r.png",
        "G": "pt/g.png", "M": "pt/m.png", "A": "pt/a.png", "C": "pt/l.png",
    },
    art=_Box(0.0, 0.0, 1.0, 0.9224),                 # full-bleed art
    set_symbol=_Box(0.9213 - 0.12, 0.5910, 0.12, 0.0410),
    pt_box=_Box(1146 / 1500, 1861 / 2100, 274 / 1500, 140 / 2100),
    title=_Text(0.0854, 0.0522, 0.8292, 0.0543, 0.0381, "belerenb"),
    type=_Text(0.0854, 0.5664, 0.8292, 0.0543, 0.0324, "belerenb"),
    rules=_Box(0.086, 0.6303, 0.828, 0.2875),
    mana_right=0.9292,
    mana_cy=0.0522 + 0.0543 / 2,
    mana_size=0.046,
)

# Frame-style key -> spec. Keys match BuildRequest.frame_style / the UI selector.
_SPECS: dict[str, _FrameSpec] = {
    "m15":         _M15,
    "m15_fullart": _M15_FULLART,
}

# Logical font name -> file in card_assets/fonts (all already shipped with the app)
_FONT_FILES = {
    "belerenb":   "beleren-bold_P1.01.ttf",
    "belerenbsc": "belerensmallcaps-bold.ttf",
    "mplantin":   "mplantin.ttf",
    "matrixb":    "matrixb.ttf",
}


# ── Asset resolution ───────────────────────────────────────────────────────────
# Users can configure the Card Conjurer folder two ways (env var wins):
#   1. MYTHFORGE_CC_DIR environment variable (power users / persistent)
#   2. cc_config.json in the project root: {"cc_dir": "C:\\path\\to\\cardconjurer"}
#      — written by the in-app "Card Conjurer folder" setting (POST /api/frame-config),
#      gitignored so it never leaks a machine-specific path to the repo.
_CONFIG_FILE = Path("cc_config.json")


def configured_cc_dir() -> str:
    """The configured CC path string (env var first, then cc_config.json). May be ''."""
    d = os.environ.get("MYTHFORGE_CC_DIR", "").strip()
    if d:
        return d
    try:
        if _CONFIG_FILE.exists():
            return (json.loads(_CONFIG_FILE.read_text(encoding="utf-8")).get("cc_dir") or "").strip()
    except Exception:
        pass
    return ""


def set_cc_dir(path: str) -> None:
    """Persist the Card Conjurer folder to cc_config.json (used by the UI)."""
    _CONFIG_FILE.write_text(json.dumps({"cc_dir": (path or "").strip()}, indent=2),
                            encoding="utf-8")


def cc_root() -> Optional[Path]:
    """The configured local Card Conjurer install, or None if unset/invalid."""
    d = configured_cc_dir()
    if not d:
        return None
    p = Path(d)
    return p if (p / "img" / "frames").is_dir() else None


def is_available(style: str = "m15") -> bool:
    """True if the given frame pack's assets are present locally."""
    root = cc_root()
    if root is None:
        return False
    spec = _SPECS.get(style)
    if spec is None:
        return False
    fdir = root / "img" / "frames" / spec.subdir
    # Require at least the base colored frames to consider the pack usable.
    return (fdir / spec.frames["M"]).exists() and (fdir / spec.frames["R"]).exists()


@lru_cache(maxsize=64)
def _load_png(path_str: str) -> Optional[Image.Image]:
    p = Path(path_str)
    if not p.exists():
        return None
    try:
        return Image.open(p).convert("RGBA")
    except Exception:
        return None


@lru_cache(maxsize=16)
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    fname = _FONT_FILES.get(name, _FONT_FILES["belerenb"])
    fp = cr._FONTS / fname
    if fp.exists():
        return ImageFont.truetype(str(fp), size)
    return ImageFont.load_default(size=size)


# ── Color identity -> frame key (per spec) ─────────────────────────────────────
def _cc_frame_key(colors: list, type_line: str, spec: _FrameSpec) -> str:
    tl = (type_line or "").lower()
    if "land" in tl and "L" in spec.frames:
        return "L"
    if not colors:
        # prefer a dedicated colorless frame if the pack has one, else artifact
        return "C" if "C" in spec.frames else "A"
    if len(colors) == 1:
        return colors[0] if colors[0] in spec.frames else "M"
    return "M"                # 2+ colors -> gold/multicolored (duals need masks; v1 = gold)


def _pt_key(frame_key: str, spec: _FrameSpec) -> str:
    if frame_key in spec.pt:
        return frame_key
    return "C"


# ── Render ──────────────────────────────────────────────────────────────────────
def render_card_cc(
    card: dict,
    themed_name: str,
    oracle_text: str,
    art_image: Optional[Image.Image] = None,
    set_symbol: Optional[Image.Image] = None,
    flavor_text: str = "",
    border_theme: str = "",        # accepted for signature parity; not used here
    style: str = "m15",            # which pack: "m15" (regular) or "m15_fullart"
) -> Optional[Image.Image]:
    """
    Render `card` using locally-installed Card Conjurer frames for `style`
    ("m15" = regular modern frame, "m15_fullart" = borderless/full-art).
    Returns a 750×1050 RGBA image, or None if the assets aren't available (so the
    caller can fall back to the built-in renderer). Signature mirrors
    card_renderer.render_card for a drop-in dispatch.
    """
    root = cc_root()
    if root is None:
        return None
    spec = _SPECS.get(style)
    if spec is None:
        return None
    fdir = root / "img" / "frames" / spec.subdir

    colors    = card.get("color_identity", []) or []
    type_line = card.get("type_line", "") or ""
    mana_cost = card.get("mana_cost", "") or ""
    power     = card.get("power")
    toughness = card.get("toughness")

    fkey  = _cc_frame_key(colors, type_line, spec)
    frame = _load_png(str(fdir / spec.frames.get(fkey, spec.frames["M"])))
    if frame is None:
        return None  # asset missing → fall back

    W, H = cr._W2, cr._H2                      # internal hi-res canvas (matches card_renderer)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    def px(box: _Box):
        return (int(box.x * W), int(box.y * H), int(box.w * W), int(box.h * H))

    # ── Art ────────────────────────────────────────────────────────────────────
    if art_image is not None:
        ax, ay, aw, ah = px(spec.art)
        art = ImageOps.fit(art_image.convert("RGBA"), (aw, ah), Image.LANCZOS)
        canvas.paste(art, (ax, ay))
    else:
        ax, ay, aw, ah = px(spec.art)
        ph = Image.new("RGBA", (aw, ah), (20, 18, 14, 255))
        ImageDraw.Draw(ph).text((aw // 2, ah // 2), themed_name,
                                font=_font("belerenb", int(0.03 * H)),
                                fill=(70, 64, 52, 255), anchor="mm")
        canvas.paste(ph, (ax, ay))

    # ── Frame overlay (full-card PNG with transparent art/text windows) ──────────
    canvas.alpha_composite(frame.resize((W, H), Image.LANCZOS))

    # ── Power/Toughness box ──────────────────────────────────────────────────────
    if power is not None and toughness is not None:
        pt_png = _load_png(str(fdir / spec.pt.get(_pt_key(fkey, spec), spec.pt["C"])))
        if pt_png is not None:
            bx, by, bw, bh = px(spec.pt_box)
            canvas.alpha_composite(pt_png.resize((bw, bh), Image.LANCZOS), (bx, by))

    # ── Set symbol ───────────────────────────────────────────────────────────────
    if set_symbol is not None:
        sx, sy, sw, sh = px(spec.set_symbol)
        ss = set_symbol.convert("RGBA")
        # fit within the band height, right-anchored
        scale = sh / ss.height
        ss = ss.resize((max(1, int(ss.width * scale)), sh), Image.LANCZOS)
        canvas.alpha_composite(ss, (sx + sw - ss.width, sy))

    draw = ImageDraw.Draw(canvas)

    # ── Mana cost (right-aligned on the title line) ──────────────────────────────
    pips = cr._parse_mana(mana_cost)
    mana_cy = int(spec.mana_cy * H)
    mana_sz = int(spec.mana_size * H)
    mana_left = int(spec.mana_right * W)
    if pips:
        mana_left = cr._draw_mana_row(canvas, pips, int(spec.mana_right * W),
                                      mana_cy, mana_sz)

    # ── Title (auto-fit + legibility-driven colour against the real frame) ───────
    tx = int(spec.title.x * W)
    tcy = int((spec.title.y + spec.title.h / 2) * H)
    title_max = max(int(0.2 * W), (mana_left - int(spec.title.size * H * 0.3)) - tx)
    t_size = int(spec.title.size * H)
    t_font = _font(spec.title.font, t_size)
    t_text = themed_name
    while t_size > int(0.022 * H) and t_font.getlength(t_text) > title_max:
        t_size = int(t_size * 0.92)
        t_font = _font(spec.title.font, t_size)
    while t_font.getlength(t_text) > title_max and len(t_text) > 4:
        t_text = t_text[:-2] + "…"
    t_box = (tx, tcy - t_size // 2, tx + max(t_font.getlength(t_text), 1), tcy + t_size // 2)
    cr._draw_legible_text(draw, canvas, (tx, tcy), t_text, t_font, t_box,
                          anchor="lm", fallback=cr._DARK_TEXT)

    # ── Type line ────────────────────────────────────────────────────────────────
    ty_x = int(spec.type.x * W)
    ty_cy = int((spec.type.y + spec.type.h / 2) * H)
    ty_max = int(spec.type.w * W) - int(0.06 * W)   # leave room for the set symbol
    ty_size = int(spec.type.size * H)
    ty_font = _font(spec.type.font, ty_size)
    ty_text = type_line
    while ty_size > int(0.02 * H) and ty_font.getlength(ty_text) > ty_max:
        ty_size = int(ty_size * 0.92)
        ty_font = _font(spec.type.font, ty_size)
    while ty_font.getlength(ty_text) > ty_max and len(ty_text) > 4:
        ty_text = ty_text[:-2] + "…"
    ty_box = (ty_x, ty_cy - ty_size // 2, ty_x + max(ty_font.getlength(ty_text), 1),
              ty_cy + ty_size // 2)
    cr._draw_legible_text(draw, canvas, (ty_x, ty_cy), ty_text, ty_font, ty_box,
                          anchor="lm", fallback=cr._DARK_TEXT)

    # ── Rules + flavor (reuse the built-in text engine at M15 bounds) ────────────
    rx, ry, rw, rh = px(spec.rules)
    has_oracle = bool((oracle_text or "").strip())
    has_flavor = bool((flavor_text or "").strip())
    body_size = int(spec.rules.h * H * 0.13)        # starting size; _draw_oracle_text auto-fits
    sym_size  = int(body_size * 1.05)

    if has_oracle and has_flavor:
        rules_h = int(rh * 0.66)
        flav_y  = ry + rules_h + int(0.012 * H)
        flav_h  = rh - rules_h - int(0.012 * H)
        cr._draw_oracle_text(canvas, oracle_text, rx, ry, rw, rules_h,
                             sym_size, body_size, cr._DARK_TEXT, center_v=True)
        cr._draw_flavor_text(canvas, flavor_text, rx, flav_y, rw, flav_h,
                             int(body_size * 0.92), cr._DARK_TEXT)
    elif has_oracle:
        cr._draw_oracle_text(canvas, oracle_text, rx, ry, rw, rh,
                             sym_size, body_size, cr._DARK_TEXT, center_v=True)
    elif has_flavor:
        cr._draw_flavor_text(canvas, flavor_text, rx, ry, rw, rh,
                             body_size, cr._DARK_TEXT)

    # ── Power/Toughness text ──────────────────────────────────────────────────────
    if power is not None and toughness is not None:
        pt_str = f"{power}/{toughness}"
        bx, by, bw, bh = px(spec.pt_box)
        pt_size = int(spec.pt_box.h * H * 0.55)
        pt_font = _font("belerenbsc", pt_size)
        pt_cx = bx + int(0.5 * bw)
        pt_cy = by + int(0.46 * bh)
        pt_box = (bx, by, bx + bw, by + bh)
        cr._draw_legible_text(draw, canvas, (pt_cx, pt_cy), pt_str, pt_font, pt_box,
                              anchor="mm", fallback=cr._DARK_TEXT)

    return canvas.resize((cr.CARD_W, cr.CARD_H), Image.LANCZOS)
