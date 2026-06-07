"""
Generates a unique set emblem for a deck.

The symbol is derived deterministically from the deck's art theme —
same theme always produces the same symbol. It is generated once and
reused across every card in the deck.

Priority:
  1. ComfyUI SDXL (if running) — highest quality
  2. Procedural Pillow drawing   — always available, unique per theme

The procedural path uses a hash of the theme string to pick:
  - Shape family (pentagon, star, shield, tome, diamond, crown)
  - Primary hue
  - Inner design accent
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# Symbol canvas size — scaled to card by card_renderer
SYMBOL_SIZE = 64


# ── Color helpers ─────────────────────────────────────────────────────────────

def _hue_to_rgb(h: float, s: float = 0.72, v: float = 0.88) -> tuple[int, int, int]:
    """HSV → RGB, all in [0,1] except h in [0,360]."""
    h = h / 60
    i = int(h)
    f = h - i
    p, q, t_ = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    segments = [(v, t_, p), (q, v, p), (p, v, t_), (p, q, v), (t_, p, v), (v, p, q)]
    r, g, b = segments[i % 6]
    return int(r * 255), int(g * 255), int(b * 255)


def _darken(c: tuple[int, int, int], factor: float = 0.55) -> tuple[int, int, int]:
    return tuple(int(x * factor) for x in c)  # type: ignore


# ── Shape drawing ─────────────────────────────────────────────────────────────

def _polygon_points(
    cx: float, cy: float, r: float, sides: int, rotation: float = 0.0
) -> list[tuple[float, float]]:
    pts = []
    for i in range(sides):
        angle = rotation + 2 * math.pi * i / sides
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def _star_points(
    cx: float, cy: float, r_outer: float, r_inner: float,
    points: int, rotation: float = 0.0
) -> list[tuple[float, float]]:
    pts = []
    for i in range(points * 2):
        r = r_outer if i % 2 == 0 else r_inner
        angle = rotation + math.pi * i / points
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


# ── Shape families ────────────────────────────────────────────────────────────

def _draw_shape_0_pentagon(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Upward pentagon with inner smaller pentagon."""
    pts = _polygon_points(cx, cy, r, 5, rotation=-math.pi / 2)
    draw.polygon(pts, fill=fg, outline=_darken(fg))
    inner = _polygon_points(cx, cy, r * 0.52, 5, rotation=-math.pi / 2)
    draw.polygon(inner, fill=bg, outline=accent)

def _draw_shape_1_star(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """5-pointed star."""
    pts = _star_points(cx, cy, r, r * 0.42, 5, rotation=-math.pi / 2)
    draw.polygon(pts, fill=fg, outline=_darken(fg))
    # Small center circle
    draw.ellipse([cx - r*0.15, cy - r*0.15, cx + r*0.15, cy + r*0.15], fill=accent)

def _draw_shape_2_shield(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Shield / heraldic shape."""
    # Trapezoid top + curved bottom
    tl = (cx - r * 0.75, cy - r * 0.78)
    tr = (cx + r * 0.75, cy - r * 0.78)
    bl = (cx - r * 0.75, cy + r * 0.1)
    br = (cx + r * 0.75, cy + r * 0.1)
    bot = (cx, cy + r * 0.92)
    draw.polygon([tl, tr, br, bot, bl], fill=fg, outline=_darken(fg))
    # Inner stripe
    tl2 = (cx - r * 0.45, cy - r * 0.5)
    tr2 = (cx + r * 0.45, cy - r * 0.5)
    bl2 = (cx - r * 0.45, cy + r * 0.1)
    br2 = (cx + r * 0.45, cy + r * 0.1)
    bot2 = (cx, cy + r * 0.55)
    draw.polygon([tl2, tr2, br2, bot2, bl2], fill=accent, outline=_darken(accent))

def _draw_shape_3_diamond(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Rotated square (diamond) with inner cross."""
    pts = _polygon_points(cx, cy, r, 4, rotation=0)
    draw.polygon(pts, fill=fg, outline=_darken(fg))
    # Cross inside
    w = r * 0.18
    draw.rectangle([cx - w, cy - r * 0.62, cx + w, cy + r * 0.62], fill=accent)
    draw.rectangle([cx - r * 0.62, cy - w, cx + r * 0.62, cy + w], fill=accent)

def _draw_shape_4_rune(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Hexagon with inner triangle — rune/arcane feel."""
    pts = _polygon_points(cx, cy, r, 6, rotation=0)
    draw.polygon(pts, fill=fg, outline=_darken(fg))
    inner = _polygon_points(cx, cy, r * 0.5, 3, rotation=-math.pi / 2)
    draw.polygon(inner, fill=accent, outline=_darken(accent))

def _draw_shape_5_crown(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Simple crown silhouette."""
    base_y = cy + r * 0.55
    base_h = r * 0.32
    # Base rectangle
    draw.rectangle([cx - r * 0.72, base_y - base_h, cx + r * 0.72, base_y], fill=fg)
    # Three spikes
    for offset in [-r * 0.5, 0, r * 0.5]:
        spike_tip = cy - r * 0.75
        spike_base_y = base_y - base_h + 2
        pts = [
            (cx + offset - r * 0.2, spike_base_y),
            (cx + offset + r * 0.2, spike_base_y),
            (cx + offset, spike_tip),
        ]
        draw.polygon(pts, fill=fg, outline=_darken(fg))
    # Gems on spikes
    for offset in [-r * 0.5, 0, r * 0.5]:
        gx, gy = cx + offset, cy - r * 0.42
        draw.ellipse([gx - r*0.1, gy - r*0.1, gx + r*0.1, gy + r*0.1], fill=accent)


def _draw_shape_6_flame(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Teardrop flame rising to a point."""
    outer = [
        (cx,              cy - r * 0.92),   # tip
        (cx + r * 0.42,  cy - r * 0.28),
        (cx + r * 0.70,  cy + r * 0.38),
        (cx + r * 0.44,  cy + r * 0.78),
        (cx,              cy + r * 0.92),   # base
        (cx - r * 0.44,  cy + r * 0.78),
        (cx - r * 0.70,  cy + r * 0.38),
        (cx - r * 0.42,  cy - r * 0.28),
    ]
    draw.polygon(outer, fill=fg, outline=_darken(fg))
    inner = [
        (cx,              cy - r * 0.44),
        (cx + r * 0.26,  cy + r * 0.14),
        (cx,              cy + r * 0.52),
        (cx - r * 0.26,  cy + r * 0.14),
    ]
    draw.polygon(inner, fill=accent)


def _draw_shape_7_eye(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """All-seeing arcane eye (almond + iris + pupil)."""
    n   = 24
    pts = [
        (cx + r * 0.92 * math.cos(2 * math.pi * i / n),
         cy + r * 0.40 * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    draw.polygon(pts, fill=fg, outline=_darken(fg))
    draw.ellipse([cx - r*0.30, cy - r*0.30, cx + r*0.30, cy + r*0.30], fill=bg)
    draw.ellipse([cx - r*0.14, cy - r*0.14, cx + r*0.14, cy + r*0.14], fill=accent)
    # Lash lines on left and right tips
    draw.line([(cx - r*0.92, cy), (cx - r*0.70, cy)], fill=accent, width=max(1, round(r*0.06)))
    draw.line([(cx + r*0.70, cy), (cx + r*0.92, cy)], fill=accent, width=max(1, round(r*0.06)))


def _draw_shape_8_crossed_swords(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Crossed swords with cross-guards."""
    sw = r * 0.11
    for dx in (1, -1):
        x1, y1 = cx + dx * r * 0.76, cy - r * 0.76
        x2, y2 = cx - dx * r * 0.62, cy + r * 0.62
        ang  = math.atan2(y2 - y1, x2 - x1)
        perp = ang + math.pi / 2
        px, py = sw * math.cos(perp), sw * math.sin(perp)
        blade = [(x1+px,y1+py),(x1-px,y1-py),(x2-px,y2-py),(x2+px,y2+py)]
        draw.polygon(blade, fill=fg, outline=_darken(fg))
        # Cross-guard near hilt end
        gx = x1 + (x2 - x1) * 0.74
        gy = y1 + (y2 - y1) * 0.74
        gw = r * 0.22
        guard = [
            (gx + gw*math.cos(perp),  gy + gw*math.sin(perp)),
            (gx + gw*math.cos(perp) + sw*1.4*math.cos(ang),
             gy + gw*math.sin(perp) + sw*1.4*math.sin(ang)),
            (gx - gw*math.cos(perp) + sw*1.4*math.cos(ang),
             gy - gw*math.sin(perp) + sw*1.4*math.sin(ang)),
            (gx - gw*math.cos(perp),  gy - gw*math.sin(perp)),
        ]
        draw.polygon(guard, fill=accent, outline=_darken(accent))
    draw.ellipse([cx-r*0.15, cy-r*0.15, cx+r*0.15, cy+r*0.15], fill=accent)


def _draw_shape_9_chalice(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Goblet / holy grail."""
    rim_y, bowl_y = cy - r * 0.64, cy + r * 0.12
    tw, bw = r * 0.64, r * 0.30
    draw.polygon([(cx-tw, rim_y),(cx+tw, rim_y),(cx+bw, bowl_y),(cx-bw, bowl_y)],
                 fill=fg, outline=_darken(fg))
    sw = round(r * 0.10)
    draw.rectangle([cx - sw, bowl_y, cx + sw, cy + r * 0.58], fill=fg)
    bbase = r * 0.58
    draw.ellipse([cx-bbase, cy+r*0.52, cx+bbase, cy+r*0.52+r*0.22], fill=fg)
    draw.ellipse([cx-bw*0.55, rim_y+r*0.09, cx+bw*0.55, rim_y+r*0.22], fill=accent)


def _draw_shape_10_tree(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Stylised three-tier tree (nature / growth)."""
    # Trunk
    tw = r * 0.10
    draw.rectangle([cx - tw, cy + r*0.12, cx + tw, cy + r*0.88], fill=fg)
    # Three tiers of foliage, bottom to top
    tiers = [(cy + r*0.18, 1.00), (cy - r*0.14, 0.76), (cy - r*0.44, 0.52)]
    for i, (ty, scale) in enumerate(tiers):
        hw  = r * scale * 0.72
        th  = r * scale * 0.44
        col = fg if i < 2 else accent
        draw.polygon(
            [(cx, ty - th), (cx + hw, ty + th), (cx - hw, ty + th)],
            fill=col, outline=_darken(fg),
        )


def _draw_shape_11_ouroboros(draw: ImageDraw.ImageDraw, cx, cy, r, fg, bg, accent):
    """Infinity / cycle: two interlocked loops."""
    off  = r * 0.36
    ring = round(r * 0.20)
    for xo in (-off, off):
        draw.ellipse(
            [cx + xo - r*0.38, cy - r*0.38, cx + xo + r*0.38, cy + r*0.38],
            outline=fg, width=ring,
        )
    # Accent gems at crossing points
    for xo in (-off * 0.42, off * 0.42):
        draw.ellipse([cx+xo-r*0.11, cy-r*0.11, cx+xo+r*0.11, cy+r*0.11], fill=accent)
    # End caps to suggest a serpent eating its tail
    draw.ellipse([cx-off-r*0.38-ring//2, cy-r*0.12,
                  cx-off-r*0.38+ring//2, cy+r*0.12], fill=fg)
    draw.ellipse([cx+off+r*0.38-ring//2, cy-r*0.12,
                  cx+off+r*0.38+ring//2, cy+r*0.12], fill=fg)


_SHAPE_FUNCS = [
    _draw_shape_0_pentagon,
    _draw_shape_1_star,
    _draw_shape_2_shield,
    _draw_shape_3_diamond,
    _draw_shape_4_rune,
    _draw_shape_5_crown,
    _draw_shape_6_flame,
    _draw_shape_7_eye,
    _draw_shape_8_crossed_swords,
    _draw_shape_9_chalice,
    _draw_shape_10_tree,
    _draw_shape_11_ouroboros,
]


# ── Emblem prompt keyword maps ────────────────────────────────────────────────
# Entries are checked in order; first match wins.
# Shape index corresponds to _SHAPE_FUNCS above (0=pentagon … 5=crown).

_SHAPE_KEYWORDS: list[tuple[str, int]] = [
    # Crown / royalty → crown (5)
    ("crown",     5),
    ("king",      5),
    ("queen",     5),
    ("royal",     5),
    ("throne",    5),
    ("emperor",   5),
    ("monarch",   5),
    ("regent",    5),
    # Star / celestial → star (1)
    ("star",      1),
    ("sun",       1),
    ("nova",      1),
    ("solar",     1),
    ("stellar",   1),
    ("radiant",   1),
    ("cat",       1),
    ("feline",    1),
    ("paw",       1),
    # Shield / defense → shield (2)
    ("shield",    2),
    ("guard",     2),
    ("castle",    2),
    ("bastion",   2),
    ("knight",    2),
    ("protect",   2),
    ("fortress",  2),
    ("bulwark",   2),
    ("warden",    2),
    # Diamond / gem → diamond (3)
    ("diamond",   3),
    ("gem",       3),
    ("crystal",   3),
    ("skull",     3),
    ("bone",      3),
    ("death",     3),
    ("void",      3),
    # Rune / arcane → hexagon-rune (4)
    ("rune",      4),
    ("arcane",    4),
    ("hex",       4),
    ("magic",     4),
    ("spell",     4),
    ("eldritch",  4),
    ("moon",      4),
    ("cosmic",    4),
    ("sigil",     4),
    ("glyph",     4),
    # Beast / wild → pentagon (0)
    ("dragon",    0),
    ("serpent",   0),
    ("beast",     0),
    ("wolf",      0),
    ("crest",     0),
    ("creature",  0),
    ("monster",   0),
    ("predator",  0),
    # Flame / fire → flame (6)
    ("flame",     6),
    ("fire",      6),
    ("burn",      6),
    ("blaze",     6),
    ("inferno",   6),
    ("lava",      6),
    ("volcano",   6),
    ("ember",     6),
    ("phoenix",   6),
    # Eye / oracle / seer → eye (7)
    ("eye",       7),
    ("iris",      7),
    ("seer",      7),
    ("oracle",    7),
    ("vision",    7),
    ("gaze",      7),
    ("beholder",  7),
    ("watch",     7),
    # Sword / warrior → crossed swords (8)
    ("sword",     8),
    ("blade",     8),
    ("warrior",   8),
    ("battle",    8),
    ("combat",    8),
    ("duelist",   8),
    ("war",       8),
    ("steel",     8),
    ("clash",     8),
    # Chalice / holy → chalice (9)
    ("chalice",   9),
    ("cup",       9),
    ("goblet",    9),
    ("grail",     9),
    ("vessel",    9),
    ("holy",      9),
    ("sacred",    9),
    ("divine",    9),
    ("church",    9),
    ("temple",    9),
    # Tree / nature / forest → tree (10)
    ("tree",      10),
    ("forest",    10),
    ("nature",    10),
    ("grove",     10),
    ("root",      10),
    ("growth",    10),
    ("garden",    10),
    ("branch",    10),
    ("thorn",     10),
    ("leaf",      10),
    # Infinity / cycle / serpent → ouroboros (11)
    ("infinite",  11),
    ("infinity",  11),
    ("cycle",     11),
    ("eternal",   11),
    ("ouroboros", 11),
    ("loop",      11),
    ("ring",      11),
    ("rebirth",   11),
    ("undying",   11),
]

# ── Rarity metals ──────────────────────────────────────────────────────────────
# Real MTG set symbols are coloured by RARITY, not theme: common = black,
# uncommon = silver, rare = gold, mythic = orange/bronze (special/timeshifted =
# purple). The printed symbols are metallic — a gradient from a dark shadow up to
# a light highlight — so we map the emblem's luminance relief onto a 3-stop metal
# ramp (shadow → mid → highlight) to get that beveled, coin-like look.
RARITY_METALS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "common":   ((26, 26, 28),   (66, 66, 70),    (140, 140, 146)),  # graphite black
    "uncommon": ((92, 98, 106),  (164, 170, 178), (236, 240, 245)),  # silver
    "rare":     ((120, 86, 20),  (198, 156, 56),  (252, 236, 158)),  # gold
    "mythic":   ((140, 40, 14),  (216, 94, 28),   (252, 178, 90)),   # orange/bronze
    "special":  ((74, 42, 116),  (128, 86, 178),  (210, 180, 240)),  # purple (timeshifted)
}
_RARITY_ALIASES = {
    "mythic rare": "mythic", "bonus": "special",
    "masterpiece": "special", "timeshifted": "special",
}


def _normalize_rarity(rarity: str) -> str:
    key = (rarity or "common").strip().lower()
    return _RARITY_ALIASES.get(key, key)


def _metal_luts(stops):
    """Three 256-entry LUTs (R,G,B) for a shadow→mid→highlight metal ramp."""
    shadow, mid, high = stops
    r_lut, g_lut, b_lut = [], [], []
    for i in range(256):
        t = i / 255
        a, b, tt = (shadow, mid, t / 0.5) if t < 0.5 else (mid, high, (t - 0.5) / 0.5)
        r_lut.append(int(a[0] + (b[0] - a[0]) * tt))
        g_lut.append(int(a[1] + (b[1] - a[1]) * tt))
        b_lut.append(int(a[2] + (b[2] - a[2]) * tt))
    return r_lut, g_lut, b_lut


def _add_rim(metal: Image.Image, alpha: Image.Image) -> Image.Image:
    """A thin dark rim behind the symbol so silver/gold stay legible on any bar."""
    grow = alpha.filter(ImageFilter.MaxFilter(3))
    rim = Image.new("RGBA", metal.size, (18, 16, 15, 255))
    rim.putalpha(grow)
    return Image.alpha_composite(rim, metal)


def colorize_by_rarity(symbol: Image.Image, rarity: str,
                       add_outline: bool = True) -> Image.Image:
    """Recolour a set-symbol relief into the card's rarity metal, preserving its
    shape (alpha). The symbol's own luminance becomes the metallic emboss; it is
    masked-normalized first so the result is consistent regardless of the input's
    base colour (works for the silver relief AND a themed pip-emblem)."""
    stops = RARITY_METALS.get(_normalize_rarity(rarity), RARITY_METALS["common"])
    rgba  = symbol.convert("RGBA")
    alpha = rgba.getchannel("A")
    mask  = alpha.point(lambda a: 255 if a > 24 else 0)
    lum   = rgba.convert("L")
    # Min/max of luminance WITHIN the shape (out-of-shape pushed to the opposite
    # extreme so it can't drag the range), then stretch to full 0..255.
    lo = Image.composite(lum, Image.new("L", lum.size, 255), mask).getextrema()[0]
    hi = Image.composite(lum, Image.new("L", lum.size, 0),   mask).getextrema()[1]
    if hi - lo < 8:
        lo, hi = 0, 255
    span = hi - lo
    norm = lum.point([0 if i <= lo else (255 if i >= hi else int((i - lo) * 255 / span))
                      for i in range(256)])
    r_lut, g_lut, b_lut = _metal_luts(stops)
    metal = Image.merge("RGBA", (norm.point(r_lut), norm.point(g_lut),
                                 norm.point(b_lut), alpha))
    return _add_rim(metal, alpha) if add_outline else metal


# ── Relief (theme-derived shape with a subtle metallic bevel) ───────────────────

def _render_relief(theme: str, emblem_prompt: str, size: int) -> Image.Image:
    """A neutral grayscale relief of the theme's emblem shape: mid-grey fill,
    darker edges, lighter accents, plus a soft vertical sheen so it reads as a
    bevelled metal coin. Hue-independent so colorize_by_rarity is consistent."""
    h = int(hashlib.sha256((theme or "").lower().encode()).hexdigest(), 16)
    shape_idx = h % len(_SHAPE_FUNCS)
    if emblem_prompt and emblem_prompt.strip():
        t = emblem_prompt.lower()
        for kw, idx in _SHAPE_KEYWORDS:
            if kw in t:
                shape_idx = idx
                break

    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy, r = size / 2, size / 2, size * 0.44
    # Grayscale tones → internal relief structure (fill / edge / accent).
    _SHAPE_FUNCS[shape_idx](draw, cx, cy, r, (168, 168, 168), (66, 66, 66), (224, 224, 224))

    alpha = img.getchannel("A")
    rgb   = img.convert("RGB")
    # Vertical sheen (bright top → dark bottom) overlaid → directional metal bevel.
    col = Image.new("L", (1, size))
    for y in range(size):
        col.putpixel((0, y), int(206 - 130 * (y / (size - 1))))
    sheen  = col.resize((size, size))
    relief = ImageChops.overlay(rgb, Image.merge("RGB", (sheen, sheen, sheen)))
    out = relief.convert("RGBA")
    out.putalpha(alpha)
    return out.filter(ImageFilter.SMOOTH)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_set_symbol(
    theme: str,
    size: int = SYMBOL_SIZE,
    emblem_prompt: str = "",
    rarity: str = "uncommon",
) -> Image.Image:
    """
    Generate a set symbol for the given deck theme.

    The SHAPE is derived from the deck theme (deterministic hash), overridable by
    ``emblem_prompt`` keywords (e.g. "crown", "arcane rune", "dragon crest").
    The COLOUR is the card's ``rarity`` metal (common=black, uncommon=silver,
    rare=gold, mythic=orange) — matching real MTG, where the set symbol's tint is
    the rarity indicator. Defaults to silver so the saved/displayed emblem is a
    neutral metallic; ``card_renderer`` re-tints it per card via
    ``colorize_by_rarity``.

    Returns a square RGBA PIL Image of ``size × size`` pixels.
    """
    return colorize_by_rarity(_render_relief(theme, emblem_prompt, size), rarity)


def save_set_symbol(theme: str, output_dir: Path, emblem_prompt: str = "") -> Path:
    """Generate and save the symbol PNG. Returns the file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in theme[:30])
    path = output_dir / f"set_symbol_{safe}.png"
    if not path.exists():
        img = generate_set_symbol(theme, emblem_prompt=emblem_prompt)
        img.save(path, "PNG")
    return path
